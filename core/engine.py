import json
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
                    # Cooldown 24h se fechou no stop-loss (perda)
                    if real_pnl < 0:
                        self.db.set_symbol_cooldown(sym, hours=24.0, reason=f"LOSS via SL/TP | PnL={sign}${real_pnl:.4f}")

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
        Analisa um símbolo usando estratégia multi-timeframe:
          - 4h: tendência de longo prazo (direção macro)
          - 1h: confirmação de tendência intermediária
          - 3m/5m: timing de entrada (pullback concluído, retomada)
        Cooldown de 24h após loss é verificado antes de qualquer análise.
        """
        logger.debug(f"[{symbol}] Iniciando análise multi-timeframe...")

        # --- 0. Cooldown após loss ---
        if self.db and not current_position:
            cooldown = self.db.get_symbol_cooldown_info(symbol)
            if cooldown:
                logger.debug(f"[{symbol}] Em cooldown por {cooldown['remaining_hours']}h ({cooldown['reason']}). Pulando.")
                if self.state:
                    self.state.update_signal(symbol, {"signal": None, "blocked": f"cooldown_{cooldown['remaining_hours']}h"})
                return None

        # --- 1. Busca candles 4h (com cache de 4h) ---
        candles_4h = self._fetch_candles_cached(symbol, interval=240, limit=200, cache_minutes=240)
        if not candles_4h:
            logger.debug(f"[{symbol}] Sem dados 4h. Pulando.")
            return None

        # --- 2. Busca candles 1h (com cache de 1h) ---
        candles_1h = self._fetch_candles_cached(symbol, interval=60, limit=200, cache_minutes=60)
        if not candles_1h:
            logger.debug(f"[{symbol}] Sem dados 1h. Pulando.")
            return None

        try:
            df_4h = self._build_df(candles_4h)
            df_1h = self._build_df(candles_1h)
        except Exception as e:
            logger.error(f"[{symbol}] Erro ao processar DataFrames: {e}")
            return None

        # --- 3. Indicadores em ambos os timeframes ---
        df_4h = TechnicalIndicators.calculate_all(df_4h)
        metrics_4h = TechnicalIndicators.get_latest(df_4h)

        df_1h = TechnicalIndicators.calculate_all(df_1h)
        metrics_1h = TechnicalIndicators.get_latest(df_1h)

        close = metrics_1h.get('close')  # preço atual = candle 1h mais recente
        if self.state and close:
            self.state.update_price(symbol, close)

        # --- 4. Tendência macro (4h) ---
        ema20_4h = metrics_4h.get('ema_20')
        ema50_4h = metrics_4h.get('ema_50')
        trend_4h = "SIDEWAYS"
        if ema20_4h and ema50_4h:
            close_4h = metrics_4h.get('close')
            if ema20_4h > ema50_4h and close_4h > ema20_4h:
                trend_4h = "UP"
            elif ema20_4h < ema50_4h and close_4h < ema20_4h:
                trend_4h = "DOWN"

        # --- 5. Tendência intermediária (1h) ---
        ema20_1h = metrics_1h.get('ema_20')
        ema50_1h = metrics_1h.get('ema_50')
        trend_1h = "SIDEWAYS"
        if ema20_1h and ema50_1h:
            if ema20_1h > ema50_1h and close > ema20_1h:
                trend_1h = "UP"
            elif ema20_1h < ema50_1h and close < ema20_1h:
                trend_1h = "DOWN"

        # Tendência consolidada: ambos devem concordar
        if trend_4h == trend_1h and trend_4h != "SIDEWAYS":
            trend = trend_4h
        else:
            trend = "SIDEWAYS"

        logger.debug(f"[{symbol}] Tendência 4h={trend_4h} | 1h={trend_1h} | Consolidada={trend}")

        # --- Lógica de Saída por Tendência (posição existente) ---
        if current_position:
            side = current_position.get("side")
            pnl = float(current_position.get("unrealisedPnl", 0))
            rsi = metrics_1h.get('rsi', 50)

            should_close = False
            close_reason = ""

            if side == "Buy" and trend_4h == "DOWN":
                close_reason = "Reversão 4h (UP -> DOWN)"
                if pnl >= 0:
                    should_close = True
                    close_reason += " | Lucro garantido"
                elif rsi < 40:
                    should_close = True
                    close_reason += f" | RSI 1h confirmado ({rsi:.1f} < 40)"
                else:
                    logger.debug(f"[{symbol}] Saída adiada: PnL={pnl:.2f} RSI={rsi:.1f}")

            elif side == "Sell" and trend_4h == "UP":
                close_reason = "Reversão 4h (DOWN -> UP)"
                if pnl >= 0:
                    should_close = True
                    close_reason += " | Lucro garantido"
                elif rsi > 60:
                    should_close = True
                    close_reason += f" | RSI 1h confirmado ({rsi:.1f} > 60)"
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
                        # Cooldown 24h se saída com perda
                        if real_pnl < 0:
                            self.db.set_symbol_cooldown(symbol, hours=24.0, reason=f"LOSS via reversão | PnL={real_pnl:.4f}")
            return None

        # Sem tendência clara nos dois timeframes → não entrar
        if trend == "SIDEWAYS":
            if self.state:
                self.state.update_signal(symbol, {"signal": None, "trend": trend, "trend_4h": trend_4h, "trend_1h": trend_1h})
            return None

        # --- 6. Estratégia no 1h (métricas intermediárias) ---
        signal = self.strategy.analyze(metrics_1h)
        if not signal:
            if self.state:
                self.state.update_signal(symbol, {"signal": None, "trend": trend})
            return None

        # Validar alinhamento do sinal com tendência macro
        if (signal.action == "CALL" and trend != "UP") or (signal.action == "PUT" and trend != "DOWN"):
            logger.debug(f"[{symbol}] Sinal {signal.action} contra tendência {trend}. Ignorando.")
            return None

        # --- 7. Sessão de Mercado ---
        session_info = SessionFilter.get_session_info()
        metrics_1h['current_session'] = session_info['current_session']
        metrics_1h['session_score'] = session_info['session_score']

        # --- 8. Score de Qualidade ---
        quality_result = QualityScorer.calculate_score(metrics_1h, signal.action)
        min_score = self.config.get("quality", {}).get("min_score", 70)
        if quality_result.score < min_score:
            logger.debug(f"[{symbol}] Score {quality_result.score} < {min_score}. Bloqueado.")
            if self.state:
                self.state.update_signal(symbol, {
                    "signal": signal.action, "trend": trend,
                    "quality_score": quality_result.score, "blocked": "quality_score"
                })
            return None

        # Verificar trade já aberto no DB
        if self.db:
            open_for_symbol = [t for t in self.db.get_open_trades(mode="live") if t["symbol"] == symbol]
            if open_for_symbol:
                return None

        # --- 9. Timing de Entrada — 3m ou 5m ---
        entry_ok, entry_context = self._check_entry_timing(symbol, signal.action)
        if not entry_ok:
            logger.debug(f"[{symbol}] Timing de entrada desfavorável (3m/5m): {entry_context}")
            if self.state:
                self.state.update_signal(symbol, {
                    "signal": signal.action, "trend": trend,
                    "quality_score": quality_result.score, "blocked": "entry_timing"
                })
            return None

        # --- 10. Validação MCP ---
        volume_ma = metrics_1h.get('volume_ma')
        volume = metrics_1h.get('volume')
        volume_ratio = (volume / volume_ma) if (volume_ma and volume_ma > 0) else 1.0

        mcp_input = MarketDataInput(
            symbol=symbol, timeframe="1h+4h", close_price=close,
            ema_20=ema20_1h, ema_50=ema50_1h, rsi=metrics_1h.get('rsi'),
            volume_ratio=volume_ratio, trend=trend, signal_type=signal.action,
            support_level=metrics_1h.get('support_level'),
            resistance_level=metrics_1h.get('resistance_level'),
            distance_to_support_pct=metrics_1h.get('distance_to_support_pct'),
            distance_to_resistance_pct=metrics_1h.get('distance_to_resistance_pct'),
            price_position=metrics_1h.get('price_position'),
            candle_pattern=metrics_1h.get('candle_pattern'),
            candle_pattern_type=metrics_1h.get('candle_pattern_type'),
            current_session=session_info['current_session'],
            session_score=session_info['session_score'],
            atr=metrics_1h.get('atr'),
            atr_percent=metrics_1h.get('atr_percent'),
            quality_score=quality_result.score,
            quality_grade=quality_result.grade,
            entry_context_3m=entry_context,
        )

        validation = self.mcp.validate_signal(mcp_input)

        if self.state:
            self.state.update_signal(symbol, {
                "signal": signal.action, "trend": trend,
                "trend_4h": trend_4h, "trend_1h": trend_1h,
                "quality_score": quality_result.score, "quality_grade": quality_result.grade,
                "mcp_approved": validation.approved, "mcp_confidence": validation.confidence,
                "session": session_info['current_session'], "price": close,
                "rsi": metrics_1h.get('rsi'),
                "blocked": None if validation.approved else "mcp_rejected",
            })

        if not validation.approved:
            logger.debug(f"[{symbol}] Sinal rejeitado pelo MCP (confiança={validation.confidence:.2f}).")
            return None

        # --- 11. SL/TP baseado no ATR do 1h (operação swing) ---
        use_atr_stops = self.config.get("quality", {}).get("use_atr_stops", True)
        atr = metrics_1h.get('atr')

        # Estratégia longo prazo: SL curto (ATR 1h), TP amplo (múltiplos ATR 4h)
        # RR alvo ≥ 5x — protege capital com stop apertado, deixa lucros correrem
        atr_4h = metrics_4h.get('atr')

        if use_atr_stops and atr and atr > 0:
            # SL = 0.8x ATR do 1h (stop apertado próximo ao preço)
            atr_pct_1h = atr / close
            sl_percent = max(atr_pct_1h * 0.8, 0.008)    # mínimo 0.8%

            # TP = 5x ATR do 4h (alvos amplos de swing)
            if atr_4h and atr_4h > 0:
                atr_pct_4h = atr_4h / close
                tp_percent = max(atr_pct_4h * 5.0, sl_percent * 5.0)  # mínimo RR 5:1
            else:
                tp_percent = max(atr_pct_1h * 6.0, sl_percent * 5.0)

            # Garantir mínimo de 2% de TP para ser relevante
            tp_percent = max(tp_percent, 0.02)

            logger.debug(f"[{symbol}] SL={sl_percent*100:.2f}% TP={tp_percent*100:.2f}% (RR={tp_percent/sl_percent:.1f}x)")
        else:
            sl_percent = self.config.get("risk", {}).get("stop_loss_percent", 0.01)
            tp_percent = self.config.get("risk", {}).get("take_profit_percent", 0.08)

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
            "latest_metrics": metrics_1h,
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

    def _build_df(self, candles: list) -> pd.DataFrame:
        cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'turnover']
        df = pd.DataFrame(candles, columns=cols)
        for col in ['timestamp', 'open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col])
        return df.sort_values('timestamp').reset_index(drop=True)

    def _fetch_candles_cached(self, symbol: str, interval: int, limit: int, cache_minutes: int) -> Optional[list]:
        """
        Busca candles com cache no DB. Se o cache ainda for válido, evita chamada à API.
        """
        if self.db:
            cached_json = self.db.get_candles_cache(symbol, interval, max_age_minutes=cache_minutes)
            if cached_json:
                try:
                    return json.loads(cached_json)
                except Exception:
                    pass

        candles = self.bybit.fetch_candles(symbol=symbol, interval=interval, limit=limit)
        if candles and self.db:
            try:
                self.db.save_candles_cache(symbol, interval, json.dumps(candles))
            except Exception as e:
                logger.warning(f"[{symbol}] Falha ao salvar cache {interval}m: {e}")
        return candles

    def _check_entry_timing(self, symbol: str, signal_type: str) -> tuple[bool, str]:
        """
        Verifica timing de entrada em 3m (fallback 5m).
        Procura pullback concluído + candle de retomada na direção do sinal.
        Retorna (ok: bool, contexto: str).
        """
        # Tentar 3m primeiro, depois 5m
        for tf in [3, 5]:
            candles = self.bybit.fetch_candles(symbol=symbol, interval=tf, limit=30)
            if candles and len(candles) >= 10:
                try:
                    df = self._build_df(candles)
                    closes = df['close'].values
                    highs = df['high'].values
                    lows = df['low'].values

                    c0 = closes[-1]  # candle atual
                    c1 = closes[-2]  # anterior
                    c2 = closes[-3]

                    if signal_type == "CALL":
                        # Pullback: c2 ou c1 foi recuo (c1 < c2), agora retomando (c0 > c1)
                        pullback_ocorreu = c1 < c2 or lows[-2] < lows[-3]
                        retomada = c0 > c1
                        if pullback_ocorreu and retomada:
                            return True, f"Pullback concluído em {tf}m. Retomada alta confirmada ({c1:.4f}→{c0:.4f})."
                        elif retomada:
                            # Aceita se simplesmente subindo (sem pullback claro)
                            return True, f"Preço subindo em {tf}m. Timing favorável ({c1:.4f}→{c0:.4f})."
                        else:
                            return False, f"Aguardando retomada em {tf}m. Preço ainda recuando ({c0:.4f} ≤ {c1:.4f})."

                    elif signal_type == "PUT":
                        pullback_ocorreu = c1 > c2 or highs[-2] > highs[-3]
                        retomada = c0 < c1
                        if pullback_ocorreu and retomada:
                            return True, f"Pullback concluído em {tf}m. Retomada baixa confirmada ({c1:.4f}→{c0:.4f})."
                        elif retomada:
                            return True, f"Preço caindo em {tf}m. Timing favorável ({c1:.4f}→{c0:.4f})."
                        else:
                            return False, f"Aguardando retomada em {tf}m. Preço ainda corrigindo ({c0:.4f} ≥ {c1:.4f})."

                except Exception as e:
                    logger.warning(f"[{symbol}] Erro no timing {tf}m: {e}")
                    continue

        # Sem dados suficientes → não bloquear (deixar MCP decidir)
        return True, "Sem dados suficientes para timing de curto prazo."
