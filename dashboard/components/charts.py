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


def _fetch_candles(symbol: str, interval: int = 15, limit: int = 200) -> pd.DataFrame:
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

    col1, col2 = st.columns(2)
    with col1:
        symbol = st.selectbox("Símbolo", [
            "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT",
            "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "MATICUSDT",
            "1000PEPEUSDT", "WIFUSDT", "NOTUSDT", "LINKUSDT"
        ])
    with col2:
        tf_map = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}
        tf_label = st.selectbox("Timeframe", list(tf_map.keys()), index=1)
        interval = tf_map[tf_label]

    if st.button("Atualizar Gráfico"):
        st.cache_data.clear()

    df = _fetch_candles(symbol, interval)

    if df.empty:
        st.warning("Sem dados para exibir.")
        return

    # Calcular EMAs
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()

    # Calcular RSI
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, float("nan"))
    df["rsi"] = 100 - (100 / (1 + rs))

    # Buscar trades deste símbolo para marcar no gráfico
    trades = db.get_trades(symbol=symbol, limit=50, since_days=30)

    # --- Criar figura ---
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.6, 0.2, 0.2],
        subplot_titles=[f"{symbol} - {tf_label}", "Volume", "RSI"]
    )

    # Candlestick
    fig.add_trace(go.Candlestick(
        x=df["timestamp"],
        open=df["open"],
        high=df["high"],
        low=df["low"],
        close=df["close"],
        name="Preço",
        increasing_line_color="#00cc88",
        decreasing_line_color="#ff4444",
    ), row=1, col=1)

    # EMAs
    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df["ema20"],
        name="EMA 20", line=dict(color="#ffa500", width=1.5)
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df["ema50"],
        name="EMA 50", line=dict(color="#4488ff", width=1.5)
    ), row=1, col=1)

    # Marcadores de Trades
    for t in trades:
        entry_time = t.get("entry_time")
        exit_time = t.get("exit_time")
        entry_price = t.get("entry_price")
        exit_price = t.get("exit_price")
        direction = t.get("direction", "LONG")
        pnl = t.get("pnl")

        if entry_time and entry_price:
            try:
                et = pd.to_datetime(entry_time)
                color = "#00cc88" if direction == "LONG" else "#ff4444"
                symbol_marker = "triangle-up" if direction == "LONG" else "triangle-down"
                fig.add_trace(go.Scatter(
                    x=[et], y=[entry_price],
                    mode="markers",
                    marker=dict(symbol=symbol_marker, size=12, color=color),
                    name=f"Entrada {direction}",
                    showlegend=False,
                    hovertext=f"{direction} @ ${entry_price:.4f}",
                ), row=1, col=1)
            except Exception:
                pass

        if exit_time and exit_price:
            try:
                ext = pd.to_datetime(exit_time)
                pnl_color = "#00cc88" if (pnl or 0) >= 0 else "#ff4444"
                fig.add_trace(go.Scatter(
                    x=[ext], y=[exit_price],
                    mode="markers",
                    marker=dict(symbol="x", size=10, color=pnl_color),
                    name="Saída",
                    showlegend=False,
                    hovertext=f"Saída @ ${exit_price:.4f} | PnL: ${pnl or 0:+.2f}",
                ), row=1, col=1)
            except Exception:
                pass

    # Volume
    vol_colors = ["#00cc88" if c >= o else "#ff4444"
                  for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(
        x=df["timestamp"], y=df["volume"],
        name="Volume", marker_color=vol_colors, showlegend=False
    ), row=2, col=1)

    # RSI
    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df["rsi"],
        name="RSI", line=dict(color="#aa88ff", width=1.5)
    ), row=3, col=1)

    fig.add_hline(y=70, line_dash="dash", line_color="red", row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", row=3, col=1)
    fig.add_hline(y=50, line_dash="dot", line_color="gray", opacity=0.5, row=3, col=1)

    # Layout
    fig.update_layout(
        template="plotly_dark",
        height=700,
        showlegend=True,
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=50, r=50, t=50, b=30),
    )
    fig.update_yaxes(title_text="RSI", row=3, col=1, range=[0, 100])

    st.plotly_chart(fig, use_container_width=True)
