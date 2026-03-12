"""
Aba Performance - Métricas detalhadas de performance do bot.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go


def render(db):
    st.subheader("Performance")

    # --- Seletor de período ---
    days = st.selectbox("Período de análise", [7, 14, 30, 90], index=2, key="perf_days")
    perf = db.get_performance_summary(since_days=days)

    # --- Métricas principais ---
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total de Trades", perf.get("total_trades", 0))
    with col2:
        wr = perf.get("win_rate", 0)
        st.metric("Win Rate", f"{wr:.1f}%", delta="Meta: 55%")
    with col3:
        pnl = perf.get("total_pnl", 0)
        st.metric("PnL Total", f"${pnl:+.2f}")
    with col4:
        pf = perf.get("profit_factor", 0)
        st.metric("Profit Factor", f"{pf:.2f}")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Ganho Médio", f"${perf.get('avg_win', 0):.2f}")
    with col2:
        st.metric("Perda Média", f"${perf.get('avg_loss', 0):.2f}")
    with col3:
        st.metric("Drawdown Máximo", f"${perf.get('max_drawdown', 0):.2f}")
    with col4:
        st.metric("Expectância", f"${perf.get('expectancy', 0):.2f}")

    st.divider()

    # --- Curva de Equity ---
    st.subheader("Curva de Equity")
    balance_hist = db.get_balance_history(days=days)

    if balance_hist:
        df_bal = pd.DataFrame(balance_hist)
        df_bal["timestamp"] = pd.to_datetime(df_bal["timestamp"])

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_bal["timestamp"],
            y=df_bal["balance"],
            mode="lines",
            name="Saldo",
            line=dict(color="#00cc88", width=2),
            fill="tozeroy",
            fillcolor="rgba(0,204,136,0.1)"
        ))
        fig.update_layout(
            title="Evolução do Saldo",
            xaxis_title="Data/Hora",
            yaxis_title="Saldo (USDT)",
            template="plotly_dark",
            height=300,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Dados de saldo ainda não disponíveis. Aguarde alguns ciclos do bot.")

    st.divider()

    # --- Distribuição de resultados ---
    st.subheader("Distribuição de Trades")
    trades = db.get_trades(limit=1000, since_days=days, only_closed=True)
    if trades:
        df_t = pd.DataFrame(trades)
        df_t["pnl"] = pd.to_numeric(df_t["pnl"], errors="coerce").fillna(0)

        wins = len(df_t[df_t["pnl"] > 0])
        losses = len(df_t[df_t["pnl"] <= 0])

        fig_pie = go.Figure(go.Pie(
            labels=["Ganhos", "Perdas"],
            values=[wins, losses],
            marker_colors=["#00cc88", "#ff4444"],
            hole=0.5,
        ))
        fig_pie.update_layout(template="plotly_dark", height=300, showlegend=True)

        col1, col2 = st.columns(2)
        with col1:
            st.plotly_chart(fig_pie, use_container_width=True)

        with col2:
            # PnL por símbolo
            if "symbol" in df_t.columns:
                sym_pnl = df_t.groupby("symbol")["pnl"].sum().sort_values()
                colors = ["#00cc88" if v >= 0 else "#ff4444" for v in sym_pnl.values]
                fig_bar = go.Figure(go.Bar(
                    x=sym_pnl.values,
                    y=sym_pnl.index,
                    orientation="h",
                    marker_color=colors,
                ))
                fig_bar.update_layout(
                    title="PnL por Símbolo",
                    template="plotly_dark",
                    height=300,
                )
                st.plotly_chart(fig_bar, use_container_width=True)
    else:
        st.info("Sem dados suficientes para exibir distribuição.")
