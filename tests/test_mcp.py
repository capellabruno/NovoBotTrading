import unittest
from mcp_local.server import MCPServer
from mcp_local.schemas import MarketDataInput

class TestMCP(unittest.TestCase):
    def setUp(self):
        self.config = {"mode": "mock"}
        self.server = MCPServer(self.config)

    def test_validate_call_approve(self):
        # Setup perfeito para CALL
        data = MarketDataInput(
            symbol="BTCUSDT",
            timeframe="5m",
            close_price=110.0,
            ema_20=105.0,
            ema_50=100.0,
            rsi=60.0,
            volume_ratio=1.5,
            trend="UP",
            signal_type="CALL"
        )
        
        result = self.server.validate_signal(data)
        self.assertTrue(result.approved)
        self.assertGreaterEqual(result.confidence, 0.7)

    def test_validate_rejection_conflict(self):
        # Sinal CALL em tendência de BAIXA (erro da estratégia, ou MCP pegando incongruencia)
        # Nota: Estrategia deterministica ja filtra isso, mas se chegasse no MCP...
        
        data = MarketDataInput(
            symbol="BTCUSDT",
            timeframe="5m",
            close_price=90.0,
            ema_20=95.0,
            ema_50=100.0, # Baixa
            rsi=60.0,
            volume_ratio=1.5,
            trend="DOWN",
            signal_type="CALL" # Incongruente
        )
        
        # O mock MCP verifica tendencia compatível
        result = self.server.validate_signal(data)
        self.assertFalse(result.approved)

if __name__ == '__main__':
    unittest.main()
