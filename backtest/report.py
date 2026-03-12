"""
Módulo de Backtest - Gerador de Relatórios.
Gera relatórios em texto e HTML.
"""
from typing import List
from datetime import datetime
import logging

from .simulator import Trade
from .metrics import BacktestMetrics

logger = logging.getLogger(__name__)


class ReportGenerator:
    """
    Gera relatórios de backtest em diferentes formatos.
    """
    
    @staticmethod
    def generate_text_report(
        symbol: str,
        metrics: BacktestMetrics,
        trades: List[Trade] = None
    ) -> str:
        """
        Gera relatório em texto.
        
        Args:
            symbol: Símbolo testado
            metrics: Métricas do backtest
            trades: Lista de trades (opcional para detalhes)
            
        Returns:
            Relatório formatado como string
        """
        report = []
        report.append("=" * 60)
        report.append(f"  RELATÓRIO DE BACKTEST - {symbol}")
        report.append(f"  Gerado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("=" * 60)
        report.append("")
        
        # Resumo de Performance
        report.append("📊 RESUMO DE PERFORMANCE")
        report.append("-" * 40)
        report.append(f"  Retorno Total:       {metrics.total_return_pct:+.2f}%")
        report.append(f"  PnL Total:           ${metrics.total_pnl:+.2f}")
        report.append(f"  Win Rate:            {metrics.win_rate:.1f}%")
        report.append(f"  Profit Factor:       {metrics.profit_factor:.2f}")
        report.append(f"  Expectancy:          ${metrics.expectancy:.2f}/trade")
        report.append("")
        
        # Estatísticas de Trades
        report.append("📈 ESTATÍSTICAS DE TRADES")
        report.append("-" * 40)
        report.append(f"  Total de Trades:     {metrics.total_trades}")
        report.append(f"  Trades Vencedores:   {metrics.winning_trades}")
        report.append(f"  Trades Perdedores:   {metrics.losing_trades}")
        report.append(f"  Trades/Dia (média):  {metrics.avg_trades_per_day:.1f}")
        report.append("")
        
        # Médias
        report.append("💰 MÉDIAS POR TRADE")
        report.append("-" * 40)
        report.append(f"  Ganho Médio:         ${metrics.avg_win:.2f}")
        report.append(f"  Perda Média:         ${metrics.avg_loss:.2f}")
        report.append(f"  Resultado Médio:     ${metrics.avg_trade:.2f}")
        report.append(f"  Maior Ganho:         ${metrics.largest_win:.2f}")
        report.append(f"  Maior Perda:         ${metrics.largest_loss:.2f}")
        report.append("")
        
        # Risco
        report.append("⚠️ MÉTRICAS DE RISCO")
        report.append("-" * 40)
        report.append(f"  Max Drawdown:        {metrics.max_drawdown_pct:.2f}%")
        report.append(f"  Sharpe Ratio:        {metrics.sharpe_ratio:.2f}")
        report.append(f"  Max Perdas Consec.:  {metrics.max_consecutive_losses}")
        report.append(f"  Max Ganhos Consec.:  {metrics.max_consecutive_wins}")
        report.append("")
        
        # Win Rate por Qualidade
        if metrics.win_rate_by_grade:
            report.append("🎯 WIN RATE POR NOTA DE QUALIDADE")
            report.append("-" * 40)
            for grade, rate in sorted(metrics.win_rate_by_grade.items()):
                report.append(f"  {grade}: {rate:.1f}%")
            report.append("")
        
        # Win Rate por Sessão
        if metrics.win_rate_by_session:
            report.append("🕐 WIN RATE POR SESSÃO")
            report.append("-" * 40)
            for session, rate in sorted(metrics.win_rate_by_session.items()):
                report.append(f"  {session}: {rate:.1f}%")
            report.append("")
        
        report.append("=" * 60)
        
        return "\n".join(report)
    
    @staticmethod
    def generate_trade_log(trades: List[Trade]) -> str:
        """
        Gera log detalhado de trades.
        
        Args:
            trades: Lista de trades
            
        Returns:
            Log formatado
        """
        if not trades:
            return "Nenhum trade executado."
        
        lines = []
        lines.append("HISTÓRICO DE TRADES")
        lines.append("-" * 100)
        lines.append(
            f"{'#':<4} {'Entrada':<20} {'Saída':<20} {'Dir':<6} "
            f"{'Entry':<12} {'Exit':<12} {'PnL':<10} {'%':<8} {'Razão':<10} {'Score':<6}"
        )
        lines.append("-" * 100)
        
        for i, trade in enumerate(trades, 1):
            entry_time = trade.entry_time.strftime("%Y-%m-%d %H:%M") if trade.entry_time else "N/A"
            exit_time = trade.exit_time.strftime("%Y-%m-%d %H:%M") if trade.exit_time else "N/A"
            
            lines.append(
                f"{i:<4} {entry_time:<20} {exit_time:<20} {trade.direction:<6} "
                f"{trade.entry_price:<12.4f} {trade.exit_price or 0:<12.4f} "
                f"${trade.pnl:>+8.2f} {trade.pnl_percent:>+6.2f}% "
                f"{trade.exit_reason:<10} {trade.quality_score or 'N/A':<6}"
            )
        
        lines.append("-" * 100)
        
        return "\n".join(lines)
    
    @staticmethod
    def save_report(content: str, filepath: str):
        """Salva relatório em arquivo."""
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        logger.info(f"Relatório salvo em: {filepath}")
    
    @staticmethod
    def print_summary(metrics: BacktestMetrics):
        """Imprime resumo rápido no console."""
        emoji = "✅" if metrics.total_return_pct > 0 else "❌"
        
        print(f"\n{emoji} RESULTADO DO BACKTEST:")
        print(f"   Retorno: {metrics.total_return_pct:+.2f}% | PnL: ${metrics.total_pnl:+.2f}")
        print(f"   Trades: {metrics.total_trades} | Win Rate: {metrics.win_rate:.1f}%")
        print(f"   Profit Factor: {metrics.profit_factor:.2f} | Max DD: {metrics.max_drawdown_pct:.1f}%")
        print()
