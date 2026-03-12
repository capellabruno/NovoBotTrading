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
    page_title="NovoBotTrading Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .stMetric label { font-size: 0.85rem; }
    .stMetric [data-testid="metric-container"] { background: #1e1e2e; padding: 12px; border-radius: 8px; }
    .block-container { padding-top: 1rem; }
    .stDataFrame { font-size: 0.8rem; }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_db():
    """Inicializa conexão com o banco. Usa DATABASE_URL do st.secrets ou env."""
    from database.manager import DatabaseManager

    db_url = None
    try:
        db_url = st.secrets["DATABASE_URL"]
    except Exception:
        pass  # fallback para env var DATABASE_URL ou SQLite

    return DatabaseManager(database_url=db_url)


def _render_overview(db, db_perf):
    wins = db_perf.get("wins", 0)
    losses = db_perf.get("losses", 0)
    total_pnl = db_perf.get("total_pnl", 0.0)
    win_rate = db_perf.get("win_rate", 0.0)
    total_trades = db_perf.get("total_trades", 0)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Trades (30d)", total_trades)
    with col2:
        st.metric("Win Rate (30d)", f"{win_rate:.1f}%")
    with col3:
        st.metric("PnL Total (30d)", f"${total_pnl:+.2f}")
    with col4:
        st.metric("Profit Factor", f"{db_perf.get('profit_factor', 0):.2f}")

    st.divider()

    st.subheader("Trades Abertos")
    open_trades = db.get_open_trades()
    if open_trades:
        df = pd.DataFrame(open_trades)
        cols_show = ["symbol", "direction", "entry_price", "size_usdt",
                     "stop_loss", "take_profit", "entry_time", "quality_score", "mode"]
        df_show = df[[c for c in cols_show if c in df.columns]]
        st.dataframe(df_show, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhuma posição aberta no momento.")

    st.divider()

    st.subheader("Evolução do Saldo (7 dias)")
    balance_hist = db.get_balance_history(days=7)
    if balance_hist:
        df_bal = pd.DataFrame(balance_hist)
        df_bal["timestamp"] = pd.to_datetime(df_bal["timestamp"])
        fig = go.Figure(go.Scatter(
            x=df_bal["timestamp"], y=df_bal["balance"],
            mode="lines", line=dict(color="#00cc88", width=2),
            fill="tozeroy", fillcolor="rgba(0,204,136,0.1)"
        ))
        fig.update_layout(template="plotly_dark", height=250,
                          margin=dict(l=40, r=20, t=20, b=30))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Sem histórico de saldo ainda.")


# --- App principal ---
db = get_db()

with st.sidebar:
    st.title("NovoBotTrading")
    st.caption("Dashboard Cloud")
    st.divider()
    st.info("Modo somente leitura — dados via Supabase", icon="☁️")
    st.divider()
    auto_refresh = st.toggle("Auto-refresh (60s)", value=True)
    if st.button("🔄 Atualizar Agora", use_container_width=True):
        st.rerun()
    st.divider()
    st.caption("Bybit Futures Bot v2.0")

if auto_refresh:
    count = st_autorefresh(interval=60_000, key="cloud_autorefresh")
    st.sidebar.caption(f"Auto-refresh ativo | #{count}")

db_perf = db.get_performance_summary(since_days=30)

tabs = st.tabs(["Visão Geral", "Histórico de Trades", "Performance", "Gráficos"])

with tabs[0]:
    _render_overview(db, db_perf)

with tabs[1]:
    from dashboard.components.trade_history import render as render_history
    render_history(db)

with tabs[2]:
    from dashboard.components.performance import render as render_performance
    render_performance(db)

with tabs[3]:
    from dashboard.components.charts import render as render_charts
    render_charts(db)
