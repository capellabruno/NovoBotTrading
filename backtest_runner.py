"""
Script de Execução do Backtest com Suporte a Múltiplos Timeframes.
Executa backtest usando configurações do settings.yaml e gera relatório comparativo.
"""
import sys
import yaml
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

# Adicionar diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent))

from backtest import BacktestEngine, DataLoader, ReportGenerator, BacktestMetrics
from execution.bybit_client import BybitClient

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('backtest.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def load_config(config_path: str = "config/settings.yaml") -> dict:
    """Carrega configuração do arquivo YAML."""
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def timeframe_to_str(minutes: int) -> str:
    """Converte minutos para string legível."""
    if minutes < 60:
        return f"M{minutes}"
    elif minutes < 1440:
        return f"H{minutes // 60}"
    else:
        return f"D{minutes // 1440}"


def generate_comparison_report(
    results: Dict[int, Dict[str, BacktestMetrics]],
    symbols: List[str]
) -> str:
    """
    Gera relatório comparativo entre timeframes.
    
    Args:
        results: Dict[timeframe][symbol] = BacktestMetrics
        symbols: Lista de símbolos testados
        
    Returns:
        Relatório formatado
    """
    report = []
    report.append("\n" + "=" * 80)
    report.append("  📊 RELATÓRIO COMPARATIVO DE TIMEFRAMES")
    report.append(f"  Gerado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("=" * 80)
    
    # Tabela de resumo por timeframe
    report.append("\n📈 RESUMO POR TIMEFRAME")
    report.append("-" * 80)
    report.append(f"{'Timeframe':<12} {'Return %':>10} {'Win Rate':>10} {'Trades':>8} {'Profit F':>10} {'Max DD':>10} {'Sharpe':>8}")
    report.append("-" * 80)
    
    timeframe_totals = {}
    
    for tf_minutes, symbol_results in sorted(results.items()):
        tf_str = timeframe_to_str(tf_minutes)
        
        # Agregar resultados de todos os símbolos
        total_return = 0
        total_trades = 0
        total_wins = 0
        max_dd = 0
        profit_factors = []
        sharpe_ratios = []
        
        for symbol, metrics in symbol_results.items():
            total_return += metrics.total_return_pct
            total_trades += metrics.total_trades
            total_wins += metrics.winning_trades
            max_dd = max(max_dd, metrics.max_drawdown_pct)
            if metrics.profit_factor > 0:
                profit_factors.append(metrics.profit_factor)
            if metrics.sharpe_ratio != 0:
                sharpe_ratios.append(metrics.sharpe_ratio)
        
        avg_return = total_return / len(symbol_results) if symbol_results else 0
        win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
        avg_pf = sum(profit_factors) / len(profit_factors) if profit_factors else 0
        avg_sharpe = sum(sharpe_ratios) / len(sharpe_ratios) if sharpe_ratios else 0
        
        timeframe_totals[tf_minutes] = {
            'avg_return': avg_return,
            'win_rate': win_rate,
            'total_trades': total_trades,
            'profit_factor': avg_pf,
            'max_drawdown': max_dd,
            'sharpe': avg_sharpe
        }
        
        emoji = "🟢" if avg_return > 0 else "🔴"
        report.append(
            f"{emoji} {tf_str:<10} {avg_return:>+9.2f}% {win_rate:>9.1f}% "
            f"{total_trades:>8} {avg_pf:>10.2f} {max_dd:>9.1f}% {avg_sharpe:>8.2f}"
        )
    
    report.append("-" * 80)
    
    # Determinar melhor timeframe
    best_tf = max(timeframe_totals.items(), key=lambda x: x[1]['avg_return'])
    best_tf_str = timeframe_to_str(best_tf[0])
    
    report.append(f"\n🏆 MELHOR TIMEFRAME: {best_tf_str}")
    report.append(f"   Retorno Médio: {best_tf[1]['avg_return']:+.2f}%")
    report.append(f"   Win Rate: {best_tf[1]['win_rate']:.1f}%")
    report.append(f"   Profit Factor: {best_tf[1]['profit_factor']:.2f}")
    
    # Tabela detalhada por símbolo
    report.append("\n\n📋 DETALHES POR SÍMBOLO E TIMEFRAME")
    report.append("-" * 80)
    
    for symbol in symbols:
        report.append(f"\n  {symbol}:")
        report.append(f"  {'Timeframe':<10} {'Return':>10} {'Trades':>8} {'Win Rate':>10} {'Avg Trade':>12}")
        
        for tf_minutes in sorted(results.keys()):
            tf_str = timeframe_to_str(tf_minutes)
            if symbol in results[tf_minutes]:
                m = results[tf_minutes][symbol]
                emoji = "✅" if m.total_return_pct > 0 else "❌"
                report.append(
                    f"  {emoji} {tf_str:<8} {m.total_return_pct:>+9.2f}% "
                    f"{m.total_trades:>8} {m.win_rate:>9.1f}% ${m.avg_trade:>+10.2f}"
                )
    
    report.append("\n" + "=" * 80)
    
    # Recomendação
    report.append("\n💡 RECOMENDAÇÃO:")
    
    if best_tf[1]['win_rate'] >= 55 and best_tf[1]['profit_factor'] >= 1.3:
        report.append(f"   ✅ Use {best_tf_str} - Bons resultados em Win Rate e Profit Factor")
    elif best_tf[1]['avg_return'] > 0:
        report.append(f"   ⚠️ {best_tf_str} teve melhor retorno, mas considere ajustar parâmetros")
    else:
        report.append(f"   ❌ Nenhum timeframe teve resultados positivos. Revise a estratégia.")
    
    report.append("\n" + "=" * 80 + "\n")
    
    return "\n".join(report)


def run_backtest():
    """Executa o backtest com suporte a múltiplos timeframes."""
    print("\n" + "=" * 60)
    print("  🧪 BACKTEST MULTI-TIMEFRAME - NovoBotTrading")
    print("=" * 60 + "\n")
    
    # 1. Carregar configuração
    config = load_config()
    backtest_config = config.get("backtest", {})
    
    if not backtest_config.get("enabled", False):
        print("❌ Backtest não está habilitado no settings.yaml")
        print("   Configure backtest.enabled = true")
        return
    
    symbols = backtest_config.get("symbols", ["BTCUSDT"])
    timeframes = backtest_config.get("timeframes", [15])  # Default M15
    start_date = backtest_config.get("start_date", "2025-01-01")
    end_date = backtest_config.get("end_date", "2025-01-20")
    initial_balance = backtest_config.get("initial_balance", 1000.0)
    compare_timeframes = backtest_config.get("compare_timeframes", True)
    
    print(f"📅 Período: {start_date} a {end_date}")
    print(f"💰 Saldo Inicial: ${initial_balance:.2f}")
    print(f"📊 Símbolos: {', '.join(symbols)}")
    print(f"⏱️ Timeframes: {', '.join([timeframe_to_str(tf) for tf in timeframes])}")
    print(f"🎯 Score Mínimo: {config.get('quality', {}).get('min_score', 70)}")
    print()
    
    # 2. Inicializar componentes
    bybit_client = BybitClient(config)
    data_loader = DataLoader(bybit_client)
    
    # Estrutura para armazenar resultados
    # results[timeframe][symbol] = BacktestMetrics
    all_results: Dict[int, Dict[str, BacktestMetrics]] = {}
    
    # 3. Executar backtest para cada timeframe e símbolo
    for tf_minutes in timeframes:
        tf_str = timeframe_to_str(tf_minutes)
        all_results[tf_minutes] = {}
        
        print(f"\n{'=' * 60}")
        print(f"  ⏱️ TIMEFRAME: {tf_str} ({tf_minutes} minutos)")
        print('=' * 60)
        
        for symbol in symbols:
            print(f"\n  📈 {symbol} ({tf_str})...")
            
            try:
                # 3.1 Carregar dados históricos
                df = data_loader.load_historical_data(
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    interval=tf_minutes
                )
                
                if df.empty:
                    print(f"  ⚠️ Nenhum dado encontrado para {symbol}")
                    continue
                
                print(f"  ✅ {len(df)} candles carregados")
                
                # 3.2 Executar backtest
                config["backtest"]["use_mcp"] = backtest_config.get("use_mcp", False)
                
                engine = BacktestEngine(config)
                metrics = engine.run(symbol, df)
                
                all_results[tf_minutes][symbol] = metrics
                
                # 3.3 Mostrar resultado rápido
                emoji = "🟢" if metrics.total_return_pct > 0 else "🔴"
                print(f"  {emoji} Resultado: {metrics.total_return_pct:+.2f}% | "
                      f"WR: {metrics.win_rate:.1f}% | Trades: {metrics.total_trades}")
                
                # 3.4 Salvar relatório individual
                report_dir = Path("backtest_reports")
                report_dir.mkdir(exist_ok=True)
                
                report = ReportGenerator.generate_text_report(symbol, metrics, engine.get_trades())
                report_path = report_dir / f"backtest_{symbol}_{tf_str}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                ReportGenerator.save_report(report, str(report_path))
                
            except Exception as e:
                logger.error(f"Erro no backtest de {symbol} ({tf_str}): {e}", exc_info=True)
                print(f"  ❌ Erro: {e}")
    
    # 4. Gerar relatório comparativo
    if compare_timeframes and len(timeframes) > 1:
        print("\n\n" + "=" * 60)
        print("  📊 GERANDO RELATÓRIO COMPARATIVO...")
        print("=" * 60)
        
        comparison_report = generate_comparison_report(all_results, symbols)
        print(comparison_report)
        
        # Salvar relatório comparativo
        report_dir = Path("backtest_reports")
        comparison_path = report_dir / f"comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        ReportGenerator.save_report(comparison_report, str(comparison_path))
        print(f"📁 Relatório comparativo salvo em: {comparison_path}")
    
    # 5. Resumo final
    print("\n" + "=" * 60)
    print("  ✅ BACKTEST CONCLUÍDO!")
    print("=" * 60)
    print(f"📁 Relatórios salvos em: backtest_reports/")
    print()


if __name__ == "__main__":
    run_backtest()
