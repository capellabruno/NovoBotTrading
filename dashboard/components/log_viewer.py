"""
Aba Log Viewer - Visualizador de logs em tempo real.
Lê diretamente do arquivo trading_system.log para exibir todos os logs do engine.
"""
import os
import re
import streamlit as st
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOG_FILE = os.path.join(ROOT, "trading_system.log")

# Regex para parsear linhas de log padrão Python:
# 2026-03-10 14:32:15,123 - core.engine - INFO - [ETHUSDT] Preço: ...
RE_LOG = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+-\s+([\w.]+)\s+-\s+(INFO|WARNING|ERROR|DEBUG|CRITICAL)\s+-\s+(.+)$"
)


def _read_log_tail(n_lines: int, level_filter: str, source_filter: str) -> list:
    """Lê as últimas n_lines do arquivo de log e retorna lista de dicts."""
    if not os.path.exists(LOG_FILE):
        return []

    # Ler tail eficientemente
    with open(LOG_FILE, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        chunk = min(size, n_lines * 220)
        f.seek(max(0, size - chunk))
        raw = f.read().decode("utf-8", errors="replace")

    events = []
    for line in raw.splitlines():
        m = RE_LOG.match(line.rstrip())
        if not m:
            continue
        ts, source, level, message = m.group(1), m.group(2), m.group(3), m.group(4)

        if level_filter != "ALL" and level != level_filter:
            continue
        if source_filter and source_filter.lower() not in source.lower() and source_filter.lower() not in message.lower():
            continue

        events.append({"timestamp": ts, "level": level, "source": source, "message": message})

    return events[-n_lines:]


def render(state: dict, db):
    st.subheader("Log do Sistema")

    col1, col2, col3 = st.columns(3)
    with col1:
        level_filter = st.selectbox("Nível", ["ALL", "INFO", "WARNING", "ERROR", "DEBUG"])
    with col2:
        source_filter = st.text_input("Filtrar (módulo ou texto)", "")
    with col3:
        limit = st.number_input("Últimas N linhas", min_value=20, max_value=1000, value=200)

    all_events = _read_log_tail(int(limit), level_filter, source_filter)

    if not all_events:
        if not os.path.exists(LOG_FILE):
            st.warning(f"Arquivo de log não encontrado: {LOG_FILE}")
        else:
            st.info("Nenhum evento encontrado com os filtros aplicados.")
        return

    df = pd.DataFrame(all_events)

    # Colorir por nível
    def color_level(val):
        if val == "ERROR" or val == "CRITICAL":
            return "background-color: rgba(255,68,68,0.15); color: #ff6666"
        elif val == "WARNING":
            return "background-color: rgba(255,165,0,0.15); color: #ffa500"
        elif val == "DEBUG":
            return "color: #666666"
        return "color: #cccccc"

    col_order = [c for c in ["timestamp", "level", "source", "message"] if c in df.columns]
    df = df[col_order]
    df.columns = [c.capitalize() for c in df.columns]

    if "Level" in df.columns:
        st.dataframe(
            df.style.applymap(color_level, subset=["Level"]),
            use_container_width=True,
            hide_index=True,
            height=450,
        )
    else:
        st.dataframe(df, use_container_width=True, hide_index=True, height=450)

    st.caption(f"Exibindo {len(all_events)} linhas de {LOG_FILE}")

    # Export
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("Exportar Logs CSV", data=csv, file_name="logs_export.csv", mime="text/csv")
