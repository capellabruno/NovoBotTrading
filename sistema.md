# Sistema Híbrido de Trading (Bybit + IQ/Pocket + MCP Local)

## Visão Geral
Este projeto implementa um sistema de trading híbrido que utiliza execução automática na Bybit e envia sinais manuais para IQ Option e Pocket Option via Telegram. O diferencial é a utilização de um **MCP Local** (Model Context Protocol) para validar os sinais gerados pela estratégia determinística antes da execução ou envio.

## Arquitetura
O sistema é modular e composto pelos seguintes componentes:
- **Analisador**: Responsável pelo cálculo de indicadores (EMA, RSI, ATR, Volume) e aplicação da estratégia de tendência.
- **MCP Local**: Camada de inteligência que valida o contexto do mercado usando LLM (local ou cloud), atuando como filtro de qualidade.
- **Execution**: Módulo de execução automática na Bybit.
- **Signals**: Bot de Telegram para envio de sinais.
- **Core**: Engine principal e agendador (Scheduler) para orquestrar o fluxo.
- **Backtest**: Sistema completo de backtesting para validação de estratégias.

## Tecnologias
- **Linguagem**: Python 3.10+
- **Bibliotecas**: pandas, numpy, ta/talib, python-telegram-bot, MCP SDK.
- **LLM**: Google Gemini 2.5 Flash (API gratuita). Alternativas disponíveis: Ollama local (LLAMA 3.2) ou DeepSeek-R1.

## Regras de Negócio Importantes
- **Timeframe**: Gráfico de 15m para identificação de sinal e 3m para timing de entrada.
- **Gestão de Risco**: 
  - Entrada: 10% do saldo.
  - Stop Loss Diário: 20% do saldo.
  - Max Losses Consecutivos: 2.
- **Validação**: O MCP não executa ordens, apenas aprova ou reprova com base em contexto.
- **Score Mínimo**: 70 pontos (configurável) para permitir entrada.

---

## Melhorias Implementadas (2026-01-23)

### 1. Sistema de Backtest
Novo módulo `/backtest` para testar estratégias em dados históricos:
- **`data_loader.py`**: Carrega dados históricos da Bybit API
- **`simulator.py`**: Simula execução de ordens e calcula PnL
- **`metrics.py`**: Calcula métricas (Win Rate, Sharpe, Max Drawdown, Profit Factor)
- **`engine.py`**: Motor principal do backtest
- **`report.py`**: Gera relatórios detalhados

**Executar**: `python backtest_runner.py`

### 2. Padrões de Candles (Price Action)
Detecção automática de padrões de reversão e continuação:
- **BULLISH**: Hammer, Inverted Hammer, Bullish Engulfing, Pin Bar Bullish
- **BEARISH**: Shooting Star, Bearish Engulfing, Pin Bar Bearish
- **NEUTRAL**: Doji (indecisão)

### 3. Filtro de Sessões de Mercado
Avaliação de liquidez por horário (UTC):
- **OVERLAP (13-16h)**: Máxima liquidez (Score 1.0)
- **NEW_YORK (13-21h)**: Alta liquidez (Score 0.9)
- **LONDON (8-16h)**: Alta liquidez (Score 0.85)
- **ASIAN (0-8h)**: Moderada (Score 0.6)
- **OFF_HOURS (21-24h)**: Baixa (Score 0.4)

### 4. ATR Dynamic Stop Loss
Stop Loss e Take Profit baseados em volatilidade:
- **SL**: 1.5x ATR (Average True Range)
- **TP**: 2.5x ATR (R:R 1:1.67)
- Adaptação automática à volatilidade do mercado

### 5. Score de Qualidade do Setup
Sistema de pontuação 0-100 para filtrar setups:
| Critério | Peso |
|----------|------|
| Tendência Alinhada | 25 pts |
| RSI Favorável | 15 pts |
| Volume Acima Média | 15 pts |
| Próximo S/R Favorável | 15 pts |
| Padrão de Candle | 15 pts |
| Sessão de Alta Liquidez | 10 pts |
| ATR Favorável | 5 pts |

**Notas**:
- A (90+): Setup excelente
- B (80-89): Setup muito bom
- C (70-79): Setup aceitável
- D/F (<70): Setup fraco - bloqueado

### 7. Sistema de Trading Adaptativo (Adaptive Optimzer)
Módulo inteligente que ajusta configurações em tempo real baseado em performance recente:
- **Periodicidade**: Reavalia a cada 6 horas.
- **Processo**:
  1. Baixa dados dos últimos 10 dias.
  2. Executa backtests em múltiplos timeframes (5, 15, 30, 60m).
  3. Compara resultados (Win Rate, Profit Factor).
- **Ação**:
  - Força o timeframe de 15m para análise principal.
  - Consulta o timeframe de 3m quando um sinal é identificado para validar o timing de entrada (FOGO vs AGUARDE).
  - Inclui contexto de 3m na validação do MCP Local.
  - Note: O Otimizador Adaptativo automático foi desabilitado no `settings.yaml` para priorizar esta configuração fixa.

---

## Estrutura de Diretórios
```
/analisador
  ├─ indicators.py      # EMA, RSI, ATR, S/R, Candle Patterns
  ├─ strategy.py        # Estratégia determinística
  ├─ session_filter.py  # Filtro de sessões de mercado
  └─ quality_scorer.py  # Sistema de Score de Qualidade
/backtest
  ├─ __init__.py
  ├─ engine.py          # Motor do backtest
  ├─ simulator.py       # Simulador de trades
  ├─ data_loader.py     # Carregador de dados com cache
  ├─ metrics.py         # Calculador de métricas
  └─ report.py          # Gerador de relatórios
/core
  ├─ engine.py          # Engine principal (integra AdaptiveOptimizer)
  ├─ optimizer.py       # Otimizador Adaptativo
  └─ scheduler.py       # Agendador
...
```

---

## Configuração Atual com Otimizador

```yaml
system:
  timeframe: "15m"  # Fallback
  dry_run: true

adaptive:
  enabled: true
  update_interval_hours: 6
  lookback_days: 10
  min_win_rate: 50.0
  candidate_timeframes: [5, 15, 30, 60]
```

---

## Próximos Passos
1. Monitorar o log para verificar as decisões do Otimizador.
2. Ajustar `min_win_rate` se o bot ficar muito restritivo.
3. Voltar para modo LIVE após validação positiva.


