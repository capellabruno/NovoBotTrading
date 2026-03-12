import unittest
import pandas as pd
import numpy as np
from analisador.indicators import TechnicalIndicators
from analisador.strategy import Strategy, Signal

class TestAnalyzer(unittest.TestCase):
    def setUp(self):
        # Criar dados fake
        dates = pd.date_range(start='2023-01-01', periods=100, freq='5T')
        self.df = pd.DataFrame({
            'timestamp': dates,
            'open': np.linspace(100, 200, 100),
            'high': np.linspace(105, 205, 100),
            'low': np.linspace(95, 195, 100),
            'close': np.linspace(100, 200, 100), # Tendência de alta perfeita
            'volume': np.random.randint(100, 1000, 100)
        })

    def test_indicators_calculation(self):
        df_calc = TechnicalIndicators.calculate_all(self.df)
        
        self.assertIn('ema_20', df_calc.columns)
        self.assertIn('ema_50', df_calc.columns)
        self.assertIn('rsi', df_calc.columns)
        self.assertIn('volume_ma', df_calc.columns)
        
        # Verificar se não tem NaN nas últimas linhas (deve ter no começo pelo window)
        self.assertFalse(np.isnan(df_calc.iloc[-1]['ema_50']))

    def test_strategy_trend_up(self):
        # Forçar cenário de alta
        # RSI 60
        data = {
            "close": 110.0,
            "ema_20": 105.0,
            "ema_50": 100.0, # Alta
            "rsi": 60.0,
            "volume": 200.0,
            "volume_ma": 100.0,
            "prev_close": 109.0
        }
        
        strategy = Strategy({})
        signal = strategy.analyze(data)
        
        self.assertIsNotNone(signal)
        self.assertEqual(signal.action, "CALL")
        
    def test_strategy_trend_down(self):
        # Forçar cenário de baixa
        data = {
            "close": 90.0,
            "ema_20": 95.0,
            "ema_50": 100.0, # Baixa
            "rsi": 40.0,
            "volume": 200.0,
            "volume_ma": 100.0,
            "prev_close": 91.0
        }
        
        strategy = Strategy({})
        signal = strategy.analyze(data)
        
        self.assertIsNotNone(signal)
        self.assertEqual(signal.action, "PUT")

    def test_strategy_no_signal(self):
        # Tendência de alta mas RSI estourado (80) -> Sem sinal, pois estratégia pede RSI <= 70
        data = {
            "close": 110.0,
            "ema_20": 105.0,
            "ema_50": 100.0, 
            "rsi": 80.0, # Sobrecompra excessiva
            "volume": 200.0,
            "volume_ma": 100.0,
            "prev_close": 109.0
        }
        
        strategy = Strategy({})
        signal = strategy.analyze(data)
        self.assertIsNone(signal) # Espera-se None pois RSI > 70

if __name__ == '__main__':
    unittest.main()
