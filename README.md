# Sistema Híbrido de Trading (Bybit + IQ/Pocket + MCP Local)

Sistema de trading automatizado e híbrido que utiliza análise técnica clássica (EMA, RSI, Volume) validada por um MCP (Model Context Protocol) Local para filtrar sinais de alta qualidade.

## Funcionalidades

- **Análise Técnica**: Cálculo de indicadores em tempo real (M5).
- **Validação Inteligente**: MCP Local analisa o contexto do mercado usando LLM antes de aprovar operações.
- **Execução Automática**: Integração com Bybit para trades automáticos.
- **Sinais Manuais**: Envio de sinais para Telegram (para IQ Option / Pocket Option).
- **Gestão de Risco**: Controle rígido de drawdown e position sizing.

## Estrutura do Projeto

- `analisador/`: Módulo de indicadores e estratégia.
- `mcp_local/`: Servidor MCP e ferramentas de validação (LLM).
- `execution/`: Cliente da exchange (Bybit).
- `signals/`: Bot de notificações (Telegram).
- `core/`: Engine principal e agendamento.
- `config/`: Arquivos de configuração.

## Como Executar

1. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```

2. Configure o arquivo `config/settings.yaml` com suas chaves de API e preferências.

3. Execute o sistema:
   ```bash
   python main.py
   ```

## Requisitos

- Python 3.10+
- Conta na Bybit (para execução automática)
- Bot no Telegram (para sinais)
- Ollama (opcional, para MCP local real) ou MockMode ativado.
