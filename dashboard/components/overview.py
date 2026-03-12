"""
Aba Overview - Visão geral do sistema em tempo real.
"""
import streamlit as st
from datetime import datetime


def render(state: dict, db_perf: dict, engine_online: bool):
    # --- Status do Engine ---
    if not engine_online or not state:
        st.error("Engine offline - State API não está respondendo")
    else:
        mode = "DRY RUN" if state.get("dry_run") else "LIVE"
        status = state.get("cycle_status", "IDLE")
        paused = state.get("is_paused", False)

        col1, col2, col3 = st.columns(3)
        with col1:
            color = "🟡" if paused else ("🟢" if status == "IDLE" else "🔵")
            st.metric("Status", f"{color} {'PAUSADO' if paused else status}")
        with col2:
            st.metric("Modo", mode)
        with col3:
            cycle = state.get("cycle_number", 0)
            st.metric("Ciclo", f"#{cycle}")

    st.divider()

    # --- Métricas de Conta ---
    balance = state.get("account_balance", 0.0) if state else 0.0
    open_pos = state.get("open_positions", {}) if state else {}
    wins = db_perf.get("wins", 0)
    losses = db_perf.get("losses", 0)
    total_pnl = db_perf.get("total_pnl", 0.0)
    win_rate = db_perf.get("win_rate", 0.0)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Saldo (USDT)", f"${balance:,.2f}")
    with col2:
        st.metric("Posições Abertas", len(open_pos))
    with col3:
        wr_delta = f"{win_rate:.1f}%"
        st.metric("Win Rate (30d)", wr_delta)
    with col4:
        delta_color = "normal"
        pnl_str = f"${total_pnl:+.2f}"
        st.metric("PnL Total (30d)", pnl_str)

    st.divider()

    # --- Posições Abertas ---
    st.subheader("Posições Abertas")
    if open_pos:
        rows = []
        last_prices = state.get("last_prices", {})
        total = 0
        for sym, pos in open_pos.items():
            entry = float(pos.get("avgPrice") or pos.get("entryPrice") or 0)
            current = last_prices.get(sym, entry)
            side = pos.get("side", "Buy")
            size = float(pos.get("size", 0))
            unreal_pnl = float(pos.get("unrealisedPnl", 0))
            total += unreal_pnl
            rows.append({
                "Símbolo": sym,
                "Direção": "LONG" if side == "Buy" else "SHORT",
                "Preço Entrada": f"${entry:.4f}",
                "Preço Atual": f"${current:.4f}",
                "Tamanho": size,
                "PnL Não Real.": f"${unreal_pnl:+.2f}",
            })
        rows.append({
            "Símbolo": "TOTAL",
            "Direção": "",
            "Preço Entrada": "",
            "Preço Atual": "",
            "Tamanho": "",
            "PnL Não Real.": f"${total:+.2f}",
        })
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhuma posição aberta no momento.")

    st.divider()

    # --- Grid de Símbolos ---
    st.subheader("Status dos Símbolos")
    last_signals = state.get("last_signals", {}) if state else {}

    if not last_signals:
        st.info("Aguardando primeiro ciclo de análise...")
    else:
        # Filtros
        col_f1, col_f2, col_f3 = st.columns([2, 2, 1])
        with col_f1:
            filter_text = st.text_input("Buscar símbolo", "", placeholder="ex: BTC, ETH...")
        with col_f2:
            filter_signal = st.selectbox("Filtrar por sinal", ["Todos", "Com Sinal", "CALL", "PUT", "Bloqueados"])
        with col_f3:
            page_size = st.selectbox("Por página", [20, 50, 100], index=0)

        # Ordenar: aprovados primeiro, bloqueados depois, sem sinal por último
        def _sort_key(item):
            sig = item[1]
            if sig.get("mcp_approved"):
                return 0
            if sig.get("signal") and sig.get("blocked"):
                return 1
            if sig.get("signal"):
                return 2
            return 3

        items = sorted(last_signals.items(), key=_sort_key)

        # Aplicar filtros
        if filter_text:
            items = [(s, d) for s, d in items if filter_text.upper() in s]
        if filter_signal == "Com Sinal":
            items = [(s, d) for s, d in items if d.get("signal")]
        elif filter_signal == "CALL":
            items = [(s, d) for s, d in items if d.get("signal") == "CALL"]
        elif filter_signal == "PUT":
            items = [(s, d) for s, d in items if d.get("signal") == "PUT"]
        elif filter_signal == "Bloqueados":
            items = [(s, d) for s, d in items if d.get("signal") and d.get("blocked")]

        total_syms = len(items)
        n_pages = max(1, (total_syms + page_size - 1) // page_size)
        if n_pages > 1:
            page = st.number_input("Página", min_value=1, max_value=n_pages, value=1, step=1) - 1
        else:
            page = 0
        items_page = items[page * page_size : (page + 1) * page_size]

        st.caption(f"Exibindo {len(items_page)} de {total_syms} símbolos | Página {page+1}/{n_pages}")

        cols = st.columns(4)
        for i, (sym, sig) in enumerate(items_page):
            signal = sig.get("signal")
            blocked = sig.get("blocked")
            mcp_ok = sig.get("mcp_approved")
            score = sig.get("quality_score") or 0

            if signal and mcp_ok:
                icon = "🟢" if signal == "CALL" else "🔴"
                label = f"{icon} {sym}\n{signal} ({score:.0f}pts)"
            elif signal and blocked:
                label = f"🟡 {sym}\n{signal} BLOQ"
            elif signal:
                label = f"🟠 {sym}\n{signal}"
            else:
                label = f"⚪ {sym}\nSEM SINAL"

            with cols[i % 4]:
                st.text(label)

    # --- Tempos ---
    if state:
        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            last = state.get("last_cycle_time", "N/A")
            if last and last != "N/A":
                try:
                    dt = datetime.fromisoformat(last)
                    last = dt.strftime("%H:%M:%S")
                except Exception:
                    pass
            st.caption(f"Último ciclo: {last}")
        with col2:
            nxt = state.get("next_cycle_time", "N/A")
            if nxt and nxt != "N/A":
                try:
                    dt = datetime.fromisoformat(nxt)
                    nxt = dt.strftime("%H:%M:%S")
                except Exception:
                    pass
            st.caption(f"Próximo ciclo: {nxt}")
