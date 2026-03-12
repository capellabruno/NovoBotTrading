"""
Smart Notification Filter
Filtro inteligente para evitar spam e duplicações
"""

import logging
import time
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

class SmartNotificationFilter:
    """Filtra notificações para evitar spam e duplicatas"""
    
    def __init__(self):
        # Cache de últimas notificações: {(tipo, simbolo): (timestamp, conteudo_hash)}
        self.last_notifications: Dict[str, float] = {}
        
        # Cooldowns por tipo (em segundos)
        self.cooldowns = {
            'trade_entry': 60,      # Evitar repetição da mesma entrada
            'trade_exit': 60,       # Evitar repetição de saída
            'risk_alert': 300,      # Alertas de risco a cada 5 min máximo
            'system_error': 3600,   # Erros de sistema a cada 1h
            'analysis': 900         # Análises a cada 15 min por par
        }
        
    def should_notify(self, notify_type: str, key: str, content: str = None) -> bool:
        """
        Verifica se deve enviar notificação
        
        Args:
            notify_type: Tipo da notificação (usado para cooldown)
            key: Chave única do evento (ex: 'ETHUSDT_LONG_ENTRY')
            content: Conteúdo opcional para detecção de duplicata exata
            
        Returns:
            bool: True se deve notificar
        """
        now = time.time()
        cache_key = f"{notify_type}:{key}"
        
        last_time = self.last_notifications.get(cache_key, 0)
        cooldown = self.cooldowns.get(notify_type, 60)
        
        # Verificar cooldown
        if (now - last_time) < cooldown:
            logger.debug(f"Notificação bloqueada por cooldown: {cache_key}")
            return False
            
        # Atualizar timestamp
        self.last_notifications[cache_key] = now
        return True
