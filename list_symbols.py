from pybit.unified_trading import HTTP
import yaml

def load_config():
    with open("config/settings.yaml", "r") as f:
        return yaml.safe_load(f)

def main():
    print("Fetching available symbols from Bybit (Linear USDT)...")
    
    # Usar public endpoint, não precisa de chaves para listar simbolos
    session = HTTP(testnet=False) 
    
    try:
        response = session.get_instruments_info(
            category="linear"
        )
        
        if response["retCode"] == 0:
            symbols = response["result"]["list"]
            # Filtrar por USDT
            usdt_pairs = [s["symbol"] for s in symbols if s["symbol"].endswith("USDT")]
            usdt_pairs.sort()
            
            print(f"Total Found: {len(usdt_pairs)}")
            print("-" * 30)
            # Imprimir em colunas ou lista simples
            for s in usdt_pairs:
                print(s)
                
        else:
            print(f"Error fetching symbols: {response}")
            
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    main()
