import logging
import pandas as pd
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, Any, Optional

from analisador.indicators import TechnicalIndicators
from analisador.strategy import Strategy, Signal
from analisador.session_filter import SessionFilter
from analisador.quality_scorer import QualityScorer
from mcp_local.server import MCPServer
from mcp_local.schemas import MarketDataInput
from mcp_local.tools import format_signal_message
from execution.bybit_client import BybitClient
from services.notifications.telegram_notifier import TelegramNotifier, TopicType
from core.optimizer import AdaptiveOptimizer

logger = logging.getLogger(__name__)


class TradingEngine:
    def __init__(self, config: Dict[str, Any],
                 state_manager=None,
                 db_manager=None):
        self.config = config
        self.strategy = Strategy(config)
        self.mcp = MCPServer(config.get("mcp", {}), db_manager=db_manager)
        self.bybit = BybitClient(config)
        self.telegram = TelegramNotifier(config)
        self.optimizer = AdaptiveOptimizer(config)

        # Integração com StateManager e DatabaseManager (opcionais)
        self.state = state_manager
        self.db = db_manager

        # Suporte a multiplos simbolos - carrega todos da Bybit dinamicamente
        system_conf = config.get("system", {})
        use_all_symbols = system_conf.get("use_all_symbols", False)

        if use_all_symbols:
            self.symbols = self.bybit.get_all_symbols()
            if not self.symbols:
                logger.warning("Falha ao buscar símbolos da Bybit. Usando fallback do settings.yaml.")
                self.symbols = system_conf.get("symbols", [system_conf.get("symbol", "BTCUSDT")])
        elif "symbols" in system_conf:
            self.symbols = system_conf.get("symbols")
        else:
            self.symbols = [system_conf.get("symbol", "BTCUSDT")]

        # Número de workers para análise paralela por símbolo
        self._symbol_workers = system_conf.get("symbol_workers", 10)

        # Publicar config no state
        if self.state:
            self.state.update_config(config)
            self.state.set_running(dry_run=config.get("system", {}).get("dry_run", True))

        # Otimização inicial se necessário
        if config.get("adaptive", {}).get("enabled", False):
            self.optimizer.optimize_all(self.symbols)

        self._cycle_count = 0

    def run_cycle(self):
        """
        Executa um ciclo completo de análise para CADA símbolo.
        """
        self._cycle_count += 1
        dry_run = self.config.get("system", {}).get("dry_run", True)
        mode_label = "DRY RUN" if dry_run else "LIVE"
        logger.info(f"=== Ciclo #{self._cycle_count} | Modo: {mode_label} ===")

        if self.state:
            self.state.start_cycle(self._cycle_count)

        # 0. Cache de posições atuais para evitar rate limit
        active_positions = self.bybit.get_positions()
        positions_map = {p['symbol']: p for p in active_positions}

        if self.state:
            self.state.update_positions(positions_map)

        # --- Detectar fechamentos por SL/TP (exchange-side) ---
        if self.db and not dry_run:
            self._reconcile_closed_trades(positions_map)

        # Atualizar saldo
        balance = self.bybit.get_balance()
        if self.state:
            self.state.update_balance(balance)

        # Limite de posições simultâneas (configurável)
        max_positions = self.config.get("risk", {}).get("max_open_positions", 2)
        current_open = len(active_positions)
        slots_available = max(0, max_positions - current_open)

        # --- FASE 1: Analisar todos os símbolos em paralelo ---
        candidates = []

        if slots_available == 0:
            logger.info(f"Limite de posições atingido ({current_open}/{max_positions}). Aguardando slot.")
        else:

            def analyze_worker(symbol: str):
                return self.analyze_symbol(symbol, positions_map.get(symbol))

            with ThreadPoolExecutor(max_workers=self._symbol_workers, thread_name_prefix="symbol_agent") as executor:
                future_map = {executor.submit(analyze_worker, sym): sym for sym in self.symbols}
                for future in as_completed(future_map):
                    sym = future_map[future]
                    try:
                        result = future.result(timeout=120)
                        if result:
                            candidates.append(result)
                    except Exception as exc:
                        logger.error(f"[{sym}] Erro no agente de análise: {exc}")

        # --- FASE 2: Selecionar os melhores e executar ---
        if candidates and slots_available > 0:
            candidates.sort(key=lambda x: (x["quality_score"], x["mcp_confidence"]), reverse=True)
            selected = candidates[:slots_available]
            logger.info(f"{len(candidates)} candidato(s) aprovado(s). Executando {len(selected)}.")
            for candidate in selected:
                self.execute_signal(candidate)
                time.sleep(3)
        elif not candidates:
            logger.info("Nenhum candidato válido neste ciclo.")

        # Salvar snapshot no DB
        if self.db:
            self.db.save_snapshot(
                balance=balance,
                open_positions=len(active_positions),
                symbols_analyzed=len(self.symbols),
                cycle_number=self._cycle_count,
            )

        # Relatório de Conta após processar símbolos
        self.send_account_report()

    def _reconcile_closed_trades(self, positions_map: dict):
        """
        Detecta trades que foram fechados pela exchange via SL/TP
        (não pelo código de reversão de tendência) e registra o PnL real no DB.
        """
        try:
            open_db_trades = self.db.get_open_trades(mode="live")
            if not open_db_trades:
                return

            # Buscar PnL fechado da exchange (ordenado mais recente primeiro)
            closed_pnl_list = self.bybit.get_closed_pnl()
            # Indexar por símbolo (mais recente por símbolo)
            pnl_by_symbol = {}
            for entry in closed_pnl_list:
                sym = entry.get("symbol")
                if sym and sym not in pnl_by_symbol:
                    pnl_by_symbol[sym] = entry

            for trade in open_db_trades:
                sym = trade.get("symbol")
                # Se não há posição aberta na exchange mas temos no DB -> fechado por SL/TP
                if sym not in positions_map:
                    pnl_entry = pnl_by_symbol.get(sym)

                    # Validar: só fechar se PnL não-zero OU se passou mais de 2 ciclos (10 min)
                    # para evitar registrar PnL=0 quando a Bybit ainda está processando
                    if pnl_entry is None:
                        logger.warning(f"[{sym}] Posição fechada mas sem PnL na API ainda. Aguardando próximo ciclo.")
                        continue

                    real_pnl = float(pnl_entry.get("closedPnl", 0))
                    exit_price = float(pnl_entry.get("avgExitPrice", 0))

                    if real_pnl == 0.0 and exit_price == 0.0:
                        logger.warning(f"[{sym}] PnL e exitPrice zerados na API. Aguardando próximo ciclo para processar.")
                        continue

                    if exit_price == 0.0:
                        exit_price = trade.get("entry_price", 0.0)

                    sign = "+" if real_pnl >= 0 else ""
                    logger.info(f"[{sym}] SL/TP atingido pela exchange | PnL: {sign}${real_pnl:.4f}")
                    self.db.close_trade_by_symbol(
                        symbol=sym,
                        exit_price=exit_price,
                        pnl=real_pnl,
                        exit_reason="SL_TP"
                    )
                    self.telegram.notify_close(sym, real_pnl, 0.0, "SL/TP atingido")

        except Exception as e:
            logger.error(f"Erro na reconciliação de trades: {e}")

    def send_account_report(self):
        try:
            balance = self.bybit.get_balance()
            positions = self.bybit.get_positions()

            msg = f"📊 <b>Relatório de Conta</b>\n\n💰 Saldo: ${balance:.2f} USDT\n"

            if positions:
                msg += f"\n🔓 <b>Posições Abertas ({len(positions)}):</b>\n"
                for p in positions:
                    symbol = p.get("symbol", "")
                    side = p.get("side", "")
                    size = p.get("size", "")
                    pnl = float(p.get("unrealisedPnl", 0))
                    sign = "+" if pnl >= 0 else ""
                    msg += f"- {symbol} ({side}): {size} | PnL: {sign}${pnl:.2f}\n"
            else:
                msg += "\n✅ Nenhuma posição aberta."

            logger.debug("Enviando relatório de conta...")
            self.telegram.manager.send_message(TopicType.PORTFOLIO, msg)

        except Exception as e:
            logger.error(f"Erro ao gerar relatório: {e}")

    def send_daily_report(self):
        """
        Gera e envia o relatório diário de PnL (23:00)
        """
        logger.debug("Gerando relatório diário...")
        try:
            now = datetime.utcnow()
            start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
            start_time_ms = int(start_of_day.timestamp() * 1000)

            pnl_list = self.bybit.get_closed_pnl(start_time=start_time_ms)

            total_trades = len(pnl_list)
            total_pnl = 0.0
            wins = 0
            losses = 0

            for trade in pnl_list:
                pnl = float(trade.get("closedPnl", 0))
                total_pnl += pnl
                if pnl > 0:
                    wins += 1
                elif pnl < 0:
                    losses += 1

            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
            emoji_pnl = "🟢" if total_pnl >= 0 else "🔴"

            sign = "+" if total_pnl >= 0 else ""
            msg = (
                f"📅 <b>Relatório Diário</b> ({start_of_day.strftime('%d/%m/%Y')})\n\n"
                f"🔢 <b>Total Ordens:</b> {total_trades}\n"
                f"✅ <b>Ganhos:</b> {wins}\n"
                f"❌ <b>Perdas:</b> {losses}\n"
                f"🎯 <b>Win Rate:</b> {win_rate:.1f}%\n\n"
                f"{emoji_pnl} <b>PnL do Dia:</b> {sign}${total_pnl:.2f} USDT\n"
            )

            self.telegram.manager.send_message(TopicType.DAILY_REPORT, msg)

        except Exception as e:
            logger.error(f"Erro ao enviar relatório diário: {e}")
            self.telegram.notify_error("DailyReport", str(e))

    def analyze_symbol(self, symbol: str, current_position: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        """
        Analisa um símbolo e retorna um candidato para execução, ou None.
        Se houver posição aberta, cuida da lógica de saída por reversão de tendência.
        """
        logger.debug(f"[{symbol}] Iniciando análise...")

        interval = 15

        # 1. Busca dados
        candles = self.bybit.fetch_candles(symbol=symbol, interval=interval, limit=200)
        if not candles:
            logger.debug(f"[{symbol}] Nenhum dado recebido. Pulando.")
            return None

        try:
            cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'turnover']
            df = pd.DataFrame(candles, columns=cols)
            df['timestamp'] = pd.to_numeric(df['timestamp'])
            df['open'] = pd.to_numeric(df['open'])
            df['high'] = pd.to_numeric(df['high'])
            df['low'] = pd.to_numeric(df['low'])
            df['close'] = pd.to_numeric(df['close'])
            df['volume'] = pd.to_numeric(df['volume'])
            df = df.sort_values('timestamp').reset_index(drop=True)
        except Exception as e:
            logger.error(f"[{symbol}] Erro ao processar DataFrame: {e}")
            self.telegram.notify_error(f"DataProc_{symbol}", str(e))
            return None

        # 2. Calcula Indicadores
        df = TechnicalIndicators.calculate_all(df)
        latest_metrics = TechnicalIndicators.get_latest(df)

        close = latest_metrics.get('close')

        if self.state and close:
            self.state.update_price(symbol, close)

        # 3. Tendência
        ema20 = latest_metrics.get('ema_20')
        ema50 = latest_metrics.get('ema_50')

        trend = "SIDEWAYS"
        if ema20 > ema50 and close > ema20:
            trend = "UP"
        elif ema20 < ema50 and close < ema20:
            trend = "DOWN"

        # --- Lógica de Saída por Tendência (posição existente) ---
        if current_position:
            side = current_position.get("side")
            pnl = float(current_position.get("unrealisedPnl", 0))
            rsi = latest_metrics.get('rsi', 50)

            should_close = False
            close_reason = ""

            if side == "Buy" and trend == "DOWN":
                close_reason = "Reversão de Tendência (UP -> DOWN)"
                if pnl >= 0:
                    should_close = True
                    close_reason += " | Lucro garantido"
                elif rsi < 40:
                    should_close = True
                    close_reason += f" | RSI Confirmado ({rsi:.1f} < 40)"
                else:
                    logger.debug(f"[{symbol}] Saída adiada: PnL={pnl:.2f} RSI={rsi:.1f}")

            elif side == "Sell" and trend == "UP":
                close_reason = "Reversão de Tendência (DOWN -> UP)"
                if pnl >= 0:
                    should_close = True
                    close_reason += " | Lucro garantido"
                elif rsi > 60:
                    should_close = True
                    close_reason += f" | RSI Confirmado ({rsi:.1f} > 60)"
                else:
                    logger.debug(f"[{symbol}] Saída adiada: PnL={pnl:.2f} RSI={rsi:.1f}")

            if should_close:
                logger.info(f"[{symbol}] FECHANDO POSIÇÃO | {side} | Motivo: {close_reason} | PnL: {pnl:.2f}")
                success = self.bybit.close_position(symbol)
                if success:
                    real_pnl = pnl
                    try:
                        time.sleep(1)
                        pnl_list = self.bybit.get_closed_pnl()
                        for entry in pnl_list:
                            if entry.get("symbol") == symbol:
                                real_pnl = float(entry.get("closedPnl", pnl))
                                break
                    except Exception as e:
                        logger.warning(f"[{symbol}] Não foi possível buscar PnL real: {e}")

                    self.telegram.notify_close(symbol, real_pnl, 0.0, close_reason)
                    if self.db:
                        self.db.close_trade_by_symbol(
                            symbol=symbol, exit_price=close,
                            pnl=real_pnl, exit_reason="TREND_REVERSAL"
                        )
            # Posição aberta: não entrar em nova posição para este símbolo
            return None

        # 4. Estratégia Determinística (Entrada)
        signal = self.strategy.analyze(latest_metrics)

        if not signal:
            if self.state:
                self.state.update_signal(symbol, {"signal": None, "trend": trend})
            return None

        # 5. Sessão de Mercado
        session_info = SessionFilter.get_session_info()
        latest_metrics['current_session'] = session_info['current_session']
        latest_metrics['session_score'] = session_info['session_score']

        # 6. Score de Qualidade
        quality_result = QualityScorer.calculate_score(latest_metrics, signal.action)

        min_score = self.config.get("quality", {}).get("min_score", 70)
        if quality_result.score < min_score:
            logger.debug(f"[{symbol}] Score {quality_result.score} < {min_score}. Bloqueado.")
            if self.state:
                self.state.update_signal(symbol, {
                    "signal": signal.action, "trend": trend,
                    "quality_score": quality_result.score, "blocked": "quality_score"
                })
            return None

        # Verificar se já existe trade aberto para este símbolo
        if self.db:
            open_for_symbol = [t for t in self.db.get_open_trades(mode="live") if t["symbol"] == symbol]
            if open_for_symbol:
                return None

        # 7. Refinamento de Entrada (3m)
        candles_3m = self.bybit.fetch_candles(symbol=symbol, interval=3, limit=50)
        entry_context_3m = self._analyze_3m_entry(symbol, candles_3m, signal.action)

        # 8. Validação MCP
        volume_ma = latest_metrics.get('volume_ma')
        volume = latest_metrics.get('volume')
        volume_ratio = (volume / volume_ma) if (volume_ma and volume_ma > 0) else 1.0

        mcp_input = MarketDataInput(
            symbol=symbol, timeframe="15m", close_price=close,
            ema_20=ema20, ema_50=ema50, rsi=latest_metrics.get('rsi'),
            volume_ratio=volume_ratio, trend=trend, signal_type=signal.action,
            support_level=latest_metrics.get('support_level'),
            resistance_level=latest_metrics.get('resistance_level'),
            distance_to_support_pct=latest_metrics.get('distance_to_support_pct'),
            distance_to_resistance_pct=latest_metrics.get('distance_to_resistance_pct'),
            price_position=latest_metrics.get('price_position'),
            candle_pattern=latest_metrics.get('candle_pattern'),
            candle_pattern_type=latest_metrics.get('candle_pattern_type'),
            current_session=session_info['current_session'],
            session_score=session_info['session_score'],
            atr=latest_metrics.get('atr'),
            atr_percent=latest_metrics.get('atr_percent'),
            quality_score=quality_result.score,
            quality_grade=quality_result.grade,
            entry_context_3m=entry_context_3m
        )

        validation = self.mcp.validate_signal(mcp_input)

        # Atualizar state
        if self.state:
            self.state.update_signal(symbol, {
                "signal": signal.action, "trend": trend,
                "quality_score": quality_result.score, "quality_grade": quality_result.grade,
                "mcp_approved": validation.approved, "mcp_confidence": validation.confidence,
                "session": session_info['current_session'], "price": close,
                "rsi": latest_metrics.get('rsi'),
                "blocked": None if validation.approved else "mcp_rejected",
            })

        if not validation.approved:
            logger.debug(f"[{symbol}] Sinal rejeitado pelo MCP (confiança={validation.confidence:.2f}).")
            return None

        # Calcular SL/TP ajustados ao timeframe (curto prazo = alvos menores e rápidos)
        use_atr_stops = self.config.get("quality", {}).get("use_atr_stops", True)
        atr = latest_metrics.get('atr')

        # Multiplicadores ATR por timeframe:
        # Timeframe curto (≤15m) → operação intraday curta → TP: 20-50% do ATR do período
        # Timeframe médio (30-60m) → swing intraday
        # Timeframe longo (≥4h) → swing/posicional
        _tf_multipliers = {
            1:    (0.5, 0.8),   # 1m  - scalp extremo
            3:    (0.6, 1.0),   # 3m  - scalp
            5:    (0.7, 1.2),   # 5m  - scalp
            15:   (0.8, 1.5),   # 15m - curto prazo  ← operação atual
            30:   (1.0, 2.0),   # 30m - intraday
            60:   (1.2, 2.5),   # 1h  - swing intraday
            240:  (1.5, 3.0),   # 4h  - swing
            1440: (2.0, 4.0),   # 1D  - posicional
        }
        sl_mult, tp_mult = _tf_multipliers.get(interval, (0.8, 1.5))

        if use_atr_stops and atr and atr > 0:
            atr_pct = atr / close
            sl_percent = max(atr_pct * sl_mult, 0.008)   # mínimo 0.8%
            tp_percent = max(atr_pct * tp_mult, 0.012)   # mínimo 1.2%

            # Garantir RR ≥ 1.5 (TP deve ser ao menos 1.5x o SL)
            if tp_percent < sl_percent * 1.5:
                tp_percent = sl_percent * 1.5

            logger.debug(f"[{symbol}] ATR Stop: SL={sl_percent*100:.2f}% TP={tp_percent*100:.2f}%")
        else:
            sl_percent = self.config.get("risk", {}).get("stop_loss_percent", 0.02)
            tp_percent = self.config.get("risk", {}).get("take_profit_percent", 0.03)

        return {
            "symbol": symbol,
            "signal": signal.action,
            "signal_obj": signal,
            "quality_score": quality_result.score,
            "quality_grade": quality_result.grade,
            "mcp_confidence": validation.confidence,
            "validation": validation,
            "close": close,
            "sl_percent": sl_percent,
            "tp_percent": tp_percent,
            "direction": "LONG" if signal.action.upper() == "CALL" else "SHORT",
            "session_info": session_info,
            "latest_metrics": latest_metrics,
        }

    def execute_signal(self, candidate: Dict[str, Any]):
        """
        Executa a ordem para o candidato selecionado e registra no DB + Telegram.
        """
        symbol = candidate["symbol"]
        signal = candidate["signal_obj"]
        close = candidate["close"]
        sl_percent = candidate["sl_percent"]
        tp_percent = candidate["tp_percent"]
        direction = candidate["direction"]
        session_info = candidate["session_info"]
        latest_metrics = candidate["latest_metrics"]
        quality_result_score = candidate["quality_score"]
        quality_result_grade = candidate["quality_grade"]
        validation = candidate["validation"]

        amount_usdt = max(
            self.config.get("risk", {}).get("account_balance_fixed", 100)
            * self.config.get("risk", {}).get("entry_percent", 0.1),
            5.0
        )

        logger.info(f"[{symbol}] ABRINDO POSIÇÃO | {direction} | Entrada=${close:.4f} | SL={sl_percent*100:.1f}% | TP={tp_percent*100:.1f}% | ${amount_usdt:.2f}")

        order_response = self.bybit.execute_order(
            symbol=symbol,
            action=signal.action,
            amount=amount_usdt,
            current_price=close,
            sl_percent=sl_percent,
            tp_percent=tp_percent
        )

        dry_run = self.config.get("system", {}).get("dry_run", True)
        order_accepted = dry_run or (
            order_response is not None and
            isinstance(order_response, dict) and
            order_response.get("retCode", -1) == 0
        )

        if not order_accepted:
            logger.warning(f"[{symbol}] Ordem rejeitada pela exchange. Não registrando no DB.")
            return

        # Calcular preços de SL/TP
        if direction == "LONG":
            sl_price = close * (1 - sl_percent)
            tp_price = close * (1 + tp_percent)
        else:
            sl_price = close * (1 + sl_percent)
            tp_price = close * (1 - tp_percent)

        if self.db:
            order_id = None
            if order_response and isinstance(order_response, dict):
                order_id = order_response.get("result", {}).get("orderId")

            qty = amount_usdt / close if close > 0 else 0

            self.db.save_trade_entry(
                symbol=symbol,
                direction=direction,
                entry_price=close,
                size_usdt=amount_usdt,
                quantity=qty,
                stop_loss=sl_price,
                take_profit=tp_price,
                quality_score=quality_result_score,
                quality_grade=quality_result_grade,
                candle_pattern=latest_metrics.get('candle_pattern'),
                session=session_info['current_session'],
                mcp_confidence=validation.confidence,
                order_id=order_id,
                mode="dry_run" if dry_run else "live",
            )

        self.telegram.notify_trade(
            symbol=symbol,
            direction=direction,
            action="OPEN",
            price=close,
            size=amount_usdt,
            reason=f"{signal.reason} (Confiança MCP: {validation.confidence})"
        )

    def _analyze_3m_entry(self, symbol: str, candles: list, signal_type: str) -> str:
        if not candles or len(candles) < 5:
            return "Dados insuficientes para análise 3m."

        try:
            cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'turnover']
            df = pd.DataFrame(candles, columns=cols)
            df['close'] = pd.to_numeric(df['close'])

            last_close = df['close'].iloc[-1]
            prev_close = df['close'].iloc[-2]

            if signal_type == "CALL":
                if last_close > prev_close:
                    return f"FOGO: Preço subindo em 3m ({last_close} > {prev_close}). Timing ideal."
                else:
                    return f"AGUARDE: Preço recuando em 3m ({last_close} <= {prev_close}). Possível pullback."
            elif signal_type == "PUT":
                if last_close < prev_close:
                    return f"FOGO: Preço caindo em 3m ({last_close} < {prev_close}). Timing ideal."
                else:
                    return f"AGUARDE: Preço subindo em 3m ({last_close} >= {prev_close}). Possível pullback."

            return "Contexto 3m neutro."

        except Exception as e:
            logger.error(f"Erro na análise 3m para {symbol}: {e}")
            return f"Erro analise 3m: {e}"
