"""
Modelos SQLAlchemy para persistência de trades, eventos e snapshots.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, Float, String, Boolean,
    DateTime, Text, create_engine
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Trade(Base):
    """Histórico de todas as operações (live e dry-run)."""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    direction = Column(String(10), nullable=False)   # LONG / SHORT
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    entry_time = Column(DateTime, default=datetime.utcnow, index=True)
    exit_time = Column(DateTime, nullable=True)
    size_usdt = Column(Float, nullable=False)         # tamanho em USDT
    quantity = Column(Float, nullable=True)           # quantidade de tokens
    pnl = Column(Float, nullable=True)               # PnL em USDT
    pnl_percent = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    exit_reason = Column(String(50), nullable=True)  # TP/SL/TREND/MANUAL
    quality_score = Column(Float, nullable=True)
    quality_grade = Column(String(2), nullable=True)
    candle_pattern = Column(String(50), nullable=True)
    session = Column(String(20), nullable=True)
    mcp_confidence = Column(Float, nullable=True)
    mode = Column(String(10), default="live")        # live / dry_run
    order_id = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SystemEvent(Base):
    """Log de eventos significativos do sistema."""
    __tablename__ = "system_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    level = Column(String(10), nullable=False)       # INFO/WARNING/ERROR
    source = Column(String(50), nullable=False)
    message = Column(Text, nullable=False)


class CycleSnapshot(Base):
    """Snapshot do estado da conta a cada ciclo."""
    __tablename__ = "cycle_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    balance = Column(Float, nullable=True)
    open_positions_count = Column(Integer, default=0)
    symbols_analyzed = Column(Integer, default=0)
    cycle_number = Column(Integer, default=0)


class KnownSymbol(Base):
    """Lista de símbolos USDT perpétuos ativos na Bybit, cacheada no banco."""
    __tablename__ = "known_symbols"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, unique=True, index=True)
    active = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


class SymbolState(Base):
    """Estado persistente por símbolo: cooldown após loss, cache de candles."""
    __tablename__ = "symbol_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, unique=True, index=True)

    # Cooldown após loss
    cooldown_until = Column(DateTime, nullable=True)   # NULL = sem cooldown
    cooldown_reason = Column(String(100), nullable=True)

    # Cache de candles (JSON serializado)
    candles_4h_json = Column(Text, nullable=True)
    candles_4h_updated_at = Column(DateTime, nullable=True)
    candles_1h_json = Column(Text, nullable=True)
    candles_1h_updated_at = Column(DateTime, nullable=True)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LLMUsage(Base):
    """Registro de uso de tokens por chamada LLM (Gemini / Groq)."""
    __tablename__ = "llm_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    provider = Column(String(20), nullable=False)       # gemini / groq / ollama / mock
    model = Column(String(60), nullable=True)
    symbol = Column(String(20), nullable=True)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    approved = Column(Boolean, nullable=True)
    confidence = Column(Float, nullable=True)
    latency_ms = Column(Integer, nullable=True)         # tempo de resposta em ms
