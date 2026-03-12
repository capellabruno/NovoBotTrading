"""
Script para reconciliar trades fechados na Bybit com o banco de dados local.
Busca todos os PnLs fechados e atualiza os registros abertos no DB.

Uso: python scripts/reconcile_trades.py
"""
import sys
import time
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from config.config_loader import load_config
from execution.bybit_client import BybitClient
from database.manager import DatabaseManager


def fetch_all_closed_pnl(bybit: BybitClient) -> list:
    """Busca todas as páginas de PnL fechado disponíveis na Bybit."""
    all_pnl = []
    cursor = None

    for page in range(20):  # até 1000 registros (20 páginas x 50)
        params = {"category": "linear", "limit": 50}
        if cursor:
            params["cursor"] = cursor

        resp = bybit.client.get_closed_pnl(**params)
        if resp.get("retCode") != 0:
            print(f"Erro na API: {resp}")
            break

        result = resp.get("result", {})
        entries = result.get("list", [])
        all_pnl.extend(entries)
        cursor = result.get("nextPageCursor")

        print(f"  Página {page + 1}: {len(entries)} entradas")
        if not cursor or not entries:
            break
        time.sleep(0.3)

    return all_pnl


def reconcile(db: DatabaseManager, all_pnl: list) -> dict:
    """
    Para cada trade fechado na Bybit, encontra o registro aberto correspondente
    no DB (mesmo símbolo + direção) e registra o PnL real.
    """
    stats = {"reconciled": 0, "no_match": 0, "total_pnl": 0.0, "wins": 0, "losses": 0}
    print("\n" + "=" * 60)
    print("RECONCILIANDO TRADES")
    print("=" * 60)

    for entry in all_pnl:
        sym = entry["symbol"]
        pnl = float(entry.get("closedPnl", 0))
        exit_price = float(entry.get("avgExitPrice", 0))
        entry_price_bybit = float(entry.get("avgEntryPrice", 0))
        side = entry.get("side", "")  # "Buy" = LONG, "Sell" = SHORT
        direction = "LONG" if side == "Buy" else "SHORT"

        # Buscar trades abertos no DB para esse símbolo+direção
        open_trades = db.get_open_trades()
        match = None
        for t in open_trades:
            if t["symbol"] == sym and t["direction"] == direction:
                match = t
                break  # mais recente primeiro

        if match:
            db.close_trade(
                trade_id=match["id"],
                exit_price=exit_price,
                pnl=pnl,
                exit_reason="SL_TP"
            )
            stats["reconciled"] += 1
            stats["total_pnl"] += pnl
            if pnl > 0:
                stats["wins"] += 1
            else:
                stats["losses"] += 1

            sign = "+" if pnl >= 0 else ""
            marker = "WIN " if pnl > 0 else "LOSS"
            print(f"  [{marker}] {sym:15s} {direction:5s} | {entry_price_bybit:.5g} -> {exit_price:.5g} | PnL: {sign}{pnl:.4f} USDT")
        else:
            stats["no_match"] += 1
            print(f"  [SKIP] {sym:15s} {direction:5s} | PnL: {pnl:+.4f} — sem match no DB")

    return stats


def print_summary(stats: dict, remaining_open: int):
    print("\n" + "=" * 60)
    print("RESUMO")
    print("=" * 60)
    print(f"  Trades reconciliados : {stats['reconciled']}")
    print(f"  Sem match no DB      : {stats['no_match']}")
    print(f"  Wins                 : {stats['wins']}")
    print(f"  Losses               : {stats['losses']}")
    wr = (stats["wins"] / stats["reconciled"] * 100) if stats["reconciled"] > 0 else 0
    print(f"  Win Rate             : {wr:.1f}%")
    print(f"  PnL Total            : ${stats['total_pnl']:+.4f} USDT")
    print(f"  Ainda abertos no DB  : {remaining_open}")
    print("=" * 60)


def main():
    print("Conectando à Bybit...")
    config = load_config()
    bybit = BybitClient(config)
    db = DatabaseManager(str(ROOT / "trading.db"))

    open_before = len(db.get_open_trades())
    print(f"Trades abertos no DB antes: {open_before}")
    print("\nBuscando trades fechados na Bybit...")

    all_pnl = fetch_all_closed_pnl(bybit)
    print(f"\nTotal de registros na Bybit: {len(all_pnl)}")

    if not all_pnl:
        print("Nenhum trade fechado encontrado na Bybit.")
        return

    stats = reconcile(db, all_pnl)

    open_after = len(db.get_open_trades())
    print_summary(stats, open_after)

    if stats["reconciled"] > 0:
        print("\nBanco de dados atualizado com sucesso!")
        print("Reinicie o dashboard para ver os dados atualizados.")


if __name__ == "__main__":
    main()
