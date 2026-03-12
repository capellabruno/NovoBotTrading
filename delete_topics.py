import logging
import requests
import sys
import yaml
import os
import time

# Configurar logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("TopicCleaner")

def load_config(path: str = "config/settings.yaml"):
    if not os.path.exists(path):
        logger.error(f"Arquivo de configuração não encontrado: {path}")
        sys.exit(1)
    with open(path, 'r') as f:
        return yaml.safe_load(f)

def delete_topics():
    logger.info("--- Iniciando Limpeza de Tópicos ---")
    config = load_config()
    
    token = config['signals']['telegram_token']
    chat_id = config['signals']['telegram_chat_id']
    base_url = f"https://api.telegram.org/bot{token}"
    
    logger.info(f"Chat ID: {chat_id}")
    
    # Range de tentativa: 1 até 200 (ajuste conforme a "idade" do grupo)
    # Se o grupo for muito antigo ou tiver muitas mensagens, isso pode demorar.
    start_id = 1
    end_id = 200
    
    deleted_count = 0
    
    logger.info(f"Tentando deletar tópicos na faixa {start_id} a {end_id}...")
    
    with requests.Session() as session:
        for msg_id in range(start_id, end_id + 1):
            try:
                # Tentar apagar o tópico (deleteForumTopic)
                # Nota: esconder o tópico (closeForumTopic) não o apaga completamente, 
                # mas deleteForumTopic apaga o tópico e mensagens.
                url = f"{base_url}/deleteForumTopic"
                payload = {"chat_id": chat_id, "message_thread_id": msg_id}
                
                response = session.post(url, json=payload, timeout=2)
                
                if response.status_code == 200 and response.json().get("ok"):
                    logger.info(f"✅ Tópico {msg_id} deletado com sucesso.")
                    deleted_count += 1
                elif response.status_code == 429:
                    retry_after = response.json().get("parameters", {}).get("retry_after", 5)
                    logger.warning(f"Rate limit atingido. Aguardando {retry_after}s...")
                    time.sleep(retry_after)
                # Ignorar erros 400 (tópico não existe)
                
                # Pequeno delay para evitar rate limit agressivo
                if msg_id % 10 == 0:
                    time.sleep(0.2)
                    print(f"Progresso: {msg_id}/{end_id}", end="\r")
                    
            except Exception as e:
                logger.error(f"Erro ao tentar deletar {msg_id}: {e}")
                
    logger.info(f"\n--- Limpeza Concluída. Total removidos: {deleted_count} ---")
    
    # Limpar arquivo de cache local
    cache_path = "data/telegram_topics.json"
    if os.path.exists(cache_path):
        os.remove(cache_path)
        logger.info("🗑️ Cache local (data/telegram_topics.json) removido.")

if __name__ == "__main__":
    delete_topics()
