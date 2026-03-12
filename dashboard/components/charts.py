"""
Aba Charts - Gráfico de preços com entradas/saídas marcadas.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


@st.cache_data(ttl=120)
def _fetch_candles(symbol: str, interval: int, limit: int) -> pd.DataFrame:
    """Busca candles da Bybit usando o BybitClient."""
    try:
        from config.config_loader import load_config
        from execution.bybit_client import BybitClient
        config = load_config()
        client = BybitClient(config)
        candles = client.fetch_candles(symbol=symbol, interval=interval, limit=limit)
        if not candles:
            return pd.DataFrame()
        cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'turnover']
        df = pd.DataFrame(candles, columns=cols)
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col])
        df['timestamp'] = pd.to_datetime(pd.to_numeric(df['timestamp']), unit='ms')
        return df.sort_values('timestamp').reset_index(drop=True)
    except Exception as e:
        st.error(f"Erro ao buscar dados: {e}")
        return pd.DataFrame()


def render(db):
    st.subheader("Gráfico de Preços")

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        db_symbols = db.get_symbols()
        default_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
                           "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT"]
        symbol_options = sorted(set(db_symbols + default_symbols))
        symbol = st.selectbox("Símbolo", symbol_options,
                              index=symbol_options.index("BTCUSDT") if "BTCUSDT" in symbol_options else 0,
                              key="chart_sym")
    with col2:
        tf_map = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240}
        tf_label = st.selectbox("Timeframe", list(tf_map.keys()), index=2, key="chart_tf")
        interval = tf_map[tf_label]
    with col3:
        limit = st.selectbox("Velas", [100, 200, 500], index=1, key="chart_limit")

    col_btn, col_info = st.columns([1, 3])
    with col_btn:
        if st.button("🔄 Atualizar", use_container_width=True):
            st.cache_data.clear()

    df = _fetch_candles(symbol, interval, limit)

    if df.empty:
        st.warning("Sem dados para exibir.")
        return

    # Indicadores
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()

    delta = df["close"].diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, float("nan"))
    df["rsi"] = 100 - (100 / (1 + rs))

    # Trades deste símbolo para marcar no gráfico
    trades = db.get_trades(symbol=symbol, limit=50, since_days=30)

    # --- Figura ---
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.60, 0.18, 0.22],
        subplot_titles=[f"{symbol} · {tf_label}", "Volume", "RSI (14)"]
    )

    # Candlestick
    fig.add_trace(go.Candlestick(
        x=df["timestamp"],
        open=df["open"], high=df["high"],
        low=df["low"],   close=df["close"],
        name="Preço",
        increasing_line_color="#00cc88",
        decreasing_line_color="#ff4444",
        increasing_fillcolor="#00cc8840",
        decreasing_fillcolor="#ff444440",
    ), row=1, col=1)

    # EMAs
    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df["ema20"],
        name="EMA 20", line=dict(color="#ffaa00", width=1.5),
        hovertemplate="EMA20: %{y:.4f}<extra></extra>"
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df["ema50"],
        name="EMA 50", line=dict(color="#4488ff", width=1.5),
        hovertemplate="EMA50: %{y:.4f}<extra></extra>"
    ), row=1, col=1)

    # Marcadores de Trades
    for t in trades:
        entry_time  = t.get("entry_time")
        exit_time   = t.get("exit_time")
        entry_price = t.get("entry_price")
        exit_price  = t.get("exit_price")
        direction   = t.get("direction", "LONG")
        pnl         = t.get("pnl")
        mode        = t.get("mode", "live")
        opacity     = 1.0 if mode == "live" else 0.4

        if entry_time and entry_price:
            try:
                et    = pd.to_datetime(entry_time)
                color = "#00cc88" if direction == "LONG" else "#ff4444"
                sym_m = "triangle-up" if direction == "LONG" else "triangle-down"
                fig.add_trace(go.Scatter(
                    x=[et], y=[entry_price],
                    mode="markers",
                    marker=dict(symbol=sym_m, size=14, color=color, opacity=opacity,
                                line=dict(width=1, color="#ffffff30")),
                    name=f"Entrada {direction}",
                    showlegend=False,
                    hovertemplate=f"{direction} @ ${'%.4f' % entry_price}<br>Modo: {mode}<extra></extra>",
                ), row=1, col=1)
            except Exception:
                pass

        if exit_time and exit_price:
            try:
                ext       = pd.to_datetime(exit_time)
                pnl_color = "#00cc88" if (pnl or 0) >= 0 else "#ff4444"
                fig.add_trace(go.Scatter(
                    x=[ext], y=[exit_price],
                    mode="markers",
                    marker=dict(symbol="x", size=12, color=pnl_color, opacity=opacity,
                                line=dict(width=2, color=pnl_color)),
                    name="Saída",
                    showlegend=False,
                    hovertemplate=f"Saída @ ${'%.4f' % exit_price}<br>PnL: ${'%+.2f' % (pnl or 0)}<extra></extra>",
                ), row=1, col=1)
            except Exception:
                pass

    # Volume
    vol_colors = ["#00cc8866" if c >= o else "#ff444466"
                  for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(
        x=df["timestamp"], y=df["volume"],
        name="Volume", marker_color=vol_colors, showlegend=False,
        hovertemplate="Vol: %{y:,.0f}<extra></extra>"
    ), row=2, col=1)

    # RSI
    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df["rsi"],
        name="RSI", line=dict(color="#aa88ff", width=1.5),
        hovertemplate="RSI: %{y:.1f}<extra></extra>"
    ), row=3, col=1)

    # Zonas RSI
    fig.add_hrect(y0=70, y1=100, fillcolor="#ff444415", line_width=0, row=3, col=1)
    fig.add_hrect(y0=0, y1=30, fillcolor="#00cc8815", line_width=0, row=3, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="#ff4444", line_width=1, row=3, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="#00cc88", line_width=1, row=3, col=1)
    fig.add_hline(y=50, line_dash="dot", line_color="#888888", line_width=0.8,
                  opacity=0.4, row=3, col=1)

    bg = "#0d0e14"
    grid_color = "#1e2030"

    fig.update_layout(
        template="plotly_dark",
        height=720,
        showlegend=True,
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.01,
                    xanchor="right", x=1, font=dict(size=11)),
        margin=dict(l=50, r=30, t=50, b=20),
        paper_bgcolor=bg, plot_bgcolor=bg,
    )
    for i in range(1, 4):
        fig.update_xaxes(gridcolor=grid_color, showgrid=True, row=i, col=1)
        fig.update_yaxes(gridcolor=grid_color, showgrid=True, row=i, col=1)

    fig.update_yaxes(title_text="RSI", row=3, col=1, range=[0, 100])

    st.plotly_chart(fig, use_container_width=True)

    if trades:
        live_trades = [t for t in trades if t.get("mode") == "live"]
        if live_trades:
            st.caption(f"📌 {len(live_trades)} trade(s) live marcados no gráfico (últimos 30 dias)")
