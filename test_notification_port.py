import logging
import sys
import os
from pathlib import Path

import yaml

# Adicionar raiz ao path
sys.path.append(os.getcwd())

from services.notifications.telegram_notifier import TelegramNotifier, TopicType

# Configurar logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestNotification")

def load_config(path: str = "config/settings.yaml"):
    if not os.path.exists(path):
        logger.error(f"Arquivo de configuração não encontrado: {path}")
        sys.exit(1)
    
    with open(path, 'r') as f:
        return yaml.safe_load(f)

def test_system():
    logger.info("--- Iniciando Teste de Portabilidade do Telegram ---")
    
    # 1. Carregar configuração
    config = load_config()
    
    # 2. Inicializar Notificador
    notifier = TelegramNotifier(config)
    
    # 3. Testar envio para cada tópico
    logger.info("Enviando notificações de teste...")
    
    # Trade Entry
    notifier.notify_trade(
        symbol="BTCUSDT", 
        direction="LONG", 
        action="OPEN", 
        price=50000.00, 
        size=0.1, 
        reason="Teste de Integração"
    )
    
    # Trade Exit
    notifier.notify_close(
        symbol="BTCUSDT", 
        pnl=150.00, 
        pnl_percent=3.5, 
        reason="Take Profit"
    )
    
    # System Error
    notifier.notify_error("Teste", "Injeção de erro simulada")
    
    # Mensagem direta via gerenciador (TopicType)
    notifier.manager.send_message(TopicType.PORTFOLIO, "📊 Teste de Relatório de Portfolio")
    notifier.manager.send_message(TopicType.RISK_ALERTS, "⚠️ Teste de Alerta de Risco")
    
    # 4. Verificar persistência
    json_path = Path("data/telegram_topics.json")
    if json_path.exists():
        logger.info(f"✅ Arquivo de persistência criado: {json_path}")
        with open(json_path, 'r') as f:
            print(f.read())
    else:
        logger.error("❌ Arquivo de persistência NÃO encontrado!")

if __name__ == "__main__":
    test_system()
