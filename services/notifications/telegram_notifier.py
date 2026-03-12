"""
Telegram Notifier
Cliente principal para envio de notificações
"""

import logging
from typing import Dict, Any
from .telegram_topics_manager import TelegramTopicsManager, TopicType
from .smart_notification_filter import SmartNotificationFilter

logger = logging.getLogger(__name__)

class TelegramNotifier:
    """Notificador Telegram integrado com Tópicos e Filtro Inteligente"""
    
    def __init__(self, config: Dict[str, Any]):
        self.manager = TelegramTopicsManager(config)
        self.filter = SmartNotificationFilter()
        self.enabled = config.get('notifications', {}).get('enabled', True)
        
    @staticmethod
    def _esc(text: str) -> str:
        """Escapa caracteres especiais HTML para campos dinâmicos."""
        return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def notify_trade(self, symbol: str, direction: str, action: str,
                     price: float, size: float, reason: str = ""):
        """Notifica ações de trade (Entradas)"""
        if not self.enabled: return

        # Filtro de spam
        key = f"{symbol}_{direction}_{action}"
        if not self.filter.should_notify("trade_entry", key):
            return

        emoji = "🟢" if direction.upper() == "LONG" else "🔴"
        action_emoji = "🚀" if action == "OPEN" else "🛑"

        msg = (
            f"{action_emoji} <b>POSIÇÃO {self._esc(action)}</b>\n\n"
            f"<b>{emoji} {self._esc(symbol)}</b> ({self._esc(direction)})\n"
            f"💰 Preço: {price}\n"
            f"📏 Tamanho: {size}\n"
        )
        if reason:
            msg += f"ℹ️ Motivo: {self._esc(reason)}"

        self.manager.send_message(TopicType.TRADE_ENTRIES, msg)

    def notify_close(self, symbol: str, pnl: float, pnl_percent: float, reason: str):
        """Notifica fechamento de trade (Saídas)"""
        if not self.enabled: return

        pnl_emoji = "✅" if pnl >= 0 else "❌"
        sign = "+" if pnl >= 0 else ""

        msg = (
            f"{pnl_emoji} <b>POSIÇÃO FECHADA</b>\n\n"
            f"🪙 <b>{self._esc(symbol)}</b>\n"
            f"💵 P&amp;L: {sign}${pnl:.2f}\n"
            f"📈 ROE: {pnl_percent:.2f}%\n"
            f"📝 Motivo: {self._esc(reason)}"
        )

        self.manager.send_message(TopicType.TRADE_EXITS, msg)

    def notify_error(self, source: str, error_msg: str):
        """Notifica erros do sistema"""
        if not self.enabled: return

        if not self.filter.should_notify("system_error", source):
            return

        msg = (
            f"🚨 <b>ERRO NO SISTEMA</b>\n\n"
            f"📌 Origem: {self._esc(source)}\n"
            f"⚠️ Erro: {self._esc(error_msg)}"
        )

        self.manager.send_message(TopicType.SYSTEM_STATUS, msg)
