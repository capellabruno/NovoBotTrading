"""
Módulo de Backtest - Simulador de Ordens.
Simula a execução de ordens e calcula PnL.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

@dataclass
class Trade:
    """Representa uma operação (entrada + saída)."""
    symbol: str
    entry_time: datetime
    entry_price: float
    direction: str  # "LONG" ou "SHORT"
    size: float  # Em USDT
    stop_loss: float
    take_profit: float
    
    # Preenchidos no fechamento
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""  # "TP", "SL", "SIGNAL", "TREND_REVERSAL"
    pnl: float = 0.0
    pnl_percent: float = 0.0
    
    # Dados extras para análise
    quality_score: Optional[int] = None
    candle_pattern: Optional[str] = None
    session: Optional[str] = None


@dataclass
class SimulatorState:
    """Estado atual do simulador."""
    balance: float
    initial_balance: float
    open_positions: Dict[str, Trade] = field(default_factory=dict)
    closed_trades: List[Trade] = field(default_factory=list)
    
    # Estatísticas
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    max_balance: float = 0.0
    min_balance: float = float('inf')
    max_drawdown: float = 0.0
    consecutive_losses: int = 0
    max_consecutive_losses: int = 0


class TradeSimulator:
    """
    Simulador de trades para backtest.
    Gerencia posições e calcula PnL.
    """
    
    def __init__(self, initial_balance: float = 1000.0, risk_config: Dict = None):
        """
        Args:
            initial_balance: Saldo inicial em USDT
            risk_config: Configurações de risco
        """
        self.state = SimulatorState(
            balance=initial_balance,
            initial_balance=initial_balance,
            max_balance=initial_balance
        )
        
        self.risk_config = risk_config or {
            "entry_percent": 0.10,
            "max_positions": 3,
            "daily_loss_limit": 0.20,
            "max_consecutive_losses": 2
        }
        
        self.daily_pnl = 0.0
        self.daily_loss_limit_hit = False
    
    def can_open_position(self, symbol: str) -> tuple:
        """
        Verifica se pode abrir nova posição.
        
        Returns:
            (pode_operar: bool, razão: str)
        """
        # Verificar se já tem posição no símbolo
        if symbol in self.state.open_positions:
            return False, "Já existe posição aberta para este símbolo"
        
        # Verificar limite de posições
        if len(self.state.open_positions) >= self.risk_config.get("max_positions", 3):
            return False, "Limite de posições abertas atingido"
        
        # Verificar limite diário de perda
        if self.daily_loss_limit_hit:
            return False, "Limite de perda diária atingido"
        
        # Verificar losses consecutivos
        if self.state.consecutive_losses >= self.risk_config.get("max_consecutive_losses", 2):
            return False, f"Máximo de {self.state.consecutive_losses} perdas consecutivas atingido"
        
        # Verificar saldo mínimo
        min_trade_size = 10  # USDT mínimo
        if self.state.balance < min_trade_size:
            return False, "Saldo insuficiente"
        
        return True, "OK"
    
    def open_position(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        entry_time: datetime,
        stop_loss: float,
        take_profit: float,
        quality_score: int = None,
        candle_pattern: str = None,
        session: str = None
    ) -> Optional[Trade]:
        """
        Abre uma nova posição.
        
        Returns:
            Trade criado ou None se não foi possível
        """
        can_open, reason = self.can_open_position(symbol)
        if not can_open:
            logger.warning(f"[{symbol}] Posição não aberta: {reason}")
            return None
        
        # Calcular tamanho
        size = self.state.balance * self.risk_config.get("entry_percent", 0.10)
        
        trade = Trade(
            symbol=symbol,
            entry_time=entry_time,
            entry_price=entry_price,
            direction=direction,
            size=size,
            stop_loss=stop_loss,
            take_profit=take_profit,
            quality_score=quality_score,
            candle_pattern=candle_pattern,
            session=session
        )
        
        self.state.open_positions[symbol] = trade
        logger.info(f"[SIM] Posição aberta: {symbol} {direction} @ {entry_price:.4f} | Size: ${size:.2f}")
        
        return trade
    
    def check_position(
        self,
        symbol: str,
        current_high: float,
        current_low: float,
        current_close: float,
        current_time: datetime
    ) -> Optional[Trade]:
        """
        Verifica se uma posição deve ser fechada (TP, SL).
        
        Returns:
            Trade fechado ou None se continua aberto
        """
        if symbol not in self.state.open_positions:
            return None
        
        trade = self.state.open_positions[symbol]
        
        if trade.direction == "LONG":
            # Verificar Stop Loss
            if current_low <= trade.stop_loss:
                return self.close_position(symbol, trade.stop_loss, current_time, "SL")
            
            # Verificar Take Profit
            if current_high >= trade.take_profit:
                return self.close_position(symbol, trade.take_profit, current_time, "TP")
        
        else:  # SHORT
            # Verificar Stop Loss
            if current_high >= trade.stop_loss:
                return self.close_position(symbol, trade.stop_loss, current_time, "SL")
            
            # Verificar Take Profit
            if current_low <= trade.take_profit:
                return self.close_position(symbol, trade.take_profit, current_time, "TP")
        
        return None
    
    def close_position(
        self,
        symbol: str,
        exit_price: float,
        exit_time: datetime,
        reason: str
    ) -> Optional[Trade]:
        """
        Fecha uma posição.
        
        Returns:
            Trade fechado
        """
        if symbol not in self.state.open_positions:
            return None
        
        trade = self.state.open_positions.pop(symbol)
        
        trade.exit_time = exit_time
        trade.exit_price = exit_price
        trade.exit_reason = reason
        
        # Calcular PnL
        if trade.direction == "LONG":
            price_change_pct = (exit_price - trade.entry_price) / trade.entry_price
        else:  # SHORT
            price_change_pct = (trade.entry_price - exit_price) / trade.entry_price
        
        trade.pnl = trade.size * price_change_pct
        trade.pnl_percent = price_change_pct * 100
        
        # Atualizar estado
        self.state.balance += trade.pnl
        self.state.closed_trades.append(trade)
        self.state.total_trades += 1
        self.daily_pnl += trade.pnl
        
        if trade.pnl > 0:
            self.state.winning_trades += 1
            self.state.consecutive_losses = 0
        else:
            self.state.losing_trades += 1
            self.state.consecutive_losses += 1
            self.state.max_consecutive_losses = max(
                self.state.max_consecutive_losses,
                self.state.consecutive_losses
            )
        
        # Atualizar max/min balance e drawdown
        if self.state.balance > self.state.max_balance:
            self.state.max_balance = self.state.balance
        
        if self.state.balance < self.state.min_balance:
            self.state.min_balance = self.state.balance
        
        current_drawdown = (self.state.max_balance - self.state.balance) / self.state.max_balance
        self.state.max_drawdown = max(self.state.max_drawdown, current_drawdown)
        
        # Verificar limite diário
        daily_loss_pct = abs(self.daily_pnl / self.state.initial_balance)
        if self.daily_pnl < 0 and daily_loss_pct >= self.risk_config.get("daily_loss_limit", 0.20):
            self.daily_loss_limit_hit = True
            logger.warning(f"[SIM] Limite de perda diária atingido: {daily_loss_pct*100:.1f}%")
        
        logger.info(
            f"[SIM] Posição fechada: {symbol} | "
            f"Razão: {reason} | "
            f"PnL: ${trade.pnl:.2f} ({trade.pnl_percent:.2f}%) | "
            f"Saldo: ${self.state.balance:.2f}"
        )
        
        return trade
    
    def reset_daily_stats(self):
        """Reseta estatísticas diárias (chamar no início de cada dia)."""
        self.daily_pnl = 0.0
        self.daily_loss_limit_hit = False
        self.state.consecutive_losses = 0
    
    def get_summary(self) -> Dict:
        """Retorna resumo do estado atual."""
        win_rate = (
            self.state.winning_trades / self.state.total_trades * 100
            if self.state.total_trades > 0 else 0
        )
        
        total_pnl = self.state.balance - self.state.initial_balance
        total_return = total_pnl / self.state.initial_balance * 100
        
        return {
            "initial_balance": self.state.initial_balance,
            "final_balance": self.state.balance,
            "total_pnl": total_pnl,
            "total_return_pct": total_return,
            "total_trades": self.state.total_trades,
            "winning_trades": self.state.winning_trades,
            "losing_trades": self.state.losing_trades,
            "win_rate": win_rate,
            "max_drawdown_pct": self.state.max_drawdown * 100,
            "max_consecutive_losses": self.state.max_consecutive_losses,
            "open_positions": len(self.state.open_positions)
        }
