"""
scripts/cleanup_dryrun.py
Remove todos os registros de dry_run do banco (trades, llm_usage, cycle_snapshots).
Roda UMA VEZ antes do deploy limpo.

Uso:
    python scripts/cleanup_dryrun.py           # preview (não apaga nada)
    python scripts/cleanup_dryrun.py --confirm  # apaga de verdade
"""
import sys
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from config.config_loader import load_config
from database.manager import DatabaseManager
from sqlalchemy import text


def cleanup(db: DatabaseManager, confirm: bool):
    tag = "" if confirm else "[PREVIEW] "

    with db._session() as sess:

        # --- 1. Trades dry_run ---
        dry_trades = sess.execute(
            text("SELECT COUNT(*) FROM trades WHERE mode = 'dry_run'")
        ).scalar()
        print(f"{tag}trades dry_run: {dry_trades} registros")

        # --- 2. Trades BYBIT_SYNC sem PnL real (importações lixo) ---
        sync_zero = sess.execute(
            text("SELECT COUNT(*) FROM trades WHERE exit_reason = 'BYBIT_SYNC' AND (pnl IS NULL OR pnl = 0)")
        ).scalar()
        print(f"{tag}trades BYBIT_SYNC com pnl=0/null: {sync_zero} registros")

        # --- 3. cycle_snapshots (histórico de snapshots de dry_run) ---
        # Apaga snapshots antigos de quando não havia trades live
        snapshots = sess.execute(
            text("SELECT COUNT(*) FROM cycle_snapshots")
        ).scalar()
        print(f"{tag}cycle_snapshots total: {snapshots} registros")

        # --- 4. llm_usage com provider='mock' ---
        mock_llm = sess.execute(
            text("SELECT COUNT(*) FROM llm_usage WHERE provider = 'mock'")
        ).scalar()
        print(f"{tag}llm_usage mock: {mock_llm} registros")

        if not confirm:
            print("\nNenhum dado apagado. Rode com --confirm para apagar.")
            return

        # --- Executar remoções ---
        r1 = sess.execute(text("DELETE FROM trades WHERE mode = 'dry_run'"))
        print(f"  ✓ {r1.rowcount} trades dry_run removidos")

        r2 = sess.execute(
            text("DELETE FROM trades WHERE exit_reason = 'BYBIT_SYNC' AND (pnl IS NULL OR pnl = 0)")
        )
        print(f"  ✓ {r2.rowcount} trades BYBIT_SYNC inválidos removidos")

        r3 = sess.execute(text("DELETE FROM cycle_snapshots"))
        print(f"  ✓ {r3.rowcount} cycle_snapshots removidos")

        r4 = sess.execute(text("DELETE FROM llm_usage WHERE provider = 'mock'"))
        print(f"  ✓ {r4.rowcount} llm_usage mock removidos")

        sess.commit()
        print("\nLimpeza concluída.")


def main():
    confirm = "--confirm" in sys.argv

    load_config()  # carrega .env → DATABASE_URL no ambiente
    db_url = os.environ.get("DATABASE_URL", "").strip('"').strip("'") or None
    db = DatabaseManager(database_url=db_url)

    print("=" * 50)
    print(f"Banco: {'PostgreSQL (Supabase)' if os.environ.get('DATABASE_URL') else 'SQLite local'}")
    print("=" * 50)

    cleanup(db, confirm)


if __name__ == "__main__":
    main()
