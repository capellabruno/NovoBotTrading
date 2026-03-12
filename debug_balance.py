import logging
import yaml
import os
from pybit.unified_trading import HTTP

# Configurar logs
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.FileHandler("debug_balance.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("DebugBalance")

def load_config(path: str = "config/settings.yaml"):
    with open(path, 'r') as f:
        return yaml.safe_load(f)

def debug_balance():
    logger.info("--- Iniciando Debug de Saldo Bybit ---")
    config = load_config()
    exec_conf = config.get("execution", {})
    
    api_key = exec_conf.get("api_key")
    api_secret = exec_conf.get("api_secret")
    testnet = exec_conf.get("testnet", True)
    
    logger.info(f"Testnet: {testnet}")
    # Pass 1: TestNet
    logger.info("--- TENTATIVA 1: TESTNET ---")
    try_connect(api_key, api_secret, True)
    
    # Pass 2: MainNet
    logger.info("\n--- TENTATIVA 2: MAINNET (PRODUÇÃO) ---")
    try_connect(api_key, api_secret, False)

def try_connect(api_key, api_secret, testnet):
    client = HTTP(
        testnet=testnet,
        api_key=api_key,
        api_secret=api_secret
    )
    
    account_types = ["UNIFIED", "CONTRACT", "SPOT"]
    
    for acc_type in account_types:
        try:
            logger.info(f"Testando {acc_type} (Testnet={testnet})...")
            response = client.get_wallet_balance(
                accountType=acc_type,
                coin="USDT"
            )
            
            if response.get("retCode") == 0:
                result = response.get("result", {})
                account_list = result.get("list", [])
                if account_list:
                    coins = account_list[0].get("coin", [])
                    for c in coins:
                        if c.get("coin") == "USDT":
                            balance = c.get("walletBalance")
                            logger.info(f"✅ SUCESSO! SALDO ENCONTRADO EM {'TESTNET' if testnet else 'MAINNET'} ({acc_type}): {balance} USDT")
                            return
            else:
                logger.info(f"Falha API: {response.get('retMsg')} (Code: {response.get('retCode')})")
                
        except Exception as e:
            logger.error(f"Erro de conexão/auth: {e}")

if __name__ == "__main__":
    debug_balance()
