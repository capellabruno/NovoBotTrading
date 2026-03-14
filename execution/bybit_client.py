from pybit.unified_trading import HTTP
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class BybitClient:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.client = None
        self.symbol = config.get("system", {}).get("symbol", "BTCUSDT")
        self._connect()

    def _connect(self):
        try:
            execution_config = self.config.get("execution", {})
            self.client = HTTP(
                testnet=execution_config.get("testnet", True),
                api_key=execution_config.get("api_key"),
                api_secret=execution_config.get("api_secret")
            )
            logger.info("Conectado à Bybit com sucesso.")
        except Exception as e:
            logger.error(f"Erro ao conectar na Bybit: {e}")
            # Em caso de falha crítica na conexão real, talvez devêssemos parar o bot?
            # Por enquanto, mantemos log.

    def fetch_candles(self, symbol: str, interval: int = 5, limit: int = 200) -> list:
        """
        Busca candles da Bybit para um simbolo especifico.
        Intervalo em minutos.
        """
        # Mapeamento de intervalo int para string da API se necessário.
        # Pybit Unified geralmente aceita "5", "15", "D", etc.
        interval_str = str(interval)
        
        try:
            client = self.client

            response = client.get_kline(
                category="linear",
                symbol=symbol,
                interval=interval_str,
                limit=limit
            )
            
            # Formato de retorno da V5: result -> list
            if response.get("retCode") == 0:
                return response.get("result", {}).get("list", [])
            else:
                logger.error(f"Erro ao buscar klines para {symbol}: {response}")
                return []
                
        except Exception as e:
            logger.error(f"Exceção ao buscar klines para {symbol}: {e}")
            return []

    def get_all_symbols(self) -> list:
        """
        Busca todos os símbolos USDT perpétuos ativos na Bybit (linear futures).
        Retorna lista de strings como ['BTCUSDT', 'ETHUSDT', ...].
        """
        try:
            all_symbols = []
            cursor = None

            while True:
                params = {
                    "category": "linear",
                    "status": "Trading",
                    "limit": 1000,
                }
                if cursor:
                    params["cursor"] = cursor

                response = self.client.get_instruments_info(**params)

                if response.get("retCode") != 0:
                    logger.error(f"Erro ao buscar lista de símbolos: {response}")
                    break

                result = response.get("result", {})
                instruments = result.get("list", [])

                for inst in instruments:
                    sym = inst.get("symbol", "")
                    # Apenas pares lineares USDT (perpetual)
                    if sym.endswith("USDT"):
                        all_symbols.append(sym)

                cursor = result.get("nextPageCursor")
                if not cursor:
                    break

            logger.info(f"Total de símbolos USDT encontrados na Bybit: {len(all_symbols)}")
            return all_symbols

        except Exception as e:
            logger.error(f"Exceção ao buscar lista de símbolos: {e}")
            return []

    def get_instrument_info(self, symbol: str) -> dict:
        """Busca informações do instrumento (qtyStep, tickSize, etc)"""
        try:
            # Cachear isso seria ideal em produção
            response = self.client.get_instruments_info(
                category="linear",
                symbol=symbol
            )
            if response["retCode"] == 0:
                list_info = response.get("result", {}).get("list", [])
                if list_info:
                    return list_info[0].get("lotSizeFilter", {})
            return {}
        except Exception:
            return {}

    def execute_order(self, symbol: str, action: str, amount: float, current_price: float, sl_percent: float, tp_percent: float):
        side = "Buy" if action.upper() == "CALL" else "Sell"
        
        # Calcular preços de SL e TP
        stop_loss = 0.0
        take_profit = 0.0
        
        if side == "Buy":
            stop_loss = current_price * (1 - sl_percent)
            take_profit = current_price * (1 + tp_percent)
        else: # Sell
            stop_loss = current_price * (1 + sl_percent)
            take_profit = current_price * (1 - tp_percent)

        stop_loss = round(stop_loss, 4)
        take_profit = round(take_profit, 4)
        
        # --- Cálculo Robusto de Quantidade ---
        qty_tokens = amount / current_price
        
        # Buscar precisão do ativo
        info = self.get_instrument_info(symbol)
        qty_step = float(info.get("qtyStep", "0.01")) # Fallback seguro 0.01
        min_qty = float(info.get("minOrderQty", "0.0"))

        # Arredondamento conforme qtyStep
        # Ex: step 0.1 -> round(10.55 / 0.1) * 0.1 = 10.5
        # Ex: step 1 -> round(10.55 / 1) * 1 = 11
        if qty_step > 0:
            qty_tokens = round(qty_tokens / qty_step) * qty_step
            # Fix floating point artifacts (e.g. 10.000000001)
            # Determinar casas decimais do step
            decimals = 0
            if "." in str(qty_step):
                decimals = len(str(qty_step).split(".")[1].rstrip("0"))
            
            qty_str = f"{qty_tokens:.{decimals}f}"
        else:
            qty_str = f"{qty_tokens:.2f}"

        # Validar minimo
        if float(qty_str) < min_qty:
             logger.warning(f"Ordem ignorada: Qtd calculada {qty_str} menor que minBybit {min_qty}")
             return None

        try:
            logger.info(f"Enviando ordem REAL em {symbol}: {side} | USDT: {amount} | Qty: {qty_str} | Price: {current_price}")
            
            response = self.client.place_order(
                category="linear",
                symbol=symbol,
                side=side,
                orderType="Market",
                qty=qty_str,
                timeInForce="GoodTillCancel",
                stopLoss=str(stop_loss),
                takeProfit=str(take_profit)
            )
            logger.info(f"Resposta ordem {symbol}: {response}")
            return response
            
        except Exception as e:
            # Fix Unicode Error in Windows Console
            error_msg = str(e).encode('ascii', 'ignore').decode('ascii')
            logger.error(f"Erro ao executar ordem em {symbol}: {error_msg}")
            return None

    def get_balance(self) -> float:
        """
        Retorna o saldo disponível em USDT (Wallet Balance).
        """
        try:
            # V5 Account Info
            response = self.client.get_wallet_balance(
                accountType="UNIFIED", # Ou CONTRACT, dependendo da conta. V5 padrão costuma ser UNIFIED ou CONTRACT.
                coin="USDT"
            )
            
            if response["retCode"] == 0:
                # Estrutura: result -> list -> 0 -> coin -> list -> 0 -> walletBalance
                # Pode variar conforme tipo de conta. Vamos assumir UNIFIED.
                # Se falhar, tentar buscar genericamente.
                account_list = response.get("result", {}).get("list", [])
                if account_list:
                    coins = account_list[0].get("coin", [])
                    for c in coins:
                        if c.get("coin") == "USDT":
                            return float(c.get("walletBalance", 0.0))
            return 0.0
        except Exception as e:
            logger.error(f"Erro ao buscar saldo: {e}")
            return 0.0

    def get_positions(self) -> list:
        """
        Retorna lista de posições abertas.
        """
        try:
            response = self.client.get_positions(
                category="linear",
                settleCoin="USDT"
            )
            
            if response["retCode"] == 0:
                # Filtrar apenas posições com size > 0
                all_positions = response.get("result", {}).get("list", [])
                active_positions = [p for p in all_positions if float(p.get("size", 0)) > 0]
                return active_positions
            
            return []
        except Exception as e:
            logger.error(f"Erro ao buscar posições: {e}")
            return []

    def close_position(self, symbol: str) -> bool:
        """
        Fecha completamente a posição aberta para o símbolo.
        Retorna True se sucesso.
        """
        try:
            # 1. Busca posição atual para saber tamanho e lado
            positions = self.get_positions()
            target_pos = next((p for p in positions if p["symbol"] == symbol), None)
            
            if not target_pos:
                logger.warning(f"Tentativa de fechar posição inexistente para {symbol}")
                return False
                
            size = float(target_pos["size"])
            side = target_pos["side"] # "Buy" ou "Sell"
            
            # Para fechar Buy, vendemos (Sell). Para fechar Sell, compramos (Buy).
            close_side = "Sell" if side == "Buy" else "Buy"
            
            logger.info(f"Fechando posição {symbol}: {close_side} {size} (ReduceOnly)")
            
            response = self.client.place_order(
                category="linear",
                symbol=symbol,
                side=close_side,
                orderType="Market",
                qty=str(size),
                timeInForce="GoodTillCancel",
                reduceOnly=True,
                closeOnTrigger=False
            )
            
            if response["retCode"] == 0:
                logger.info(f"Posição fechada com sucesso: {response}")
                return True
            else:
                logger.error(f"Falha ao fechar posição: {response}")
                return False
                
        except Exception as e:
            logger.error(f"Erro crítico ao fechar posição {symbol}: {e}")
            return False

    def get_closed_pnl(self, start_time: int = None) -> list:
        """
        Busca histórico de PnL fechado.
        :param start_time: Timestamp em ms. Se None, últimas 50 entradas.
        """
        try:
            params = {
                "category": "linear",
                "limit": 50
            }
            if start_time:
                params["startTime"] = start_time
                
            response = self.client.get_closed_pnl(**params)
            
            if response["retCode"] == 0:
                result = response.get("result", {})
                return result.get("list", [])
            
            logger.error(f"Erro ao buscar Closed PnL: {response}")
            return []
            
        except Exception as e:
            logger.error(f"Exceção ao buscar Closed PnL: {e}")
            return []
