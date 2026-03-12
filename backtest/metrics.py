"""
Módulo de Backtest - Calculador de Métricas.
Calcula métricas de performance: Win Rate, Sharpe, Drawdown, etc.
"""
from typing import List, Dict
from dataclasses import dataclass
import numpy as np
from .simulator import Trade

@dataclass
class BacktestMetrics:
    """Métricas completas do backtest."""
    # Retorno
    total_return_pct: float
    total_pnl: float
    
    # Trades
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    
    # Risco
    max_drawdown_pct: float
    sharpe_ratio: float
    profit_factor: float
    expectancy: float
    
    # Médias
    avg_win: float
    avg_loss: float
    avg_trade: float
    largest_win: float
    largest_loss: float
    
    # Consecutivos
    max_consecutive_wins: int
    max_consecutive_losses: int
    
    # Por período
    avg_trades_per_day: float
    
    # Por qualidade
    win_rate_by_grade: Dict[str, float]
    
    # Por sessão
    win_rate_by_session: Dict[str, float]


class MetricsCalculator:
    """
    Calcula métricas de performance do backtest.
    """
    
    @staticmethod
    def calculate(
        trades: List[Trade],
        initial_balance: float,
        final_balance: float,
        trading_days: int = 1
    ) -> BacktestMetrics:
        """
        Calcula todas as métricas.
        
        Args:
            trades: Lista de trades fechados
            initial_balance: Saldo inicial
            final_balance: Saldo final
            trading_days: Número de dias de trading
            
        Returns:
            BacktestMetrics com todas as métricas calculadas
        """
        if not trades:
            return MetricsCalculator._empty_metrics()
        
        # Separar ganhos e perdas
        pnls = [t.pnl for t in trades]
        wins = [t.pnl for t in trades if t.pnl > 0]
        losses = [t.pnl for t in trades if t.pnl < 0]
        
        # Básico
        total_pnl = final_balance - initial_balance
        total_return_pct = (total_pnl / initial_balance) * 100
        total_trades = len(trades)
        winning_trades = len(wins)
        losing_trades = len(losses)
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        # Médias
        avg_win = np.mean(wins) if wins else 0
        avg_loss = np.mean(losses) if losses else 0
        avg_trade = np.mean(pnls) if pnls else 0
        largest_win = max(wins) if wins else 0
        largest_loss = min(losses) if losses else 0
        
        # Profit Factor
        gross_profit = sum(wins) if wins else 0
        gross_loss = abs(sum(losses)) if losses else 1
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        # Expectancy (esperança matemática por trade)
        if total_trades > 0:
            expectancy = (
                (win_rate / 100 * avg_win) + 
                ((1 - win_rate / 100) * avg_loss)
            )
        else:
            expectancy = 0
        
        # Sharpe Ratio (simplificado - sem risk-free rate)
        if len(pnls) > 1:
            returns_std = np.std(pnls)
            sharpe_ratio = (avg_trade / returns_std * np.sqrt(252)) if returns_std > 0 else 0
        else:
            sharpe_ratio = 0
        
        # Max Drawdown
        max_drawdown_pct = MetricsCalculator._calculate_max_drawdown(trades, initial_balance)
        
        # Consecutivos
        max_consecutive_wins, max_consecutive_losses = MetricsCalculator._calculate_consecutive(trades)
        
        # Trades por dia
        avg_trades_per_day = total_trades / trading_days if trading_days > 0 else 0
        
        # Win Rate por Nota de Qualidade
        win_rate_by_grade = MetricsCalculator._win_rate_by_attribute(
            trades, lambda t: t.quality_score
        )
        
        # Win Rate por Sessão
        win_rate_by_session = MetricsCalculator._win_rate_by_attribute(
            trades, lambda t: t.session
        )
        
        return BacktestMetrics(
            total_return_pct=round(total_return_pct, 2),
            total_pnl=round(total_pnl, 2),
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=round(win_rate, 2),
            max_drawdown_pct=round(max_drawdown_pct, 2),
            sharpe_ratio=round(sharpe_ratio, 2),
            profit_factor=round(profit_factor, 2),
            expectancy=round(expectancy, 2),
            avg_win=round(avg_win, 2),
            avg_loss=round(avg_loss, 2),
            avg_trade=round(avg_trade, 2),
            largest_win=round(largest_win, 2),
            largest_loss=round(largest_loss, 2),
            max_consecutive_wins=max_consecutive_wins,
            max_consecutive_losses=max_consecutive_losses,
            avg_trades_per_day=round(avg_trades_per_day, 2),
            win_rate_by_grade=win_rate_by_grade,
            win_rate_by_session=win_rate_by_session
        )
    
    @staticmethod
    def _calculate_max_drawdown(trades: List[Trade], initial_balance: float) -> float:
        """Calcula o drawdown máximo em %."""
        if not trades:
            return 0.0
        
        balance = initial_balance
        peak = initial_balance
        max_dd = 0.0
        
        for trade in trades:
            balance += trade.pnl
            if balance > peak:
                peak = balance
            
            drawdown = (peak - balance) / peak if peak > 0 else 0
            max_dd = max(max_dd, drawdown)
        
        return max_dd * 100
    
    @staticmethod
    def _calculate_consecutive(trades: List[Trade]) -> tuple:
        """Calcula sequências consecutivas de ganhos e perdas."""
        max_wins = current_wins = 0
        max_losses = current_losses = 0
        
        for trade in trades:
            if trade.pnl > 0:
                current_wins += 1
                current_losses = 0
                max_wins = max(max_wins, current_wins)
            else:
                current_losses += 1
                current_wins = 0
                max_losses = max(max_losses, current_losses)
        
        return max_wins, max_losses
    
    @staticmethod
    def _win_rate_by_attribute(trades: List[Trade], attr_getter) -> Dict[str, float]:
        """Calcula win rate agrupado por atributo."""
        groups = {}
        
        for trade in trades:
            key = attr_getter(trade)
            if key is None:
                key = "N/A"
            elif isinstance(key, int):
                # Para quality_score, agrupar em faixas
                if key >= 90:
                    key = "A (90+)"
                elif key >= 80:
                    key = "B (80-89)"
                elif key >= 70:
                    key = "C (70-79)"
                else:
                    key = "D/F (<70)"
            
            if key not in groups:
                groups[key] = {"wins": 0, "total": 0}
            
            groups[key]["total"] += 1
            if trade.pnl > 0:
                groups[key]["wins"] += 1
        
        return {
            k: round(v["wins"] / v["total"] * 100, 1) if v["total"] > 0 else 0
            for k, v in groups.items()
        }
    
    @staticmethod
    def _empty_metrics() -> BacktestMetrics:
        """Retorna métricas zeradas."""
        return BacktestMetrics(
            total_return_pct=0,
            total_pnl=0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0,
            max_drawdown_pct=0,
            sharpe_ratio=0,
            profit_factor=0,
            expectancy=0,
            avg_win=0,
            avg_loss=0,
            avg_trade=0,
            largest_win=0,
            largest_loss=0,
            max_consecutive_wins=0,
            max_consecutive_losses=0,
            avg_trades_per_day=0,
            win_rate_by_grade={},
            win_rate_by_session={}
        )
