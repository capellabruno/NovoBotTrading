"""
database/startup.py
Rotinas executadas UMA VEZ na inicialização do sistema:
  1. verify_tables()      — verifica se todas as tabelas existem no banco
  2. sync_trades_from_bybit() — importa histórico de trades fechados da Bybit
"""
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import inspect, text

from .models import Base

if TYPE_CHECKING:
    from .manager import DatabaseManager
    from execution.bybit_client import BybitClient

logger = logging.getLogger(__name__)

# Tabelas obrigatórias (nome da tabela no banco)
REQUIRED_TABLES = [t.name for t in Base.metadata.sorted_tables]


# ---------------------------------------------------------------------------
# 1. Verificação de tabelas
# ---------------------------------------------------------------------------

def verify_tables(db: "DatabaseManager") -> bool:
    """
    Verifica se todas as tabelas obrigatórias existem no banco.
    Se alguma estiver faltando, cria automaticamente via SQLAlchemy.
    Retorna True se tudo estiver OK (mesmo após criação automática).
    """
    logger.info("=" * 55)
    logger.info("[DB] Verificando integridade das tabelas...")

    try:
        inspector = inspect(db._engine)
        existing = set(inspector.get_table_names())
        required = set(REQUIRED_TABLES)

        missing = required - existing
        ok = required & existing

        for tbl in sorted(ok):
            logger.info(f"[DB]   ✓ {tbl}")

        if missing:
            logger.warning(f"[DB] Tabelas ausentes: {sorted(missing)}. Criando...")
            db.ensure_tables()

            # Confirmar criação
            inspector2 = inspect(db._engine)
            still_missing = set(REQUIRED_TABLES) - set(inspector2.get_table_names())
            if still_missing:
                logger.error(f"[DB] FALHA ao criar tabelas: {sorted(still_missing)}")
                return False

            for tbl in sorted(missing):
                logger.info(f"[DB]   + {tbl} criada com sucesso")
        else:
            logger.info("[DB] Todas as tabelas presentes.")

        logger.info("=" * 55)
        return True

    except Exception as e:
        logger.error(f"[DB] Erro ao verificar tabelas: {e}")
        return False


# ---------------------------------------------------------------------------
# 2. Sincronização de trades históricos da Bybit
# ---------------------------------------------------------------------------

