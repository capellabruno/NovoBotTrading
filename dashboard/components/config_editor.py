"""
Aba Config - Editor de configuração com hot-reload.
"""
import streamlit as st
from dashboard.api_client import get_config, update_config


def render(engine_online: bool):
    st.subheader("Configuração do Bot")

    if not engine_online:
        st.error("Engine offline - não é possível editar configurações.")
        return

    config = get_config()
    if not config:
        st.warning("Configuração não disponível. O engine precisa estar rodando.")
        return

    st.info("As alterações entram em vigor no próximo ciclo de trading.")

    changes = {}

    # --- Sistema ---
    with st.expander("Sistema", expanded=True):
        sys_conf = config.get("system", {})
        dry_run = st.toggle("Modo DRY RUN (simulação)", value=sys_conf.get("dry_run", True))
        changes.setdefault("system", {})["dry_run"] = dry_run

    # --- Qualidade ---
    with st.expander("Qualidade do Setup"):
        qual_conf = config.get("quality", {})
        min_score = st.slider("Score Mínimo para Entrada", 0, 100, int(qual_conf.get("min_score", 70)))
        use_patterns = st.toggle("Usar Padrões de Candle", value=qual_conf.get("use_candle_patterns", True))
        use_session = st.toggle("Usar Filtro de Sessão", value=qual_conf.get("use_session_filter", True))
        use_atr = st.toggle("Usar ATR Stops", value=qual_conf.get("use_atr_stops", True))
        changes["quality"] = {
            "min_score": min_score,
            "use_candle_patterns": use_patterns,
            "use_session_filter": use_session,
            "use_atr_stops": use_atr,
        }

    # --- Risco ---
    with st.expander("Gestão de Risco"):
        risk_conf = config.get("risk", {})
        entry_pct = st.number_input("% por Trade (0.01 = 1%)", min_value=0.01, max_value=0.5,
                                     value=float(risk_conf.get("entry_percent", 0.1)), step=0.01)
        sl_pct = st.number_input("Stop Loss %", min_value=0.005, max_value=0.2,
                                   value=float(risk_conf.get("stop_loss_percent", 0.05)), step=0.005)
        tp_pct = st.number_input("Take Profit %", min_value=0.01, max_value=0.5,
                                   value=float(risk_conf.get("take_profit_percent", 0.10)), step=0.01)
        daily_loss = st.number_input("Perda Diária Máxima %", min_value=0.05, max_value=0.5,
                                      value=float(risk_conf.get("daily_loss_percent", 0.20)), step=0.05)
        max_consec = st.number_input("Perdas Consecutivas Máximas", min_value=1, max_value=10,
                                      value=int(risk_conf.get("max_consecutive_losses", 2)))
        changes["risk"] = {
            "entry_percent": entry_pct,
            "stop_loss_percent": sl_pct,
            "take_profit_percent": tp_pct,
            "daily_loss_percent": daily_loss,
            "max_consecutive_losses": max_consec,
        }

    # --- MCP ---
    with st.expander("Validação por IA (MCP)"):
        mcp_conf = config.get("mcp", {})
        mcp_mode = st.selectbox("Modo MCP", ["gemini", "mock", "ollama"],
                                  index=["gemini", "mock", "ollama"].index(mcp_conf.get("mode", "gemini")))
        changes["mcp"] = {"mode": mcp_mode}

    # --- Indicadores ---
    with st.expander("Indicadores Técnicos"):
        ind_conf = config.get("indicators", {})
        ema_fast = st.number_input("EMA Rápida", min_value=5, max_value=50,
                                    value=int(ind_conf.get("ema_fast", 20)))
        ema_slow = st.number_input("EMA Lenta", min_value=20, max_value=200,
                                    value=int(ind_conf.get("ema_slow", 50)))
        rsi_period = st.number_input("Período RSI", min_value=5, max_value=30,
                                      value=int(ind_conf.get("rsi_period", 14)))
        changes["indicators"] = {
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "rsi_period": rsi_period,
        }

    st.divider()

    # --- Credenciais (apenas status) ---
    with st.expander("Credenciais (somente leitura)"):
        st.caption("As credenciais são carregadas do arquivo .env e não são exibidas por segurança.")
        bybit_key = config.get("execution", {}).get("api_key", "")
        tg_token = config.get("signals", {}).get("telegram_token", "")
        gemini_key = config.get("mcp", {}).get("gemini_api_key", "")
        st.write(f"Bybit API Key: {'✅ Configurada' if bybit_key and bybit_key != '***' else '❌ Não configurada'}")
        st.write(f"Telegram Token: {'✅ Configurado' if tg_token and tg_token != '***' else '❌ Não configurado'}")
        st.write(f"Gemini API Key: {'✅ Configurada' if gemini_key and gemini_key != '***' else '❌ Não configurada'}")

    # --- Salvar ---
    if st.button("Salvar Configuração", type="primary"):
        success = update_config(changes)
        if success:
            st.success("Configuração salva! O engine recarregará no próximo ciclo.")
        else:
            st.error("Falha ao salvar configuração. Verifique se o engine está online.")
