# Neste design inicial, tools.py pode ser usado se expandirmos o MCP 
# para chamar funções externas (ex: checar notícias).
# Por enquanto, deixarei como placeholder ou funções auxiliares de formatação.

def format_signal_message(validation_result, signal_data):
    icon = "✅" if validation_result.approved else "❌"
    return (
        f"{icon} SINAL VALIDADO PELO MCP\n"
        f"Ação: {signal_data.action}\n"
        f"Confiança: {validation_result.confidence * 100:.1f}%\n"
        f"Motivo: {validation_result.reasoning}\n"
    )
