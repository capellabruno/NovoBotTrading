import logging
import requests
from typing import Dict, Any

logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self, config: Dict[str, Any]):
        self.config = config.get("signals", {})
        self.token = self.config.get("telegram_token")
        self.chat_id = self.config.get("telegram_chat_id")
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def send_message(self, message: str):
        if not self.token or not self.chat_id:
            logger.warning("Telegram não configurado. Token ou Chat ID faltando.")
            return

        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }

        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code != 200:
                logger.error(f"Erro ao enviar mensagem Telegram: {response.text}")
            else:
                logger.debug("Mensagem Telegram enviada com sucesso.")
        except Exception as e:
            logger.error(f"Exceção ao enviar mensagem Telegram: {e}")
