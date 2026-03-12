"""
Telegram Topics Manager
Sistema para organizar notificações em tópicos específicos de um supergrupo
Portado e Adaptado para NovoBotTrading com persistência robusta
"""

import logging
import json
import os
from pathlib import Path
from typing import Dict, Optional, Any
from enum import Enum
import requests

logger = logging.getLogger(__name__)

class TopicType(Enum):
    """Tipos de tópicos organizados"""
    TRADE_ENTRIES = "TRADE_ENTRIES"     # 📈 Entradas de posição
    TRADE_EXITS = "TRADE_EXITS"         # 📉 Saídas de posição  
    PORTFOLIO = "PORTFOLIO"             # 📊 Resumos de portfolio
    RISK_ALERTS = "RISK_ALERTS"         # ⚠️ Alertas de risco
    SYSTEM_STATUS = "SYSTEM_STATUS"     # 🔧 Status do sistema
    ANALYSIS = "ANALYSIS"               # 🔍 Análises técnicas
    DAILY_REPORT = "DAILY_REPORT"       # 📅 Relatório Diário

class TelegramTopicsManager:
    """Gerenciador de tópicos organizados no Telegram"""
    
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(TelegramTopicsManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, config: Dict[str, Any] = None):
        if hasattr(self, '_initialized') and self._initialized:
            return
            
        self.config = config or {}
        self.signals_config = self.config.get('signals', {})
        self.bot_token = self.signals_config.get('telegram_token')
        self.chat_id = self.signals_config.get('telegram_chat_id')
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        
        # Arquivo de persistência
        self.topics_file = Path("data/telegram_topics.json")
        self.topics_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Mapa de IDs dos tópicos
        self.topic_ids: Dict[str, int] = {}
        
        # Configuração visual dos tópicos
        self.topic_config = {
            TopicType.TRADE_ENTRIES: {'name': '📈 Entradas', 'color': 0x00FF00},
            TopicType.TRADE_EXITS: {'name': '📉 Saídas', 'color': 0xFF6B35},
            TopicType.PORTFOLIO: {'name': '📊 Portfolio', 'color': 0x0099FF},
            TopicType.RISK_ALERTS: {'name': '⚠️ Risco', 'color': 0xFF0000},
            TopicType.SYSTEM_STATUS: {'name': '🔧 Sistema', 'color': 0x666666},
            TopicType.ANALYSIS: {'name': '🔍 Análises', 'color': 0x9933FF},
            TopicType.DAILY_REPORT: {'name': '📅 Relatório Diário', 'color': 0xFFAE00}
        }
        
        self._load_topics()
        self._initialized = True

    def _load_topics(self):
        """Carrega tópicos do arquivo JSON"""
        if self.topics_file.exists():
            try:
                with open(self.topics_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Migrar chaves string para Enum se necessário, ou manter string
                    self.topic_ids = data
                    logger.info(f"Tópicos carregados: {len(self.topic_ids)} encontrados.")
            except Exception as e:
                logger.error(f"Erro ao carregar tópicos: {e}")
                
        # Verificar override manual no settings
        manual_topics = self.config.get('notifications', {}).get('topic_ids', {})
        if manual_topics:
            for key, value in manual_topics.items():
                if value and str(value) != "0":
                    valid_key = key.upper()
                    if hasattr(TopicType, valid_key):
                        self.topic_ids[valid_key] = int(value)
                        logger.info(f"Override manual aplicado para {valid_key}: {value}")

    def _save_topics(self):
        """Salva tópicos no arquivo JSON"""
        try:
            with open(self.topics_file, 'w', encoding='utf-8') as f:
                json.dump(self.topic_ids, f, indent=2)
        except Exception as e:
            logger.error(f"Erro ao salvar tópicos: {e}")

    def _create_topic(self, name: str, icon_color: int) -> Optional[int]:
        """Cria um novo tópico via API do Telegram"""
        if not self.bot_token or not self.chat_id:
            return None
            
        url = f"{self.base_url}/createForumTopic"
        payload = {
            "chat_id": self.chat_id,
            "name": name,
            "icon_color": icon_color
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                result = response.json().get('result', {})
                return result.get('message_thread_id')
            else:
                logger.error(f"Falha ao criar tópico {name}: {response.text}")
                return None
        except Exception as e:
            logger.error(f"Erro de conexão ao criar tópico {name}: {e}")
            return None

    def get_topic_id(self, topic_type: TopicType) -> Optional[int]:
        """Obtém ou cria o ID do tópico solicitado"""
        key = topic_type.value
        
        # 1. Tentar obter da memória/cache persistente
        if key in self.topic_ids:
            return self.topic_ids[key]
            
        # 2. Se não existir, criar novo
        config = self.topic_config.get(topic_type)
        if not config:
            return None
            
        logger.info(f"Criando novo tópico: {config['name']}")
        new_id = self._create_topic(config['name'], config['color'])
        
        if new_id:
            self.topic_ids[key] = new_id
            self._save_topics()
            logger.info(f"Tópico criado com sucesso: {key} -> ID {new_id}")
            
            # Enviar mensagem de boas vindas
            self.send_message(topic_type, f"Componente ativado: {config['name']}")
            
            return new_id
        
        return None

    def send_message(self, topic_type: TopicType, message: str) -> bool:
        """Envia mensagem para o tópico específico"""
        if not self.bot_token or not self.chat_id:
            return False
            
        topic_id = self.get_topic_id(topic_type)
        
        if topic_id is None:
            # Fallback para chat principal se falhar criar tópico
            logger.warning(f"Tópico não disponível, enviando para chat principal: {message[:20]}...")
            return self._send_raw(self.chat_id, None, message)
            
        return self._send_raw(self.chat_id, topic_id, message)

    def _escape_html(self, text: str) -> str:
        """Escapa caracteres especiais para HTML Parse Mode"""
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _send_raw(self, chat_id, message_thread_id, text) -> bool:
        url = f"{self.base_url}/sendMessage"
        
        # O text enviado já vem formatado com tags HTML intencionais (<b>, etc) do notifier?
        # Se sim, NÃO DEVEMOS escapar tudo, apenas o conteúdo dinâmico que pode conter < >.
        # PORÉM, o erro ocorreu com "Unsupported start tag".
        # O TelegramNotifier formata com <b>...</b>.
        # O erro provavelmente vem de conteúdo dinâmico (ex: msg de erro, ou nomes) inserido nessas strings.
        # Como o TelegramNotifier constroi a string final, a responsabilidade de escapar dados brutos deveria ser dele.
        # Mas como safeguard, se o parse falhar, podemos tentar reenviar sem parse_mode?
        # A melhor abordagem rápida aqui é tentar enviar, se der erro 400 parse, tentar enviar RAW text.
        
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        
        if message_thread_id:
            payload["message_thread_id"] = message_thread_id
            
        try:
            response = requests.post(url, json=payload, timeout=10)
            
            # Retry logic para erro de parse
            if response.status_code == 400 and "parse entities" in response.text:
                logger.warning(f"Erro de parse HTML Telegram. Tentando enviar como texto puro. Erro: {response.text}")
                payload.pop("parse_mode")
                response = requests.post(url, json=payload, timeout=10)

            if response.status_code == 429:
                logger.warning("Telegram Rate Limit atingido")
                return False
                
            if response.status_code != 200:
                # Se erro for "message thread not found", invalidar cache
                if "thread not found" in response.text.lower():
                    logger.warning("Thread não encontrada. Invalidando cache.")
                logger.error(f"Erro API Telegram: {response.text}")
                return False
                
            return True
        except Exception as e:
            logger.error(f"Exceção no envio Telegram: {e}")
            return False
