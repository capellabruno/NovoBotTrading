"""
NovoBotTrading Dashboard - Interface Gráfica de Acompanhamento
Execute com: streamlit run dashboard/app.py
"""
import sys
import os
import time

# Adicionar o diretório raiz ao path para imports
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import streamlit as st
from streamlit_autorefresh import st_autorefresh

st.set_page_config(
    page_title="NovoBotTrading Dashboard",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

# CSS customizado
st.markdown("""
<style>
    .block-container { padding-top: 1.2rem; padding-bottom: 1rem; }
    .stMetric label { font-size: 0.78rem; color: #8b8fa8; text-transform: uppercase; letter-spacing: 0.05em; }
    .stMetric [data-testid="metric-container"] {
        background: #12131a;
        border: 1px solid #1e2030;
        padding: 14px 16px;
        border-radius: 10px;
    }
    .stMetric [data-testid="stMetricValue"] { font-size: 1.4rem; font-weight: 700; }
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
    div[data-testid="stExpander"] { background: #12131a; border: 1px solid #1e2030; border-radius: 10px; }
    .stDataFrame { font-size: 0.82rem; }
    section[data-testid="stSidebar"] { background: #0d0e14; }
    hr { border-color: #1e2030; margin: 0.8rem 0; }
</style>
""", unsafe_allow_html=True)

# Imports internos
from dashboard.api_client import get_state, is_engine_online, send_pause, send_resume
from database.manager import DatabaseManager

@st.cache_resource
def get_db():
    return DatabaseManager()

db = get_db()


# --- Sidebar ---
with st.sidebar:
    st.title("NovoBotTrading")
    st.caption("Painel de Controle")
    st.divider()

    # Status do engine
    engine_online = is_engine_online()
    status_icon = "🟢" if engine_online else "🔴"
    st.metric("Engine", f"{status_icon} {'Online' if engine_online else 'Offline'}")

    # Buscar estado atual
    state = get_state() if engine_online else None

    if state:
        dry_run = state.get("dry_run", True)
        paused = state.get("is_paused", False)
        cycle = state.get("cycle_number", 0)

        st.metric("Modo", "DRY RUN" if dry_run else "LIVE")
        st.metric("Ciclo", f"#{cycle}")

        st.divider()

        # Controles
        if paused:
            if st.button("▶️ Retomar Bot", use_container_width=True, type="primary"):
                send_resume()
                st.success("Retomando...")
                time.sleep(1)
                st.rerun()
        else:
            if st.button("⏸️ Pausar Bot", use_container_width=True):
                send_pause()
                st.warning("Pausando...")
                time.sleep(1)
                st.rerun()

    st.divider()

    # Auto-refresh
    auto_refresh = st.toggle("Auto-refresh (30s)", value=True)
    if st.button("🔄 Atualizar Agora", use_container_width=True):
        st.rerun()

    st.divider()
    st.caption("Bybit Futures Bot v2.0")
    st.caption("Powered by Claude AI")

# --- Auto-refresh (deve ficar fora do sidebar) ---
if auto_refresh:
    count = st_autorefresh(interval=30_000, key="main_autorefresh")
    st.sidebar.caption(f"Auto-refresh ativo | refresh #{count}")

# --- Dados para as abas (sempre frescos a cada rerun) ---
db_perf = db.get_performance_summary(since_days=30)

# --- Abas principais ---
tabs = st.tabs([
    "Visão Geral",
    "Posições",
    "Histórico de Trades",
    "Performance",
    "Gráficos",
    "Configuração",
    "Logs",
])

with tabs[0]:
    from dashboard.components.overview import render as render_overview
    render_overview(state, db_perf, engine_online)

with tabs[1]:
    from dashboard.components.positions import render as render_positions
    render_positions(state, engine_online)

with tabs[2]:
    from dashboard.components.trade_history import render as render_history
    render_history(db)

with tabs[3]:
    from dashboard.components.performance import render as render_performance
    render_performance(db)

with tabs[4]:
    from dashboard.components.charts import render as render_charts
    render_charts(db)

with tabs[5]:
    from dashboard.components.config_editor import render as render_config
    render_config(engine_online)

with tabs[6]:
    from dashboard.components.log_viewer import render as render_logs
    render_logs(state, db)
