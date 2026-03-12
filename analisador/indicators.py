import pandas as pd
import numpy as np
import ta

class TechnicalIndicators:
    @staticmethod
    def calculate_all(df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula EMA 20, EMA 50, RSI 14, ATR e Média de Volume para o DataFrame fornecido.
        Espera que o DataFrame tenha colunas: 'open', 'high', 'low', 'close', 'volume'.
        """
        df = df.copy()
        
        # EMAs
        df['ema_20'] = ta.trend.EMAIndicator(close=df['close'], window=20).ema_indicator()
        df['ema_50'] = ta.trend.EMAIndicator(close=df['close'], window=50).ema_indicator()
        
        # RSI
        df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
        
        # Volume MA
        df['volume_ma'] = df['volume'].rolling(window=20).mean()
        
        # ATR (Average True Range) para Stop Loss dinâmico
        df['atr'] = ta.volatility.AverageTrueRange(
            high=df['high'],
            low=df['low'],
            close=df['close'],
            window=14
        ).average_true_range()
        
        # Detectar padrões de candles
        df = TechnicalIndicators.detect_candle_patterns(df)
        
        return df
    
    @staticmethod
    def detect_candle_patterns(df: pd.DataFrame) -> pd.DataFrame:
        """
        Detecta padrões de candles importantes para trading.
        Adiciona colunas: candle_pattern, candle_pattern_type
        """
        df = df.copy()
        df['candle_pattern'] = None
        df['candle_pattern_type'] = None
        
        for i in range(1, len(df)):
            open_price = df.iloc[i]['open']
            high = df.iloc[i]['high']
            low = df.iloc[i]['low']
            close = df.iloc[i]['close']
            
            prev_open = df.iloc[i-1]['open']
            prev_close = df.iloc[i-1]['close']
            
            body = abs(close - open_price)
            upper_shadow = high - max(open_price, close)
            lower_shadow = min(open_price, close) - low
            total_range = high - low
            
            if total_range == 0:
                continue
                
            body_ratio = body / total_range
            
            # Doji - Corpo muito pequeno (indecisão)
            if body_ratio < 0.1:
                df.iloc[i, df.columns.get_loc('candle_pattern')] = 'DOJI'
                df.iloc[i, df.columns.get_loc('candle_pattern_type')] = 'NEUTRAL'
                continue
            
            # Hammer - Sombra inferior longa, corpo pequeno no topo (reversão alta)
            if lower_shadow > body * 2 and upper_shadow < body * 0.5 and close > open_price:
                df.iloc[i, df.columns.get_loc('candle_pattern')] = 'HAMMER'
                df.iloc[i, df.columns.get_loc('candle_pattern_type')] = 'BULLISH'
                continue
            
            # Inverted Hammer - Sombra superior longa, corpo pequeno embaixo (reversão alta)
            if upper_shadow > body * 2 and lower_shadow < body * 0.5 and close > open_price:
                df.iloc[i, df.columns.get_loc('candle_pattern')] = 'INVERTED_HAMMER'
                df.iloc[i, df.columns.get_loc('candle_pattern_type')] = 'BULLISH'
                continue
            
            # Shooting Star - Sombra superior longa, corpo pequeno embaixo (reversão baixa)
            if upper_shadow > body * 2 and lower_shadow < body * 0.5 and close < open_price:
                df.iloc[i, df.columns.get_loc('candle_pattern')] = 'SHOOTING_STAR'
                df.iloc[i, df.columns.get_loc('candle_pattern_type')] = 'BEARISH'
                continue
            
            # Bullish Engulfing - Candle de alta engolindo o anterior
            if (close > open_price and  # Candle atual de alta
                prev_close < prev_open and  # Candle anterior de baixa
                open_price < prev_close and  # Abre abaixo do fechamento anterior
                close > prev_open):  # Fecha acima da abertura anterior
                df.iloc[i, df.columns.get_loc('candle_pattern')] = 'BULLISH_ENGULFING'
                df.iloc[i, df.columns.get_loc('candle_pattern_type')] = 'BULLISH'
                continue
            
            # Bearish Engulfing - Candle de baixa engolindo o anterior
            if (close < open_price and  # Candle atual de baixa
                prev_close > prev_open and  # Candle anterior de alta
                open_price > prev_close and  # Abre acima do fechamento anterior
                close < prev_open):  # Fecha abaixo da abertura anterior
                df.iloc[i, df.columns.get_loc('candle_pattern')] = 'BEARISH_ENGULFING'
                df.iloc[i, df.columns.get_loc('candle_pattern_type')] = 'BEARISH'
                continue
            
            # Pin Bar Bullish - Sombra inferior muito longa (rejeição de baixa)
            if lower_shadow > total_range * 0.6 and body_ratio < 0.3:
                df.iloc[i, df.columns.get_loc('candle_pattern')] = 'PIN_BAR_BULLISH'
                df.iloc[i, df.columns.get_loc('candle_pattern_type')] = 'BULLISH'
                continue
            
            # Pin Bar Bearish - Sombra superior muito longa (rejeição de alta)
            if upper_shadow > total_range * 0.6 and body_ratio < 0.3:
                df.iloc[i, df.columns.get_loc('candle_pattern')] = 'PIN_BAR_BEARISH'
                df.iloc[i, df.columns.get_loc('candle_pattern_type')] = 'BEARISH'
                continue
        
        return df

    @staticmethod
    def find_pivot_points(df: pd.DataFrame, left_bars: int = 5, right_bars: int = 5) -> tuple:
        """
        Identifica pivôs de alta (resistências) e pivôs de baixa (suportes) usando swing highs/lows.
        
        Args:
            df: DataFrame com colunas 'high' e 'low'
            left_bars: Número de barras à esquerda para confirmar pivô
            right_bars: Número de barras à direita para confirmar pivô
            
        Returns:
            tuple: (lista de suportes, lista de resistências)
        """
        highs = df['high'].values
        lows = df['low'].values
        
        supports = []
        resistances = []
        
        for i in range(left_bars, len(df) - right_bars):
            # Verifica Swing High (Resistência)
            is_swing_high = True
            for j in range(1, left_bars + 1):
                if highs[i] <= highs[i - j]:
                    is_swing_high = False
                    break
            if is_swing_high:
                for j in range(1, right_bars + 1):
                    if highs[i] <= highs[i + j]:
                        is_swing_high = False
                        break
            
            if is_swing_high:
                resistances.append(highs[i])
            
            # Verifica Swing Low (Suporte)
            is_swing_low = True
            for j in range(1, left_bars + 1):
                if lows[i] >= lows[i - j]:
                    is_swing_low = False
                    break
            if is_swing_low:
                for j in range(1, right_bars + 1):
                    if lows[i] >= lows[i + j]:
                        is_swing_low = False
                        break
            
            if is_swing_low:
                supports.append(lows[i])
        
        return supports, resistances

    @staticmethod
    def get_nearest_support_resistance(close: float, supports: list, resistances: list) -> dict:
        """
        Encontra o suporte e resistência mais próximos do preço atual.
        
        Args:
            close: Preço de fechamento atual
            supports: Lista de níveis de suporte
            resistances: Lista de níveis de resistência
            
        Returns:
            dict com suporte/resistência mais próximos e distâncias
        """
        # Filtra suportes abaixo do preço e resistências acima
        valid_supports = [s for s in supports if s < close]
        valid_resistances = [r for r in resistances if r > close]
        
        # Encontra os mais próximos
        nearest_support = max(valid_supports) if valid_supports else None
        nearest_resistance = min(valid_resistances) if valid_resistances else None
        
        # Calcula distâncias percentuais
        dist_to_support = ((close - nearest_support) / close * 100) if nearest_support else None
        dist_to_resistance = ((nearest_resistance - close) / close * 100) if nearest_resistance else None
        
        # Determina posição do preço
        # Threshold de 2% para cripto (1% era muito restritivo)
        NEAR_THRESHOLD = 2.0
        price_position = "MIDDLE"
        if dist_to_support is not None and dist_to_resistance is not None:
            if dist_to_support < dist_to_resistance and dist_to_support < NEAR_THRESHOLD:
                price_position = "NEAR_SUPPORT"
            elif dist_to_resistance < dist_to_support and dist_to_resistance < NEAR_THRESHOLD:
                price_position = "NEAR_RESISTANCE"
        elif dist_to_support is not None and dist_to_support < NEAR_THRESHOLD:
            price_position = "NEAR_SUPPORT"
        elif dist_to_resistance is not None and dist_to_resistance < NEAR_THRESHOLD:
            price_position = "NEAR_RESISTANCE"
        
        return {
            "support_level": nearest_support,
            "resistance_level": nearest_resistance,
            "distance_to_support_pct": round(dist_to_support, 2) if dist_to_support else None,
            "distance_to_resistance_pct": round(dist_to_resistance, 2) if dist_to_resistance else None,
            "price_position": price_position
        }

    @staticmethod
    def get_latest(df: pd.DataFrame) -> dict:
        """
        Retorna os indicadores da última vela FECHADA.
        A Bybit retorna o candle atual (aberto) como o mais recente após o sort —
        ele tem volume parcial e distorce todos os cálculos. Usamos iloc[-2] (penúltimo)
        que é o último candle completamente fechado.
        """
        if df.empty:
            return {}

        # Precisa de pelo menos 2 candles: o fechado ([-2]) e o atual aberto ([-1])
        if len(df) < 2:
            last_row = df.iloc[-1]
            prev_row = last_row
        else:
            last_row = df.iloc[-2]   # último candle fechado
            prev_row = df.iloc[-3] if len(df) > 2 else df.iloc[-2]
        
        # Calcula suporte e resistência (exclui o candle aberto = último)
        supports, resistances = TechnicalIndicators.find_pivot_points(df.iloc[:-1])
        sr_levels = TechnicalIndicators.get_nearest_support_resistance(
            last_row['close'], supports, resistances
        )
        
        # ATR como percentual do preço
        atr = last_row.get('atr', 0)
        atr_percent = (atr / last_row['close'] * 100) if last_row['close'] > 0 and atr else 0
        
        result = {
            "open": last_row['open'],
            "close": last_row['close'],
            "high": last_row['high'],
            "low": last_row['low'],
            "ema_20": last_row['ema_20'],
            "ema_50": last_row['ema_50'],
            "rsi": last_row['rsi'],
            "volume": last_row['volume'],
            "volume_ma": last_row['volume_ma'],
            "prev_close": prev_row['close'],
            "prev_ema_20": prev_row['ema_20'],
            # ATR
            "atr": round(atr, 6) if atr else None,
            "atr_percent": round(atr_percent, 2) if atr_percent else None,
            # Padrões de Candles
            "candle_pattern": last_row.get('candle_pattern'),
            "candle_pattern_type": last_row.get('candle_pattern_type')
        }
        
        # Adiciona dados de suporte/resistência
        result.update(sr_levels)
        
        return result
