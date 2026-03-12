# 📘 Documentação Técnica – Sistema Híbrido de Trading (Bybit + IQ/Pocket + MCP Local)

## ✅ É VIÁVEL USAR MCP LOCAL?
Sim. Criar um **MCP local** é totalmente viável, recomendado e profissional para este sistema.

O MCP local atua como uma **camada inteligente de validação**, rodando:
- Localmente (localhost)
- Sem latência crítica
- Sem depender de serviços externos
- Com total controle do código

Ele **não executa trades**, apenas **analisa, valida e classifica sinais**.

---

## 🎯 VISÃO GERAL DO SISTEMA

- 🤖 Execução automática: **Bybit (API oficial)**
- 📲 Execução manual: **IQ Option / Pocket Option (via sinais)**
- 🧠 **MCP Local**: validação contextual com LLM
- 📊 Timeframe fixo: **M5 (5 minutos)**
- 🔐 Gestão de risco rígida e automática

---

## 🧠 PAPEL DO MCP LOCAL

### O MCP FAZ
- Validar contexto do mercado
- Classificar qualidade do setup
- Retornar nível de confiança
- Bloquear operações ruins
- Reduzir overtrade

### O MCP NÃO FAZ
- ❌ Executar ordens
- ❌ Controlar stop/lote
- ❌ Decidir risco
- ❌ Operar sozinho

📌 O MCP **nunca substitui regras técnicas**, apenas valida.

---

## 📊 ESTRATÉGIA (CAMADA DETERMINÍSTICA)

### Indicadores
- EMA 20
- EMA 50
- RSI (14)
- Volume médio

### Tendência de Alta
- Preço acima da EMA 20 e 50
- EMA 20 > EMA 50
- RSI entre 50 e 70

### Tendência de Queda
- Preço abaixo da EMA 20 e 50
- EMA 20 < EMA 50
- RSI entre 30 e 50

Sem tendência clara → **NÃO OPERAR**

---

## 🎯 GATILHO DE ENTRADA
- Pullback até EMA 20
- Candle de rejeição
- Volume acima da média
- Confirmação no fechamento do candle

---

## ⏱️ OPÇÕES BINÁRIAS
- Entrada no início do candle
- Expiração: 5 ou 10 minutos
- CALL (alta) | PUT (queda)

---

## 🔐 GESTÃO DE RISCO
- Saldo exemplo: $10
- Entrada fixa: $1 (10%)
- Perda máxima diária: $2 (20%)
- Máximo: 2 losses consecutivos
- Bloqueio automático de sinais/execuções

---

## 🧠 FLUXO COM MCP LOCAL

1. Fecha candle M5
2. Calcula indicadores
3. Estratégia gera setup
4. MCP local valida contexto
5. Verifica risco diário
6. Executa (Bybit) ou envia sinal (Telegram)
7. Atualiza histórico

---

## ⚙️ ARQUITETURA ATUALIZADA

```
/analisador
  ├─ indicators.py
  ├─ strategy.py

/mcp_local
  ├─ server.py
  ├─ tools.py
  ├─ schemas.py
  ├─ prompts.py

/execution
  ├─ bybit_client.py

/signals
  ├─ telegram_bot.py

/core
  ├─ engine.py
  ├─ scheduler.py

/config
  ├─ settings.yaml

/main.py
```

---

## 🧩 STACK TECNOLÓGICA
- Python 3.10+
- pandas, numpy
- ta / talib
- python-telegram-bot
- MCP SDK (Python)
- LLM local (Ollama) ou cloud
- SQLite / PostgreSQL

---

## 🧠 EXEMPLO DE INPUT PARA MCP

```json
{
  "trend": "alta",
  "ema20": 1.1023,
  "ema50": 1.1001,
  "rsi": 62,
  "volume_ratio": 1.4,
  "risk_ok": true
}
```

### RESPOSTA ESPERADA
```json
{
  "approve": true,
  "confidence": 0.81,
  "comment": "Pullback saudável em tendência de alta"
}
```

---

## 🧠 PROMPT MESTRE ATUALIZADO (VS CODE)

Você é um engenheiro de software especialista em trading algorítmico e IA.

Crie um sistema em Python que:

1. Use timeframe M5
2. Estratégia com EMA 20, EMA 50, RSI e volume
3. Opere somente a favor da tendência
4. Use gatilho de pullback + confirmação
5. Gestão de risco rígida (10% trade / 20% diário)
6. Execução automática via Bybit API
7. Envio de sinais via Telegram para IQ Option e Pocket Option
8. Implemente um MCP LOCAL para:
   - validar sinais
   - retornar confiança
   - bloquear setups ruins
9. MCP não executa ordens nem controla risco
10. Código modular, comentado e pronto para produção
11. Sem martingale

Gere o projeto completo.

---

## 🚀 EVOLUÇÕES FUTURAS
- Backtest com MCP
- LLM local (Ollama)
- Dashboard Web
- SaaS multiusuário
- Machine Learning supervisionado

---

## ✅ CONCLUSÃO
✔ MCP local é totalmente viável  
✔ Melhora qualidade dos sinais  
✔ Não compromete segurança  
✔ Arquitetura profissional e escalável  
