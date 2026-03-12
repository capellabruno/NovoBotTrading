"""
Aba Posições - Detalhes das posições abertas com opção de fechar.
"""
import streamlit as st
import requests


def render(state: dict, engine_online: bool):
    open_pos = state.get("open_positions", {}) if state else {}
    last_prices = state.get("last_prices", {}) if state else {}

    if not open_pos:
        st.info("Nenhuma posição aberta no momento.")
        return

    st.subheader(f"Posições Abertas ({len(open_pos)})")

    for sym, pos in open_pos.items():
        entry = float(pos.get("avgPrice") or pos.get("entryPrice") or 0)
        current = last_prices.get(sym, entry)
        side = pos.get("side", "Buy")
        size = float(pos.get("size", 0))
        unreal_pnl = float(pos.get("unrealisedPnl", 0))
        sl = pos.get("stopLoss", "N/A")
        tp = pos.get("takeProfit", "N/A")
        direction = "LONG" if side == "Buy" else "SHORT"

        pnl_color = "green" if unreal_pnl >= 0 else "red"
        pnl_sign = "+" if unreal_pnl >= 0 else ""

        with st.expander(f"{'🟢' if direction == 'LONG' else '🔴'} {sym} | {direction} | PnL: {pnl_sign}${unreal_pnl:.2f}", expanded=True):
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Preço Entrada", f"${entry:.4f}")
            with col2:
                delta_pct = ((current - entry) / entry * 100) if entry > 0 else 0
                st.metric("Preço Atual", f"${current:.4f}", delta=f"{delta_pct:+.2f}%")
            with col3:
                st.metric("Tamanho", f"{size} tokens")
            with col4:
                st.metric("PnL Não Real.", f"{pnl_sign}${unreal_pnl:.2f}")

            col1, col2 = st.columns(2)
            with col1:
                st.caption(f"Stop Loss: {sl}")
            with col2:
                st.caption(f"Take Profit: {tp}")

            if engine_online:
                if st.button(f"Fechar {sym}", key=f"close_{sym}", type="secondary"):
                    st.warning(f"Funcionalidade de fechamento manual envia sinal ao engine. Confirme na próxima execução.")