def sync_trades_from_bybit(db: "DatabaseManager", bybit: "BybitClient",
                            days_back: int = 90) -> int:
    """
    Importa trades fechados da Bybit que ainda não estão no banco.
    Evita duplicatas verificando o order_id antes de inserir.
    Retorna o número de trades importados.
    """
    logger.info("=" * 55)
    logger.info(f"[DB] Sincronizando histórico de trades da Bybit (últimos {days_back} dias)...")

    if bybit.dry_run:
        logger.info("[DB] Modo DRY RUN — sincronização ignorada.")
        logger.info("=" * 55)
        return 0

    try:
        # Calcular start_time em ms
        from datetime import timedelta
        start_dt = datetime.utcnow() - timedelta(days=days_back)
        start_ms = int(start_dt.timestamp() * 1000)

        # Buscar todos os trades fechados na Bybit (paginado)
        all_bybit_trades = _fetch_all_closed_pnl(bybit, start_ms)
        logger.info(f"[DB] {len(all_bybit_trades)} trades fechados encontrados na Bybit.")

        if not all_bybit_trades:
            logger.info("[DB] Nenhum trade a importar.")
            logger.info("=" * 55)
            return 0

        # Buscar order_ids já registrados no banco para evitar duplicatas
        existing_order_ids = _get_existing_order_ids(db)
        logger.info(f"[DB] {len(existing_order_ids)} trades já registrados no banco.")

        imported = 0
        skipped = 0

        for trade in all_bybit_trades:
            order_id = trade.get("orderId") or trade.get("orderLinkId")

            if order_id and order_id in existing_order_ids:
                skipped += 1
                continue

            symbol = trade.get("symbol", "")
            side = trade.get("side", "")  # "Buy" / "Sell"
            direction = "LONG" if side == "Buy" else "SHORT"

            avg_entry = _safe_float(trade.get("avgEntryPrice") or trade.get("entryPrice"))
            avg_exit = _safe_float(trade.get("avgExitPrice") or trade.get("exitPrice"))
            closed_pnl = _safe_float(trade.get("closedPnl"))
            qty = _safe_float(trade.get("qty") or trade.get("closedSize"))
            size_usdt = avg_entry * qty if avg_entry and qty else 0.0

            # Timestamps
            created_ms = trade.get("createdTime") or trade.get("openedTime")
            updated_ms = trade.get("updatedTime") or trade.get("closedTime")
            entry_time = _ms_to_dt(created_ms)
            exit_time = _ms_to_dt(updated_ms)

            # Salvar entrada
            trade_id = db.save_trade_entry(
                symbol=symbol,
                direction=direction,
                entry_price=avg_entry or 0.0,
                size_usdt=size_usdt,
                quantity=qty,
                stop_loss=None,
                take_profit=None,
                quality_score=None,
                quality_grade=None,
                candle_pattern=None,
                session=None,
                mcp_confidence=None,
                order_id=order_id,
                mode="live",
            )

            # Sobrescrever entry_time com o valor real da Bybit
            if entry_time:
                _patch_entry_time(db, trade_id, entry_time)

            # Registrar saída
            if avg_exit and avg_exit > 0:
                db.close_trade(
                    trade_id=trade_id,
                    exit_price=avg_exit,
                    pnl=closed_pnl,
                    exit_reason="BYBIT_SYNC",
                )
                # Sobrescrever exit_time com o valor real
                if exit_time:
                    _patch_exit_time(db, trade_id, exit_time)

            imported += 1
            logger.debug(f"[DB]   Importado: {symbol} {direction} PnL={closed_pnl:.4f}")

        logger.info(f"[DB] Sincronização concluída: {imported} importados | {skipped} já existiam.")
        logger.info("=" * 55)
        return imported

    except Exception as e:
        logger.error(f"[DB] Erro na sincronização de trades: {e}")
        logger.info("=" * 55)
        return 0


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _fetch_all_closed_pnl(bybit: "BybitClient", start_ms: int) -> list:
    """Busca todo o histórico paginando até esgotar os resultados."""
    all_trades = []
    cursor = None
    page = 0

    while True:
        page += 1
        try:
            params = {
                "category": "linear",
                "limit": 100,
                "startTime": start_ms,
            }
            if cursor:
                params["cursor"] = cursor

            response = bybit.client.get_closed_pnl(**params)

            if response.get("retCode") != 0:
                logger.warning(f"[DB] Bybit retornou erro na página {page}: {response.get('retMsg')}")
                break

            result = response.get("result", {})
            batch = result.get("list", [])
            all_trades.extend(batch)

            cursor = result.get("nextPageCursor")
            if not cursor or not batch:
                break

        except Exception as e:
            logger.error(f"[DB] Erro ao paginar closed PnL (pág {page}): {e}")
            break

    return all_trades


def _get_existing_order_ids(db: "DatabaseManager") -> set:
    """Retorna conjunto de order_ids já registrados no banco."""
    try:
        with db._session() as sess:
            from .models import Trade
            rows = sess.query(Trade.order_id).filter(Trade.order_id.isnot(None)).all()
            return {r[0] for r in rows}
    except Exception as e:
        logger.warning(f"[DB] Não foi possível buscar order_ids existentes: {e}")
        return set()


def _safe_float(value) -> float:
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _ms_to_dt(ms) -> datetime | None:
    try:
        return datetime.utcfromtimestamp(int(ms) / 1000) if ms else None
    except Exception:
        return None


def _patch_entry_time(db: "DatabaseManager", trade_id: int, entry_time: datetime):
    """Corrige entry_time e created_at no banco após inserção."""
    try:
        with db._lock:
            with db._session() as sess:
                sess.execute(
                    text("UPDATE trades SET entry_time = :et, created_at = :et WHERE id = :id"),
                    {"et": entry_time, "id": trade_id}
                )
                sess.commit()
    except Exception as e:
        logger.warning(f"[DB] Falha ao corrigir entry_time do trade {trade_id}: {e}")


def _patch_exit_time(db: "DatabaseManager", trade_id: int, exit_time: datetime):
    """Corrige exit_time no banco após inserção."""
    try:
        with db._lock:
            with db._session() as sess:
                sess.execute(
                    text("UPDATE trades SET exit_time = :et WHERE id = :id"),
                    {"et": exit_time, "id": trade_id}
                )
                sess.commit()
    except Exception as e:
        logger.warning(f"[DB] Falha ao corrigir exit_time do trade {trade_id}: {e}")
