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
    col1, col2, col3 = st.columns(3)
    with col1:
        symbol_filter = st.selectbox("Símbolo", ["Todos", "ETHUSDT", "SOLUSDT", "XRPUSDT",
                                                  "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT",
                                                  "MATICUSDT", "1000PEPEUSDT", "WIFUSDT",
                                                  "NOTUSDT", "LINKUSDT"])
    with col2:
        direction_filter = st.selectbox("Direção", ["Todos", "LONG", "SHORT"])
    with col3:
        days_filter = st.selectbox("Período", [7, 14, 30, 90, 365], index=2)

    only_closed = st.checkbox("Apenas trades fechados", value=True)

    # --- Carregar dados ---
    sym = None if symbol_filter == "Todos" else symbol_filter
    trades = db.get_trades(limit=500, symbol=sym, since_days=days_filter, only_closed=only_closed)

    if not trades:
        st.info("Nenhum trade encontrado com os filtros selecionados.")
        return

    df = pd.DataFrame(trades)

    # Filtro de direção
    if direction_filter != "Todos":
        df = df[df["direction"] == direction_filter]

    # Formatar colunas
    display_cols = {
        "symbol": "Símbolo",
        "direction": "Direção",
        "entry_time": "Entrada",
        "exit_time": "Saída",
        "entry_price": "Preço Entrada",
        "exit_price": "Preço Saída",
        "size_usdt": "Tamanho (USDT)",
        "pnl": "PnL (USDT)",
        "pnl_percent": "PnL (%)",
        "quality_score": "Score",
        "quality_grade": "Nota",
        "session": "Sessão",
        "exit_reason": "Motivo Saída",
        "mode": "Modo",
    }

    df_display = df[[c for c in display_cols.keys() if c in df.columns]].copy()
    df_display = df_display.rename(columns={k: v for k, v in display_cols.items() if k in df_display.columns})

    # Colorir PnL
    if "PnL (USDT)" in df_display.columns:
        df_display["PnL (USDT)"] = df_display["PnL (USDT)"].apply(
            lambda x: f"${x:+.2f}" if x is not None else "Em aberto"
        )

    if "Tamanho (USDT)" in df_display.columns:
        df_display["Tamanho (USDT)"] = df_display["Tamanho (USDT)"].apply(
            lambda x: f"${x:.2f}" if x is not None else "-"
        )

    st.metric("Total de trades", len(df_display))
    st.dataframe(df_display, use_container_width=True, hide_index=True)

    # --- Exportar ---
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Exportar CSV",
        data=csv,
        file_name="trades_export.csv",
        mime="text/csv",
    )
