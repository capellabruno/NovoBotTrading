"""
Módulo de Backtest.
Contém ferramentas para testar estratégias em dados históricos.
"""
from .engine import BacktestEngine
from .simulator import TradeSimulator, Trade
from .data_loader import DataLoader
from .metrics import MetricsCalculator, BacktestMetrics
from .report import ReportGenerator

__all__ = [
    'BacktestEngine',
    'TradeSimulator',
    'Trade',
    'DataLoader',
    'MetricsCalculator',
    'BacktestMetrics',
    'ReportGenerator'
]
