"""
Gerenciador do banco de dados.
Suporta SQLite (local) e PostgreSQL (Supabase/cloud).
Thread-safe para uso simultâneo pelo engine e pelo dashboard.
"""
import os
import threading
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from sqlalchemy import create_engine, func, desc
from sqlalchemy.orm import sessionmaker, Session

from .models import Base, Trade, SystemEvent, CycleSnapshot

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self, db_path: str = "trading.db", database_url: str = None):
        """
        Args:
            db_path: Caminho SQLite (fallback local).
            database_url: URL PostgreSQL completa. Se não fornecido, tenta
                          a variável de ambiente DATABASE_URL; senão usa SQLite.
        """
        self._lock = threading.Lock()

        url = database_url or os.environ.get("DATABASE_URL")
        if url:
            # Supabase retorna "postgres://..." mas SQLAlchemy requer "postgresql://"
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql://", 1)
            engine = create_engine(
                url,
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=10,
                echo=False,
            )
            logger.info("DatabaseManager inicializado: PostgreSQL (cloud)")
        else:
            engine = create_engine(
                f"sqlite:///{db_path}",
                connect_args={"check_same_thread": False},
                pool_pre_ping=True,
                echo=False,
            )
            logger.info(f"DatabaseManager inicializado: SQLite ({db_path})")

        Base.metadata.create_all(engine)
        self._SessionFactory = sessionmaker(bind=engine)

    def _session(self) -> Session:
        return self._SessionFactory()

    # -------------------------------------------------------------------------
    # Trades
    # -------------------------------------------------------------------------

    def save_trade_entry(self, symbol: str, direction: str, entry_price: float,
                         size_usdt: float, quantity: float = None,
                         stop_loss: float = None, take_profit: float = None,
                         quality_score: float = None, quality_grade: str = None,
                         candle_pattern: str = None, session: str = None,
                         mcp_confidence: float = None, order_id: str = None,
                         mode: str = "live") -> int:
        """Salva entrada de trade. Retorna o ID do registro."""
        with self._lock:
            with self._session() as sess:
                trade = Trade(
                    symbol=symbol,
                    direction=direction,
                    entry_price=entry_price,
                    entry_time=datetime.utcnow(),
                    size_usdt=size_usdt,
                    quantity=quantity,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    quality_score=quality_score,
                    quality_grade=quality_grade,
                    candle_pattern=candle_pattern,
                    session=session,
                    mcp_confidence=mcp_confidence,
                    order_id=order_id,
                    mode=mode,
                )
                sess.add(trade)
                sess.commit()
                return trade.id

    def close_trade(self, trade_id: int, exit_price: float, pnl: float,
                    exit_reason: str = "UNKNOWN"):
        """Registra saída de um trade existente."""
        with self._lock:
            with self._session() as sess:
                trade = sess.get(Trade, trade_id)
                if trade:
                    trade.exit_price = exit_price
                    trade.exit_time = datetime.utcnow()
                    trade.pnl = pnl
                    if trade.size_usdt and trade.size_usdt > 0:
                        trade.pnl_percent = (pnl / trade.size_usdt) * 100
                    trade.exit_reason = exit_reason
                    sess.commit()

    def close_trade_by_symbol(self, symbol: str, exit_price: float,
                               pnl: float, exit_reason: str = "UNKNOWN"):
        """Fecha o trade aberto mais recente de um símbolo."""
        with self._lock:
            with self._session() as sess:
                trade = (
                    sess.query(Trade)
                    .filter(Trade.symbol == symbol, Trade.exit_time.is_(None))
                    .order_by(desc(Trade.entry_time))
                    .first()
                )
                if trade:
                    trade.exit_price = exit_price
                    trade.exit_time = datetime.utcnow()
                    trade.pnl = pnl
                    if trade.size_usdt and trade.size_usdt > 0:
                        trade.pnl_percent = (pnl / trade.size_usdt) * 100
                    trade.exit_reason = exit_reason
                    sess.commit()

    def get_trades(self, limit: int = 200, symbol: str = None,
                   since_days: int = None, only_closed: bool = False) -> List[Dict]:
        with self._session() as sess:
            q = sess.query(Trade)
            if symbol:
                q = q.filter(Trade.symbol == symbol)
            if since_days:
                cutoff = datetime.utcnow() - timedelta(days=since_days)
                q = q.filter(Trade.entry_time >= cutoff)
            if only_closed:
                q = q.filter(Trade.exit_time.isnot(None))
            trades = q.order_by(desc(Trade.entry_time)).limit(limit).all()
            return [self._trade_to_dict(t) for t in trades]

    def get_symbols(self) -> List[str]:
        """Retorna lista de símbolos únicos com trades registrados."""
        with self._session() as sess:
            rows = sess.query(Trade.symbol).distinct().order_by(Trade.symbol).all()
            return [r[0] for r in rows]

    def get_open_trades(self, mode: str = None) -> List[Dict]:
        """Retorna trades sem exit_time. Se mode='live', exclui dry_run."""
        with self._session() as sess:
            q = sess.query(Trade).filter(Trade.exit_time.is_(None))
            if mode:
                q = q.filter(Trade.mode == mode)
            trades = q.order_by(desc(Trade.entry_time)).all()
            return [self._trade_to_dict(t) for t in trades]

    def get_performance_summary(self, since_days: int = 30) -> Dict[str, Any]:
        cutoff = datetime.utcnow() - timedelta(days=since_days)
        with self._session() as sess:
            q = sess.query(Trade).filter(
                Trade.exit_time.isnot(None),
                Trade.entry_time >= cutoff
            )
            trades = q.all()

        total = len(trades)
        if total == 0:
            return {
                "total_trades": 0, "wins": 0, "losses": 0,
                "win_rate": 0.0, "total_pnl": 0.0,
                "avg_win": 0.0, "avg_loss": 0.0,
                "profit_factor": 0.0, "max_drawdown": 0.0,
                "expectancy": 0.0,
            }

        wins = [t for t in trades if (t.pnl or 0) > 0]
        losses = [t for t in trades if (t.pnl or 0) <= 0]
        total_pnl = sum(t.pnl or 0 for t in trades)
        gross_win = sum(t.pnl for t in wins) if wins else 0
        gross_loss = abs(sum(t.pnl for t in losses)) if losses else 0

        # Max drawdown simples
        running = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in sorted(trades, key=lambda x: x.entry_time):
            running += t.pnl or 0
            if running > peak:
                peak = running
            dd = peak - running
            if dd > max_dd:
                max_dd = dd

        return {
            "total_trades": total,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": (len(wins) / total * 100) if total > 0 else 0.0,
            "total_pnl": total_pnl,
            "avg_win": (gross_win / len(wins)) if wins else 0.0,
            "avg_loss": (gross_loss / len(losses)) if losses else 0.0,
            "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else 0.0,
            "max_drawdown": max_dd,
            "expectancy": total_pnl / total if total > 0 else 0.0,
        }

    def get_balance_history(self, days: int = 30) -> List[Dict]:
        cutoff = datetime.utcnow() - timedelta(days=days)
        with self._session() as sess:
            snaps = (
                sess.query(CycleSnapshot)
                .filter(CycleSnapshot.timestamp >= cutoff)
                .order_by(CycleSnapshot.timestamp)
                .all()
            )
            return [{"timestamp": s.timestamp.isoformat(), "balance": s.balance} for s in snaps]

    @staticmethod
    def _trade_to_dict(t: Trade) -> Dict:
        return {
            "id": t.id,
            "symbol": t.symbol,
            "direction": t.direction,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "entry_time": t.entry_time.isoformat() if t.entry_time else None,
            "exit_time": t.exit_time.isoformat() if t.exit_time else None,
            "size_usdt": t.size_usdt,
            "quantity": t.quantity,
            "pnl": t.pnl,
            "pnl_percent": t.pnl_percent,
            "stop_loss": t.stop_loss,
            "take_profit": t.take_profit,
            "exit_reason": t.exit_reason,
            "quality_score": t.quality_score,
            "quality_grade": t.quality_grade,
            "candle_pattern": t.candle_pattern,
            "session": t.session,
            "mcp_confidence": t.mcp_confidence,
            "mode": t.mode,
            "order_id": t.order_id,
        }

    # -------------------------------------------------------------------------
    # System Events
    # -------------------------------------------------------------------------

    def log_event(self, level: str, source: str, message: str):
        with self._lock:
            with self._session() as sess:
                event = SystemEvent(
                    level=level,
                    source=source,
                    message=message[:2000],  # truncar mensagens muito longas
                )
                sess.add(event)
                sess.commit()

    def get_recent_events(self, limit: int = 200, level: str = None) -> List[Dict]:
        with self._session() as sess:
            q = sess.query(SystemEvent)
            if level and level != "ALL":
                q = q.filter(SystemEvent.level == level)
            events = q.order_by(desc(SystemEvent.timestamp)).limit(limit).all()
            return [
                {
                    "timestamp": e.timestamp.isoformat(),
                    "level": e.level,
                    "source": e.source,
                    "message": e.message,
                }
                for e in reversed(events)
            ]

    # -------------------------------------------------------------------------
    # Cycle Snapshots
    # -------------------------------------------------------------------------

    def save_snapshot(self, balance: float, open_positions: int,
                      symbols_analyzed: int, cycle_number: int):
        with self._lock:
            with self._session() as sess:
                snap = CycleSnapshot(
                    balance=balance,
                    open_positions_count=open_positions,
                    symbols_analyzed=symbols_analyzed,
                    cycle_number=cycle_number,
                )
                sess.add(snap)
                sess.commit()
