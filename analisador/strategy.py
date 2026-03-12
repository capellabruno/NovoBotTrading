from dataclasses import dataclass
from typing import Optional
import logging
    
@dataclass
class Signal:
    action: str  # "CALL", "PUT" or None
    confidence: float
    reason: str
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None

class Strategy:
    def __init__(self, config: dict):
        self.config = config

    def analyze(self, data: dict) -> Optional[Signal]:
        """
        Analisa os dados técnicos e retorna um sinal se houver setup.
        """
        logging.info("Analisando dados técnicos...")
        logging.info(data)
        if not data:
            return None

        # Desempacotar dados
        close = data.get('close')
        ema_20 = data.get('ema_20')
        ema_50 = data.get('ema_50')
        rsi = data.get('rsi')
        volume = data.get('volume')
        volume_ma = data.get('volume_ma')
        prev_close = data.get('prev_close')
        
        # Checagem de segurança se algum dado for None (NaN)
        if any(v is None for v in [close, ema_20, ema_50, rsi, volume, volume_ma]):
            return None

        # Definições de Tendência
        trend_up = ema_20 > ema_50 and close > ema_20
        trend_down = ema_20 < ema_50 and close < ema_20
        
        # Filtro de Volume (opcional, mas recomendado no doc)
        volume_ok = volume > volume_ma

        # Lógica de CALL (Tendência de Alta)
        # Pullback: Preço recuando perto da EMA20 ou apenas tendência forte?
        # A doc menciona: "Pullback até EMA 20, Candle de rejeição"
        # Simplificação para este código inicial: 
        # Se tendência de alta E RSI não sobrecomprado E (algum critério de pullback ou breakout)
        
        # CALL: tendência de alta, RSI não sobrecomprado (zona ampliada)
        # Aceita volume até 60% da média (sessão ASIAN naturalmente tem volume menor)
        if trend_up and 45 <= rsi <= 75:
            volume_sufficient = volume > volume_ma * 0.6
            if volume_sufficient:
                reason_parts = ["Tendência de Alta (EMA20 > EMA50)"]
                if 50 <= rsi <= 65:
                    reason_parts.append("RSI em zona ideal")
                elif rsi > 65:
                    reason_parts.append(f"RSI alto ({rsi:.0f}) mas tendência forte")
                else:
                    reason_parts.append(f"RSI ({rsi:.0f}) em pullback de tendência")
                if volume_ok:
                    reason_parts.append("volume acima da média")
                return Signal(
                    action="CALL",
                    confidence=0.7,
                    reason=", ".join(reason_parts) + "."
                )

        # PUT: tendência de baixa, RSI não sobrevendido (zona ampliada)
        if trend_down and 25 <= rsi <= 55:
            volume_sufficient = volume > volume_ma * 0.6
            if volume_sufficient:
                reason_parts = ["Tendência de Baixa (EMA20 < EMA50)"]
                if 35 <= rsi <= 50:
                    reason_parts.append("RSI em zona ideal")
                elif rsi < 35:
                    reason_parts.append(f"RSI baixo ({rsi:.0f}) mas tendência forte")
                else:
                    reason_parts.append(f"RSI ({rsi:.0f}) em pullback de tendência")
                if volume_ok:
                    reason_parts.append("volume acima da média")
                return Signal(
                    action="PUT",
                    confidence=0.7,
                    reason=", ".join(reason_parts) + "."
                )

        return None
