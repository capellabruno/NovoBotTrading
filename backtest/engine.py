"""
Módulo de Backtest - Motor Principal.
Executa o backtest simulando o fluxo do TradingEngine.
"""
import pandas as pd
import logging
from datetime import datetime
from typing import Dict, Any, List

from analisador.indicators import TechnicalIndicators
from analisador.strategy import Strategy
from analisador.session_filter import SessionFilter
from analisador.quality_scorer import QualityScorer
from mcp_local.server import MCPServer
from mcp_local.schemas import MarketDataInput

from .simulator import TradeSimulator, Trade
from .metrics import MetricsCalculator, BacktestMetrics

logger = logging.getLogger(__name__)


class BacktestEngine:
    """
    Motor de backtest que simula o TradingEngine em dados históricos.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Args:
            config: Configuração completa do sistema
        """
        self.config = config
        self.strategy = Strategy(config)
        self.mcp = MCPServer(config.get("mcp", {}))
        
        backtest_config = config.get("backtest", {})
        risk_config = config.get("risk", {})
        
        self.initial_balance = backtest_config.get("initial_balance", 1000.0)
        self.use_mcp = backtest_config.get("use_mcp", True)
        self.min_quality_score = config.get("quality", {}).get("min_score", 70)
        
        self.simulator = TradeSimulator(
            initial_balance=self.initial_balance,
            risk_config=risk_config
        )
        
        self.results: Dict[str, Any] = {}
    
    def run(self, symbol: str, df: pd.DataFrame) -> BacktestMetrics:
        """
        Executa backtest para um símbolo.
        
        Args:
            symbol: Par de trading
            df: DataFrame com dados históricos (timestamp, open, high, low, close, volume)
            
        Returns:
            BacktestMetrics com resultados
        """
        logger.info(f"[BACKTEST] Iniciando para {symbol} com {len(df)} candles")
        
        # 1. Calcular indicadores
        df = TechnicalIndicators.calculate_all(df)
        
        # Pular candles iniciais (warmup dos indicadores)
        warmup_period = 50
        df = df.iloc[warmup_period:].reset_index(drop=True)
        
        logger.info(f"[BACKTEST] {len(df)} candles após warmup")
        
        # 2. Iterar sobre cada candle
        for i in range(1, len(df)):
            current_candle = df.iloc[i]
            history_df = df.iloc[:i+1]  # Histórico até o candle atual
            
            current_time = datetime.fromtimestamp(current_candle['timestamp'] / 1000)
            
            # 2.1 Verificar posições abertas (SL/TP)
            if symbol in self.simulator.state.open_positions:
                closed = self.simulator.check_position(
                    symbol=symbol,
                    current_high=current_candle['high'],
                    current_low=current_candle['low'],
                    current_close=current_candle['close'],
                    current_time=current_time
                )
                if closed:
                    continue  # Não abrir nova posição no mesmo candle
            
            # 2.2 Buscar métricas atuais
            latest_metrics = TechnicalIndicators.get_latest(history_df)
            
            # 2.3 Determinar tendência
            close = latest_metrics.get('close')
            ema20 = latest_metrics.get('ema_20')
            ema50 = latest_metrics.get('ema_50')
            
            if not all([close, ema20, ema50]):
                continue
            
            trend = "SIDEWAYS"
            if ema20 > ema50 and close > ema20:
                trend = "UP"
            elif ema20 < ema50 and close < ema20:
                trend = "DOWN"
            
            # 2.4 Estratégia determinística
            signal = self.strategy.analyze(latest_metrics)
            
            if not signal:
                continue
            
            # 2.5 Análise de sessão
            session_info = SessionFilter.get_session_info(current_time)
            latest_metrics['current_session'] = session_info['current_session']
            latest_metrics['session_score'] = session_info['session_score']
            
            # 2.6 Score de qualidade
            quality_result = QualityScorer.calculate_score(latest_metrics, signal.action)
            
            if quality_result.score < self.min_quality_score:
                logger.debug(f"[{symbol}] Setup ignorado: Score {quality_result.score} < {self.min_quality_score}")
                continue
            
            # 2.7 Validação MCP (opcional no backtest - pode ser lento)
            approved = True
            if self.use_mcp:
                mcp_input = self._build_mcp_input(
                    symbol, trend, signal.action, latest_metrics, session_info, quality_result
                )
                validation = self.mcp.validate_signal(mcp_input)
                approved = validation.approved
            
            if not approved:
                logger.debug(f"[{symbol}] Setup reprovado pelo MCP")
                continue
            
            # 2.8 Calcular SL/TP (ATR-based)
            atr = latest_metrics.get('atr')
            if atr and atr > 0:
                sl_distance = atr * 1.5
                tp_distance = atr * 2.5
            else:
                sl_pct = self.config.get("risk", {}).get("stop_loss_percent", 0.01)
                tp_pct = self.config.get("risk", {}).get("take_profit_percent", 0.02)
                sl_distance = close * sl_pct
                tp_distance = close * tp_pct
            
            direction = "LONG" if signal.action == "CALL" else "SHORT"
            
            if direction == "LONG":
                stop_loss = close - sl_distance
                take_profit = close + tp_distance
            else:
                stop_loss = close + sl_distance
                take_profit = close - tp_distance
            
            # 2.9 Abrir posição
            self.simulator.open_position(
                symbol=symbol,
                direction=direction,
                entry_price=close,
                entry_time=current_time,
                stop_loss=stop_loss,
                take_profit=take_profit,
                quality_score=quality_result.score,
                candle_pattern=latest_metrics.get('candle_pattern'),
                session=session_info['current_session']
            )
        
        # 3. Fechar posições restantes ao final
        for sym in list(self.simulator.state.open_positions.keys()):
            last_candle = df.iloc[-1]
            self.simulator.close_position(
                symbol=sym,
                exit_price=last_candle['close'],
                exit_time=datetime.fromtimestamp(last_candle['timestamp'] / 1000),
                reason="END_OF_DATA"
            )
        
        # 4. Calcular métricas
        trading_days = (
            datetime.fromtimestamp(df.iloc[-1]['timestamp'] / 1000) -
            datetime.fromtimestamp(df.iloc[0]['timestamp'] / 1000)
        ).days or 1
        
        metrics = MetricsCalculator.calculate(
            trades=self.simulator.state.closed_trades,
            initial_balance=self.initial_balance,
            final_balance=self.simulator.state.balance,
            trading_days=trading_days
        )
        
        logger.info(f"[BACKTEST] Concluído: {metrics.total_trades} trades | Win Rate: {metrics.win_rate}% | Return: {metrics.total_return_pct}%")
        
        return metrics
    
    def _build_mcp_input(
        self,
        symbol: str,
        trend: str,
        signal_type: str,
        metrics: Dict,
        session_info: Dict,
        quality_result
    ) -> MarketDataInput:
        """Constrói input para validação MCP."""
        volume = metrics.get('volume', 0)
        volume_ma = metrics.get('volume_ma', 1)
        
        return MarketDataInput(
            symbol=symbol,
            timeframe="5m",
            close_price=metrics.get('close'),
            ema_20=metrics.get('ema_20'),
            ema_50=metrics.get('ema_50'),
            rsi=metrics.get('rsi'),
            volume_ratio=volume / volume_ma if volume_ma else 1.0,
            trend=trend,
            signal_type=signal_type,
            support_level=metrics.get('support_level'),
            resistance_level=metrics.get('resistance_level'),
            distance_to_support_pct=metrics.get('distance_to_support_pct'),
            distance_to_resistance_pct=metrics.get('distance_to_resistance_pct'),
            price_position=metrics.get('price_position'),
            candle_pattern=metrics.get('candle_pattern'),
            candle_pattern_type=metrics.get('candle_pattern_type'),
            current_session=session_info['current_session'],
            session_score=session_info['session_score'],
            atr=metrics.get('atr'),
            atr_percent=metrics.get('atr_percent'),
            quality_score=quality_result.score,
            quality_grade=quality_result.grade
        )
    
    def get_trades(self) -> List[Trade]:
        """Retorna lista de trades executados."""
        return self.simulator.state.closed_trades
    
    def get_summary(self) -> Dict:
        """Retorna resumo do simulador."""
        return self.simulator.get_summary()
