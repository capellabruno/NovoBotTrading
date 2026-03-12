"""
Aba Histórico de Trades - Tabela de todas as operações com filtros e export.
"""
import streamlit as st
import pandas as pd
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


def render(db):
    st.subheader("Histórico de Trades")

    # --- Filtros ---
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        known_symbols = ["Todos"] + db.get_symbols()
        symbol_filter = st.selectbox("Símbolo", known_symbols, key="th_symbol")
    with col2:
        direction_filter = st.selectbox("Direção", ["Todos", "LONG", "SHORT"], key="th_dir")
    with col3:
        days_filter = st.selectbox("Período", [7, 14, 30, 90, 365], index=2, key="th_days")
    with col4:
        mode_filter = st.selectbox("Modo", ["Todos", "live", "dry_run"], key="th_mode")

    only_closed = st.checkbox("Apenas trades fechados", value=True, key="th_closed")

    # --- Carregar dados ---
    sym = None if symbol_filter == "Todos" else symbol_filter
    trades = db.get_trades(limit=500, symbol=sym, since_days=days_filter, only_closed=only_closed)

    if not trades:
        st.info("Nenhum trade encontrado com os filtros selecionados.")
        return

    df = pd.DataFrame(trades)

    if direction_filter != "Todos":
        df = df[df["direction"] == direction_filter]
    if mode_filter != "Todos":
        df = df[df["mode"] == mode_filter]

    if df.empty:
        st.info("Nenhum trade com os filtros selecionados.")
        return

    # --- Métricas do filtro ---
    closed_df  = df[df["exit_time"].notna()] if "exit_time" in df.columns else df
    total_pnl  = closed_df["pnl"].sum() if "pnl" in closed_df.columns else 0
    wins       = len(closed_df[closed_df["pnl"] > 0]) if "pnl" in closed_df.columns else 0
    total_c    = len(closed_df)
    wr         = (wins / total_c * 100) if total_c > 0 else 0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total no filtro", len(df))
    m2.metric("Fechados", total_c)
    m3.metric("Win Rate", f"{wr:.1f}%")
    m4.metric("PnL no período", f"${total_pnl:+.2f}")

    st.divider()

    # --- Tabela formatada ---
    rows = []
    for _, t in df.iterrows():
        pnl = t.get("pnl")
        pnl_str = f"${pnl:+.2f}" if pnl is not None else "—"
        rows.append({
            "Símbolo":        t.get("symbol", ""),
            "Direção":        "🟢 LONG" if t.get("direction") == "LONG" else "🔴 SHORT",
            "Entrada":        str(t.get("entry_time", ""))[:16],
            "Saída":          str(t.get("exit_time", ""))[:16] if t.get("exit_time") else "—",
            "Preço Entrada":  f"{t.get('entry_price', 0):.4f}",
            "Preço Saída":    f"{t.get('exit_price', 0):.4f}" if t.get("exit_price") else "—",
            "Tamanho ($)":    f"${t.get('size_usdt', 0):.2f}",
            "PnL":            pnl_str,
            "Score":          t.get("quality_score") or "—",
            "Motivo Saída":   t.get("exit_reason") or "—",
            "Modo":           t.get("mode") or "—",
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # --- Exportar ---
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="⬇ Exportar CSV",
        data=csv,
        file_name="trades_export.csv",
        mime="text/csv",
    )
