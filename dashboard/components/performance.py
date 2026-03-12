"""
Aba Performance - Métricas detalhadas de performance do bot.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go


def render(db):
    st.subheader("Performance Detalhada")

    days = st.selectbox("Período de análise", [7, 14, 30, 90], index=2, key="perf_days")
    perf = db.get_performance_summary(since_days=days)

    # --- KPIs principais ---
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total de Trades", perf.get("total_trades", 0))
    wr = perf.get("win_rate", 0)
    c2.metric("Win Rate", f"{wr:.1f}%",
              delta=f"{'acima' if wr >= 55 else 'abaixo'} de 55%",
              delta_color="normal" if wr >= 55 else "inverse")
    pf = perf.get("profit_factor", 0)
    c3.metric("Profit Factor", f"{pf:.2f}",
              delta=f"{'bom' if pf >= 1.5 else 'baixo'}",
              delta_color="normal" if pf >= 1.5 else "inverse")
    pnl = perf.get("total_pnl", 0)
    c4.metric("PnL Total", f"${pnl:+.2f}",
              delta_color="normal" if pnl >= 0 else "inverse")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Ganho Médio",   f"${perf.get('avg_win', 0):.2f}")
    c2.metric("Perda Média",   f"${perf.get('avg_loss', 0):.2f}")
    c3.metric("Max Drawdown",  f"${perf.get('max_drawdown', 0):.2f}")
    c4.metric("Expectância",   f"${perf.get('expectancy', 0):.2f}")

    st.divider()

    trades = db.get_trades(limit=1000, since_days=days, only_closed=True)
    if not trades:
        st.info("Sem dados suficientes para exibir gráficos.")
        return

    df = pd.DataFrame(trades)
    df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce").fillna(0)
    df_sorted = df.sort_values("entry_time").reset_index(drop=True)

    # --- Curva de Equity + Drawdown ---
    df_sorted["equity"] = df_sorted["pnl"].cumsum()
    df_sorted["peak"]   = df_sorted["equity"].cummax()
    df_sorted["dd"]     = df_sorted["equity"] - df_sorted["peak"]

    col1, col2 = st.columns(2)

    with col1:
        colors_pts = ["#00cc88" if v >= 0 else "#ff4444" for v in df_sorted["pnl"]]
        fig_eq = go.Figure()
        fig_eq.add_trace(go.Scatter(
            x=df_sorted.index, y=df_sorted["equity"],
            mode="lines+markers",
            line=dict(color="#00cc88", width=2),
            marker=dict(size=5, color=colors_pts),
            fill="tozeroy", fillcolor="rgba(0,204,136,0.07)",
            name="Equity",
            hovertemplate="Trade #%{x}<br>Equity: $%{y:+.2f}<extra></extra>"
        ))
        fig_eq.update_layout(
            title="Curva de Equity",
            template="plotly_dark", height=300,
            margin=dict(l=40, r=20, t=40, b=30),
            yaxis=dict(tickprefix="$", gridcolor="#1e2030"),
            xaxis=dict(gridcolor="#1e2030"),
            paper_bgcolor="#0d0e14", plot_bgcolor="#0d0e14",
        )
        st.plotly_chart(fig_eq, use_container_width=True)

    with col2:
        fig_dd = go.Figure(go.Scatter(
            x=df_sorted.index, y=df_sorted["dd"],
            mode="lines", fill="tozeroy",
            line=dict(color="#ff4444", width=1.5),
            fillcolor="rgba(255,68,68,0.1)",
            name="Drawdown",
            hovertemplate="Trade #%{x}<br>Drawdown: $%{y:.2f}<extra></extra>"
        ))
        fig_dd.update_layout(
            title="Drawdown por Trade",
            template="plotly_dark", height=300,
            margin=dict(l=40, r=20, t=40, b=30),
            yaxis=dict(tickprefix="$", gridcolor="#1e2030"),
            xaxis=dict(gridcolor="#1e2030"),
            paper_bgcolor="#0d0e14", plot_bgcolor="#0d0e14",
        )
        st.plotly_chart(fig_dd, use_container_width=True)

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        # Donut ganhos x perdas
        wins_n   = len(df[df["pnl"] > 0])
        losses_n = len(df[df["pnl"] <= 0])
        fig_pie = go.Figure(go.Pie(
            labels=["Ganhos", "Perdas"],
            values=[wins_n, losses_n],
            marker_colors=["#00cc88", "#ff4444"],
            hole=0.55,
            textinfo="percent+value",
            hovertemplate="%{label}: %{value} trades (%{percent})<extra></extra>"
        ))
        fig_pie.update_layout(
            title="Ganhos x Perdas",
            template="plotly_dark", height=280,
            margin=dict(l=20, r=20, t=40, b=20),
            paper_bgcolor="#0d0e14",
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    with col2:
        # Histograma PnL
        fig_hist = go.Figure(go.Histogram(
            x=df["pnl"], nbinsx=30,
            marker_color="#4488ff", opacity=0.85,
            hovertemplate="PnL: $%{x:.2f}<br>Trades: %{y}<extra></extra>"
        ))
        fig_hist.add_vline(x=0, line_dash="dash", line_color="#ff4444", opacity=0.7)
        fig_hist.update_layout(
            title="Distribuição de PnL",
            template="plotly_dark", height=280,
            margin=dict(l=40, r=20, t=40, b=30),
            xaxis=dict(tickprefix="$", gridcolor="#1e2030"),
            yaxis=dict(title="Trades", gridcolor="#1e2030"),
            paper_bgcolor="#0d0e14", plot_bgcolor="#0d0e14",
        )
        st.plotly_chart(fig_hist, use_container_width=True)

    st.divider()

    # PnL por símbolo
    if "symbol" in df.columns:
        sym_pnl = df.groupby("symbol")["pnl"].sum().sort_values()
        colors  = ["#ff4444" if v < 0 else "#00cc88" for v in sym_pnl.values]
        fig_bar = go.Figure(go.Bar(
            x=sym_pnl.values, y=sym_pnl.index,
            orientation="h",
            marker_color=colors,
            text=[f"${v:+.2f}" for v in sym_pnl.values],
            textposition="outside",
            hovertemplate="%{y}: $%{x:+.2f}<extra></extra>"
        ))
        fig_bar.update_layout(
            title="PnL Acumulado por Símbolo",
            template="plotly_dark", height=max(300, len(sym_pnl) * 22),
            margin=dict(l=100, r=80, t=40, b=30),
            xaxis=dict(tickprefix="$", gridcolor="#1e2030"),
            yaxis=dict(gridcolor="#1e2030"),
            paper_bgcolor="#0d0e14", plot_bgcolor="#0d0e14",
        )
        st.plotly_chart(fig_bar, use_container_width=True)
