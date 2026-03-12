import requests
import yaml
import time

def load_config():
    try:
        with open("config/settings.yaml", "r") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print("Erro: config/settings.yaml não encontrado.")
        return None

def get_updates(token):
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        response = requests.get(url, timeout=10)
        return response.json()
    except Exception as e:
        print(f"Erro ao conectar com Telegram: {e}")
        return None

def main():
    config = load_config()
    if not config:
        return

    token = config.get("signals", {}).get("telegram_token")
    if not token or token == "YOUR_TELEGRAM_TOKEN":
        print("Erro: Token do Telegram não configurado em settings.yaml")
        return

    print("--- Buscando Chat IDs ---")
    print("1. Crie um grupo no Telegram.")
    print("2. Adicione o seu bot ao grupo.")
    print("3. Envie uma mensagem no grupo (ex: /start ou 'ola').")
    print("4. Aguarde abaixo...\n")

    while True:
        updates = get_updates(token)
        if updates and updates.get("ok"):
            results = updates.get("result", [])
            if not results:
                print("Nenhuma mensagem recebida ainda... (Tentando novamente em 3s)")
            else:
                print(f"\nEncontradas {len(results)} mensagens!\n")
                found_chats = set()
                
                for update in results:
                    msg = update.get("message", {}) or update.get("my_chat_member", {})
                    chat = msg.get("chat", {})
                    
                    chat_id = chat.get("id")
                    chat_type = chat.get("type")
                    title = chat.get("title", "Privado")
                    username = chat.get("username", "N/A")
                    
                    if chat_id and chat_id not in found_chats:
                        found_chats.add(chat_id)
                        print(f"📌 Chat Encontrado:")
                        print(f"   ID: {chat_id}")
                        print(f"   Tipo: {chat_type}")
                        print(f"   Título: {title}")
                        print(f"   Username: @{username}")
                        print("-" * 30)
                
                print("\nCopie o ID do grupo desejado e coloque no 'telegram_chat_id' do arquivo settings.yaml")
                break
        else:
            print("Erro ao buscar updates.")
        
        time.sleep(3)

if __name__ == "__main__":
    main()
