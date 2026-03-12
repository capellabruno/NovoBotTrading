"""
Módulo de Backtest - Carregador de Dados Históricos.
Busca dados de candles da Bybit para períodos históricos.
Inclui cache local para evitar rate limiting.
"""
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Optional
from pathlib import Path
import logging
import time
import os

logger = logging.getLogger(__name__)

class DataLoader:
    """
    Carrega dados históricos de candles da Bybit API.
    Usa cache local para evitar chamadas repetidas à API.
    """
    
    CACHE_DIR = "data/cache"
    
    def __init__(self, bybit_client):
        """
        Args:
            bybit_client: Instância do BybitClient para fazer requisições
        """
        self.bybit = bybit_client
        self._ensure_cache_dir()
    
    def _ensure_cache_dir(self):
        """Cria diretório de cache se não existir."""
        Path(self.CACHE_DIR).mkdir(parents=True, exist_ok=True)
    
    def _get_cache_path(self, symbol: str, interval: int, start_date: str, end_date: str) -> str:
        """Gera caminho do arquivo de cache."""
        filename = f"{symbol}_{interval}m_{start_date}_{end_date}.csv"
        return os.path.join(self.CACHE_DIR, filename)
    
    def load_historical_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        interval: int = 5,
        use_cache: bool = True
    ) -> pd.DataFrame:
        """
        Carrega dados históricos para um símbolo.
        Usa cache local se disponível para evitar rate limiting.
        
        Args:
            symbol: Par de trading (ex: "BTCUSDT")
            start_date: Data inicial no formato "YYYY-MM-DD"
            end_date: Data final no formato "YYYY-MM-DD"
            interval: Intervalo em minutos (1, 5, 15, 60, etc)
            use_cache: Se True, tenta carregar do cache primeiro
            
        Returns:
            DataFrame com colunas: timestamp, open, high, low, close, volume
        """
        cache_path = self._get_cache_path(symbol, interval, start_date, end_date)
        
        # Tentar carregar do cache primeiro
        if use_cache and os.path.exists(cache_path):
            logger.info(f"Carregando {symbol} do cache: {cache_path}")
            return self.load_from_csv(cache_path)
        
        logger.info(f"Carregando dados históricos para {symbol} ({interval}m) de {start_date} a {end_date}")
        
        # Bybit retorna máximo 1000 candles por request
        # Fazer uma única requisição com limit alto
        try:
            candles = self.bybit.fetch_candles(
                symbol=symbol,
                interval=interval,
                limit=1000  # Máximo permitido pela API
            )
            
            if not candles:
                logger.warning(f"Nenhum dado retornado para {symbol}")
                return pd.DataFrame()
            
            # Converter para DataFrame
            df = self._to_dataframe(candles)
            
            # Filtrar pelo período desejado
            start_ts = datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000
            end_ts = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).timestamp() * 1000
            
            df = df[
                (df['timestamp'] >= start_ts) &
                (df['timestamp'] <= end_ts)
            ]
            
            df = df.sort_values('timestamp').reset_index(drop=True)
            df = df.drop_duplicates(subset=['timestamp'])
            
            logger.info(f"Total de {len(df)} candles carregados para {symbol}")
            
            # Salvar no cache para uso futuro
            if use_cache and len(df) > 0:
                self.save_to_csv(df, cache_path)
                logger.info(f"Dados salvos no cache: {cache_path}")
            
            # Delay para evitar rate limit entre símbolos
            time.sleep(1.0)
            
            return df
            
        except Exception as e:
            logger.error(f"Erro ao carregar candles para {symbol}: {e}")
            return pd.DataFrame()
    
    def _to_dataframe(self, candles: List) -> pd.DataFrame:
        """Converte lista de candles para DataFrame."""
        cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'turnover']
        df = pd.DataFrame(candles, columns=cols)
        
        for col in ['timestamp', 'open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col])
        
        return df
    
    @staticmethod
    def load_from_csv(filepath: str) -> pd.DataFrame:
        """
        Carrega dados de um arquivo CSV.
        
        Args:
            filepath: Caminho para o arquivo CSV
            
        Returns:
            DataFrame com os dados
        """
        logger.info(f"Carregando dados de {filepath}")
        df = pd.read_csv(filepath)
        
        # Garantir tipos corretos
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col])
        
        return df
    
    @staticmethod
    def save_to_csv(df: pd.DataFrame, filepath: str):
        """Salva DataFrame em CSV."""
        df.to_csv(filepath, index=False)
        logger.info(f"Dados salvos em {filepath}")
    
    def clear_cache(self):
        """Limpa o cache de dados."""
        import shutil
        if os.path.exists(self.CACHE_DIR):
            shutil.rmtree(self.CACHE_DIR)
            self._ensure_cache_dir()
            logger.info("Cache limpo com sucesso")
