from pydantic import BaseModel, Field
from typing import Optional, List

class MarketDataInput(BaseModel):
    symbol: str
    timeframe: str
    close_price: float
    ema_20: float
    ema_50: float
    rsi: float
    volume_ratio: float  # Volume / VolumeMA
    trend: str # "UP", "DOWN", "SIDEWAYS"
    signal_type: Optional[str] = None # "CALL" or "PUT" sent by the deterministic strategy
    
    # Suporte e Resistência
    support_level: Optional[float] = None      # Nível de suporte mais próximo
    resistance_level: Optional[float] = None   # Nível de resistência mais próximo
    distance_to_support_pct: Optional[float] = None   # % distância ao suporte
    distance_to_resistance_pct: Optional[float] = None # % distância à resistência
    price_position: Optional[str] = None       # "NEAR_SUPPORT", "NEAR_RESISTANCE", "MIDDLE"
    
    # Padrões de Candles
    candle_pattern: Optional[str] = None       # Nome do padrão detectado
    candle_pattern_type: Optional[str] = None  # "BULLISH", "BEARISH", "NEUTRAL"
    
    # Sessão de Mercado
    current_session: Optional[str] = None      # "ASIAN", "LONDON", "NEW_YORK", "OVERLAP"
    session_score: Optional[float] = None      # Score da sessão (0.0 a 1.0)
    
    # ATR (Volatilidade)
    atr: Optional[float] = None                # Average True Range absoluto
    atr_percent: Optional[float] = None        # ATR como % do preço
    
    # Score de Qualidade
    quality_score: Optional[int] = None        # Pontuação total (0-100)
    quality_grade: Optional[str] = None        # Nota: "A", "B", "C", "D", "F"
    
    # Contexto de Entrada 3m
    entry_context_3m: Optional[str] = None     # Análise do timeframe de 3m para entrada



class ValidationResult(BaseModel):
    approved: bool
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str
    suggested_action: str # "EXECUTE", "WAIT", "ABORT"
