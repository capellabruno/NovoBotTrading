"""
NovoBotTrading Dashboard - Versão Cloud (Streamlit Community Cloud)
Lê dados diretamente do PostgreSQL (Supabase) — não depende do engine local.

Deploy: https://share.streamlit.io
"""
import sys
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

st.set_page_config(
    page_title="NovoBotTrading",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    /* Base */
    .block-container { padding-top: 1.2rem; padding-bottom: 1rem; }
    .stMetric label { font-size: 0.78rem; color: #8b8fa8; text-transform: uppercase; letter-spacing: 0.05em; }
    .stMetric [data-testid="metric-container"] {
        background: #12131a;
        border: 1px solid #1e2030;
        padding: 14px 16px;
        border-radius: 10px;
    }
    .stMetric [data-testid="stMetricValue"] { font-size: 1.4rem; font-weight: 700; }
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] { gap: 4px; }
    .stTabs [data-baseweb="tab"] {
        background: #12131a;
        border-radius: 8px;
        padding: 6px 18px;
        color: #8b8fa8;
        font-size: 0.85rem;
    }
    .stTabs [aria-selected="true"] {
        background: #1e2030 !important;
        color: #e2e8f0 !important;
        border-bottom: 2px solid #00cc88;
    }
    /* Dataframe */
    .stDataFrame { font-size: 0.82rem; }
    /* Sidebar */
    section[data-testid="stSidebar"] { background: #0d0e14; }
    /* Divider */
    hr { border-color: #1e2030; margin: 0.8rem 0; }
    /* Badge */
    .badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 20px;
        font-size: 0.72rem;
        font-weight: 600;
        letter-spacing: 0.04em;
    }
    .badge-live { background: #0d2b1e; color: #00cc88; border: 1px solid #00cc88; }
    .badge-dry  { background: #2b1e0d; color: #ffaa00; border: 1px solid #ffaa00; }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_db():
    from database.manager import DatabaseManager
    db_url = None
    try:
        db_url = st.secrets["DATABASE_URL"]
    except Exception:
        pass
    return DatabaseManager(database_url=db_url)


def _pnl_color(val):
    """Retorna cor CSS para PnL."""
    return "#00cc88" if (val or 0) >= 0 else "#ff4444"


def _render_overview(db, db_perf):
    wins        = db_perf.get("wins", 0)
    losses      = db_perf.get("losses", 0)
    total_pnl   = db_perf.get("total_pnl", 0.0)
    win_rate    = db_perf.get("win_rate", 0.0)
    total_trades = db_perf.get("total_trades", 0)
    pf          = db_perf.get("profit_factor", 0.0)
    avg_win     = db_perf.get("avg_win", 0.0)
    avg_loss    = db_perf.get("avg_loss", 0.0)
    expectancy  = db_perf.get("expectancy", 0.0)
    drawdown    = db_perf.get("max_drawdown", 0.0)

    # --- KPIs principais ---
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Trades (30d)", total_trades)
    c2.metric("Win Rate", f"{win_rate:.1f}%",
              delta=f"{'acima' if win_rate >= 55 else 'abaixo'} de 55%",
              delta_color="normal" if win_rate >= 55 else "inverse")
    c3.metric("PnL Total", f"${total_pnl:+.2f}", delta_color="normal" if total_pnl >= 0 else "inverse")
    c4.metric("Profit Factor", f"{pf:.2f}",
              delta=f"{'bom' if pf >= 1.5 else 'baixo'}",
              delta_color="normal" if pf >= 1.5 else "inverse")
    c5.metric("Ganho Médio", f"${avg_win:.2f}")
    c6.metric("Expectância", f"${expectancy:.2f}",
              delta_color="normal" if expectancy >= 0 else "inverse")

    st.divider()

    # --- Posições abertas ---
    st.subheader("Posições Abertas")
    open_trades = db.get_open_trades(mode="live")
    if open_trades:
        df = pd.DataFrame(open_trades)

        # Calcular PnL fictício com base no preço atual não disponível aqui,
        # mostramos os dados do banco com formatação melhorada
        rows = []
        for t in open_trades:
            pnl_unrealized = t.get("pnl")
            rows.append({
                "Símbolo":       t.get("symbol", ""),
                "Direção":       ("🟢 LONG" if t.get("direction") == "LONG" else "🔴 SHORT"),
                "Entrada ($)":   f"{t.get('entry_price', 0):.4f}",
                "Stop Loss":     f"{t.get('stop_loss', 0):.4f}" if t.get("stop_loss") else "—",
                "Take Profit":   f"{t.get('take_profit', 0):.4f}" if t.get("take_profit") else "—",
                "Tamanho":       f"${t.get('size_usdt', 0):.2f}",
                "Score":         t.get("quality_score") or "—",
                "Abertura":      t.get("entry_time", "")[:16] if t.get("entry_time") else "—",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("Nenhuma posição aberta no momento.")

    st.divider()

    # --- Curva de saldo ---
    st.subheader("Curva de Saldo (7 dias)")
    balance_hist = db.get_balance_history(days=7)
    if balance_hist:
        df_bal = pd.DataFrame(balance_hist)
        df_bal["timestamp"] = pd.to_datetime(df_bal["timestamp"])

        first_val = df_bal["balance"].iloc[0]
        last_val = df_bal["balance"].iloc[-1]
        pct_change = ((last_val - first_val) / first_val * 100) if first_val else 0
        line_color = "#00cc88" if pct_change >= 0 else "#ff4444"
        fill_color = "rgba(0,204,136,0.08)" if pct_change >= 0 else "rgba(255,68,68,0.08)"

        fig = go.Figure(go.Scatter(
            x=df_bal["timestamp"], y=df_bal["balance"],
            mode="lines", line=dict(color=line_color, width=2.5),
            fill="tozeroy", fillcolor=fill_color,
            hovertemplate="<b>%{x|%d/%m %H:%M}</b><br>$%{y:,.2f}<extra></extra>"
        ))
        fig.update_layout(
            template="plotly_dark",
            height=220,
            margin=dict(l=40, r=20, t=10, b=30),
            yaxis=dict(tickprefix="$", gridcolor="#1e2030"),
            xaxis=dict(gridcolor="#1e2030"),
            paper_bgcolor="#0d0e14",
            plot_bgcolor="#0d0e14",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Sem histórico de saldo ainda.")


def _render_history(db):
    st.subheader("Histórico de Trades")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        days_filter = st.selectbox("Período", [7, 14, 30, 90, 365], index=2, key="hist_days")
    with col2:
        direction_filter = st.selectbox("Direção", ["Todos", "LONG", "SHORT"], key="hist_dir")
    with col3:
        mode_filter = st.selectbox("Modo", ["live", "dry_run", "Todos"], key="hist_mode")
    with col4:
        only_closed = st.checkbox("Apenas fechados", value=True, key="hist_closed")

    trades = db.get_trades(
        limit=500,
        since_days=days_filter,
        only_closed=only_closed,
    )

    if not trades:
        st.info("Nenhum trade encontrado.")
        return

    df = pd.DataFrame(trades)

    if direction_filter != "Todos":
        df = df[df["direction"] == direction_filter]
    if mode_filter != "Todos":
        df = df[df["mode"] == mode_filter]

    if df.empty:
        st.info("Nenhum trade com os filtros selecionados.")
        return

    # Métricas rápidas do filtro
    closed_df = df[df["exit_time"].notna()] if "exit_time" in df.columns else df
    total_pnl  = closed_df["pnl"].sum() if "pnl" in closed_df.columns else 0
    wins       = len(closed_df[closed_df["pnl"] > 0]) if "pnl" in closed_df.columns else 0
    total_c    = len(closed_df)
    wr         = (wins / total_c * 100) if total_c > 0 else 0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Trades no filtro", len(df))
    m2.metric("Fechados", total_c)
    m3.metric("Win Rate", f"{wr:.1f}%")
    m4.metric("PnL no período", f"${total_pnl:+.2f}")

    # Construir tabela de exibição
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
            "Tamanho":        f"${t.get('size_usdt', 0):.2f}",
            "PnL":            pnl_str,
            "Score":          t.get("quality_score") or "—",
            "Motivo":         t.get("exit_reason") or "—",
            "Modo":           t.get("mode") or "—",
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("⬇ Exportar CSV", data=csv,
                       file_name="trades_export.csv", mime="text/csv")


def _render_performance(db):
    st.subheader("Performance Detalhada")

    days = st.selectbox("Período", [7, 14, 30, 90], index=2, key="perf_days")
    perf = db.get_performance_summary(since_days=days)

    # KPIs
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total de Trades", perf.get("total_trades", 0))
    c2.metric("Win Rate",        f"{perf.get('win_rate', 0):.1f}%")
    c3.metric("Profit Factor",   f"{perf.get('profit_factor', 0):.2f}")
    c4.metric("PnL Total",       f"${perf.get('total_pnl', 0):+.2f}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Ganho Médio",     f"${perf.get('avg_win', 0):.2f}")
    c2.metric("Perda Média",     f"${perf.get('avg_loss', 0):.2f}")
    c3.metric("Max Drawdown",    f"${perf.get('max_drawdown', 0):.2f}")
    c4.metric("Expectância",     f"${perf.get('expectancy', 0):.2f}")

    st.divider()

    trades = db.get_trades(limit=1000, since_days=days, only_closed=True)
    if not trades:
        st.info("Sem dados suficientes.")
        return

    df = pd.DataFrame(trades)
    df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce").fillna(0)

    col1, col2 = st.columns(2)

    with col1:
        # Curva de equity por trade
        df_sorted = df.sort_values("entry_time").reset_index(drop=True)
        df_sorted["equity"] = df_sorted["pnl"].cumsum()
        fig_eq = go.Figure(go.Scatter(
            x=df_sorted.index, y=df_sorted["equity"],
            mode="lines+markers",
            line=dict(color="#00cc88", width=2),
            marker=dict(size=4, color=["#00cc88" if v >= 0 else "#ff4444" for v in df_sorted["pnl"]]),
            fill="tozeroy", fillcolor="rgba(0,204,136,0.07)",
            hovertemplate="Trade #%{x}<br>PnL acumulado: $%{y:+.2f}<extra></extra>"
        ))
        fig_eq.update_layout(
            title="Curva de Equity (por trade)",
            template="plotly_dark", height=300,
            margin=dict(l=40, r=20, t=40, b=30),
            yaxis=dict(tickprefix="$", gridcolor="#1e2030"),
            xaxis=dict(gridcolor="#1e2030"),
            paper_bgcolor="#0d0e14", plot_bgcolor="#0d0e14",
        )
        st.plotly_chart(fig_eq, use_container_width=True)

    with col2:
        # Distribuição Ganhos x Perdas (donut)
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
            title="Distribuição Ganhos x Perdas",
            template="plotly_dark", height=300,
            margin=dict(l=20, r=20, t=40, b=20),
            paper_bgcolor="#0d0e14",
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    st.divider()

    # PnL por símbolo — top ganhos e perdas
    if "symbol" in df.columns:
        sym_pnl = df.groupby("symbol")["pnl"].sum().sort_values()
        colors  = ["#ff4444" if v < 0 else "#00cc88" for v in sym_pnl.values]
        fig_bar = go.Figure(go.Bar(
            x=sym_pnl.values,
            y=sym_pnl.index,
            orientation="h",
            marker_color=colors,
            text=[f"${v:+.2f}" for v in sym_pnl.values],
            textposition="outside",
            hovertemplate="%{y}: $%{x:+.2f}<extra></extra>"
        ))
        fig_bar.update_layout(
            title="PnL Acumulado por Símbolo",
            template="plotly_dark", height=max(300, len(sym_pnl) * 22),
            margin=dict(l=100, r=60, t=40, b=30),
            xaxis=dict(tickprefix="$", gridcolor="#1e2030"),
            yaxis=dict(gridcolor="#1e2030"),
            paper_bgcolor="#0d0e14", plot_bgcolor="#0d0e14",
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    # Histograma de PnL por trade
    fig_hist = go.Figure(go.Histogram(
        x=df["pnl"],
        nbinsx=30,
        marker_color="#4488ff",
        opacity=0.8,
        hovertemplate="PnL: $%{x:.2f}<br>Count: %{y}<extra></extra>"
    ))
    fig_hist.add_vline(x=0, line_dash="dash", line_color="#ff4444", opacity=0.6)
    fig_hist.update_layout(
        title="Distribuição de PnL por Trade",
        template="plotly_dark", height=260,
        margin=dict(l=40, r=20, t=40, b=30),
        xaxis=dict(tickprefix="$", gridcolor="#1e2030"),
        yaxis=dict(title="Trades", gridcolor="#1e2030"),
        paper_bgcolor="#0d0e14", plot_bgcolor="#0d0e14",
    )
    st.plotly_chart(fig_hist, use_container_width=True)


# ---------------------------------------------------------------------------
# App principal
# ---------------------------------------------------------------------------
db = get_db()

with st.sidebar:
    st.markdown("## 📈 NovoBotTrading")
    st.caption("Dashboard Cloud · Somente leitura")
    st.divider()

    db_perf_sidebar = db.get_performance_summary(since_days=30)
    pnl_s    = db_perf_sidebar.get("total_pnl", 0.0)
    wr_s     = db_perf_sidebar.get("win_rate", 0.0)
    total_s  = db_perf_sidebar.get("total_trades", 0)

    pnl_color_css = "#00cc88" if pnl_s >= 0 else "#ff4444"
    st.markdown(f"""
    <div style='background:#12131a;border:1px solid #1e2030;border-radius:10px;padding:12px 14px;'>
        <div style='font-size:0.72rem;color:#8b8fa8;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:6px;'>Resumo 30d</div>
        <div style='font-size:1.1rem;font-weight:700;color:{pnl_color_css};'>${pnl_s:+.2f} USDT</div>
        <div style='font-size:0.82rem;color:#ccd0e0;margin-top:4px;'>
            {total_s} trades &nbsp;·&nbsp; {wr_s:.1f}% win rate
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.divider()
    st.info("Dados via Supabase (PostgreSQL)", icon="☁️")
    st.divider()

    auto_refresh = st.toggle("Auto-refresh (60s)", value=True)
    if st.button("🔄 Atualizar agora", use_container_width=True):
        st.rerun()
    st.divider()
    st.caption("Bybit Futures Bot v2.0")

if auto_refresh:
    count = st_autorefresh(interval=60_000, key="cloud_autorefresh")
    st.sidebar.caption(f"Refresh #{count}")

db_perf = db.get_performance_summary(since_days=30)

tabs = st.tabs(["📊  Visão Geral", "📋  Histórico", "📈  Performance"])

with tabs[0]:
    _render_overview(db, db_perf)

with tabs[1]:
    _render_history(db)

with tabs[2]:
    _render_performance(db)
