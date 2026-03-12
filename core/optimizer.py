"""
Módulo de Otimização Adaptativa.
Executa backtests periódicos para determinar a melhor configuração por símbolo.
"""
import logging
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import time

from backtest.engine import BacktestEngine
from backtest.data_loader import DataLoader
from backtest.metrics import BacktestMetrics
from execution.bybit_client import BybitClient

logger = logging.getLogger(__name__)

class AdaptiveOptimizer:
    """
    Otimizador que roda backtests em dados recentes para selecionar
    o melhor timeframe e estratégia para cada símbolo.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.adaptive_conf = config.get("adaptive", {})
        
        # Estado atual das otimizações
        # {symbol: {"timeframe": "15m", "score": 85.0, "last_update": datetime}}
        self.active_configs: Dict[str, Dict] = {}
        
        # Componentes
        self.bybit = BybitClient(config)
        self.data_loader = DataLoader(self.bybit)
        
        # Cache local para evitar baixar dados toda hora
        # O data_loader já tem cache, mas aqui controlamos a frequência
        self.last_run_time: Optional[datetime] = None
        
    def get_best_timeframe(self, symbol: str) -> Optional[str]:
        """
        Retorna o melhor timeframe para o símbolo.
        Retorna None se o símbolo deve ser PAUSADO (performance ruim).
        """
        if not self.adaptive_conf.get("enabled", False):
            # Fallback para config estática
            tf = self.config.get("system", {}).get("timeframe", "15m")
            return str(tf).replace("m", "")
            
        config = self.active_configs.get(symbol)
        
        if not config:
            logger.warning(f"[{symbol}] Sem otimização disponível, usando padrão.")
            tf = self.config.get("system", {}).get("timeframe", "15m")
            return str(tf).replace("m", "")
            
        # Verificar validade (TTL)
        hours_since_update = (datetime.now() - config['last_update']).total_seconds() / 3600
        update_interval = self.adaptive_conf.get("update_interval_hours", 6)
        
        if hours_since_update > update_interval * 2:
            logger.warning(f"[{symbol}] Otimização expirada ({hours_since_update:.1f}h).")
            # Poderia disparar re-otimização aqui, mas ideal é o scheduler fazer
        
        if not config.get("is_active", True):
            return None  # Símbolo pausado
            
        return config.get("timeframe")

    def optimize_all(self, symbols: List[str]):
        """
        Executa o processo de otimização para todos os símbolos.
        Deve ser chamado pelo Scheduler.
        """
        logger.info(f"🔄 Iniciando Otimização Adaptativa para {len(symbols)} símbolos...")
        start_time = time.time()
        
        lookback_days = self.adaptive_conf.get("lookback_days", 10)
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        
        timeframes = self.adaptive_conf.get("candidate_timeframes", [5, 15, 30, 60])
        
        results_summary = []
        
        # Configurar backtest temporário
        bt_config = self.config.copy()
        bt_config["backtest"]["use_mcp"] = False # Velocidade
        bt_config["quality"]["min_score"] = 70   # Padrão
        
        for symbol in symbols:
            best_tf = None
            best_score = -9999
            best_metrics = None
            
            logger.info(f"📊 Otimizando {symbol}...")
            
            # Para cada timeframe
            for tf in timeframes:
                try:
                    # Carregar dados (usa cache do DataLoader)
                    df = self.data_loader.load_historical_data(
                        symbol=symbol,
                        start_date=start_date,
                        end_date=end_date,
                        interval=tf,
                        use_cache=True 
                    )
                    
                    if df.empty or len(df) < 50:
                        continue
                        
                    # Rodar Backtest
                    engine = BacktestEngine(bt_config)
                    metrics = engine.run(symbol, df)
                    
                    # Calcular Score
                    score = self._calculate_score(metrics)
                    
                    if score > best_score:
                        best_score = score
                        best_tf = tf
                        best_metrics = metrics
                        
                except Exception as e:
                    logger.error(f"Erro ao otimizar {symbol} em {tf}m: {e}")
            
            # Analisar vencedor
            if best_tf and best_metrics:
                decision = self._decide_status(best_metrics)
                
                self.active_configs[symbol] = {
                    "timeframe": str(best_tf),
                    "score": best_score,
                    "metrics": {
                        "win_rate": best_metrics.win_rate,
                        "profit_factor": best_metrics.profit_factor,
                        "total_return": best_metrics.total_return_pct
                    },
                    "is_active": decision["active"],
                    "reason": decision["reason"],
                    "last_update": datetime.now()
                }
                
                status_icon = "✅" if decision["active"] else "⏸️"
                results_summary.append(
                    f"{status_icon} {symbol}: TF={best_tf}m | WR={best_metrics.win_rate}% | PF={best_metrics.profit_factor:.2f}"
                )
            else:
                logger.warning(f"[{symbol}] Falha na otimização (sem dados suficiente?)")
                self.active_configs[symbol] = {
                    "timeframe": "15", # Fallback seguro
                    "is_active": False,
                    "reason": "Sem dados/Falha",
                    "last_update": datetime.now()
                }
        
        duration = time.time() - start_time
        logger.info(f"✅ Otimização Concluída em {duration:.1f}s")
        for line in results_summary:
            logger.info(line)
            
        self.last_run_time = datetime.now()

    def _calculate_score(self, metrics: BacktestMetrics) -> float:
        """
        Calcula pontuação da estratégia.
        Score = (WinRate * 1) + (ProfitFactor * 15) - (MaxDD * 4) + (Return * 2)
        """
        # Se não houve trades, penalidade máxima
        if metrics.total_trades == 0:
            return -100.0
            
        score = (metrics.win_rate * 1.0)
        score += (metrics.profit_factor * 15.0)
        score -= (metrics.max_drawdown_pct * 4.0)
        score += (metrics.total_return_pct * 2.0)
        
        # Penalizar poucos trades (ex: < 3 em 10 dias não é estatisticamente válido)
        if metrics.total_trades < 3:
            score -= 20.0
            
        return score

    def _decide_status(self, metrics: BacktestMetrics) -> Dict:
        """Decide se o ativo deve ser operado ou pausado."""
        min_wr = self.adaptive_conf.get("min_win_rate", 50.0)
        min_pf = self.adaptive_conf.get("min_profit_factor", 1.1)
        
        reasons = []
        approved = True
        
        if metrics.win_rate < min_wr:
            approved = False
            reasons.append(f"WR {metrics.win_rate}% < {min_wr}%")
            
        if metrics.profit_factor < min_pf:
            approved = False
            reasons.append(f"PF {metrics.profit_factor:.2f} < {min_pf}")
            
        if metrics.total_return_pct <= 0:
            approved = False
            reasons.append(f"Retorno Negativo ({metrics.total_return_pct}%)")
            
        return {
            "active": approved,
            "reason": ", ".join(reasons) if reasons else "Aprovado"
        }
