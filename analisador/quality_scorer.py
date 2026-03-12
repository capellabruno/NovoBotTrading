"""
Módulo de Score de Qualidade do Setup.
Avalia a qualidade geral de um setup de trading com pontuação de 0-100.
"""
from typing import Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class QualityResult:
    """Resultado da avaliação de qualidade."""
    score: int                    # Pontuação total (0-100)
    grade: str                    # Nota: A, B, C, D, F
    breakdown: Dict[str, int]     # Pontuação por critério
    is_tradeable: bool            # Se atende ao mínimo para operar
    warnings: list                # Alertas sobre o setup


class QualityScorer:
    """
    Sistema de pontuação para qualidade do setup.
    Score mínimo para entrada: 70/100
    """
    
    # Pesos de cada critério
    WEIGHTS = {
        "trend_aligned": 25,           # Tendência confirmada (EMA20 > EMA50 para CALL)
        "rsi_favorable": 15,           # RSI em zona ideal
        "volume_above_avg": 15,        # Volume acima da média
        "near_support_resistance": 15, # Perto de nível chave favorável
        "candle_pattern": 15,          # Padrão de candle confirmando
        "session_quality": 10,         # Sessão de alta liquidez
        "atr_favorable": 5,            # Volatilidade adequada
    }
    
    # Score mínimo para permitir entrada
    MIN_SCORE = 70
    
    @classmethod
    def calculate_score(cls, data: Dict[str, Any], signal_type: str) -> QualityResult:
        """
        Calcula o score de qualidade do setup.
        
        Args:
            data: Dicionário com métricas do indicador (output de get_latest())
            signal_type: "CALL" ou "PUT"
            
        Returns:
            QualityResult com pontuação detalhada
        """
        breakdown = {}
        warnings = []
        
        # 1. Tendência Alinhada (25 pontos)
        breakdown["trend_aligned"] = cls._score_trend(data, signal_type, warnings)
        
        # 2. RSI Favorável (15 pontos)
        breakdown["rsi_favorable"] = cls._score_rsi(data, signal_type, warnings)
        
        # 3. Volume Acima da Média (15 pontos)
        breakdown["volume_above_avg"] = cls._score_volume(data, warnings)
        
        # 4. Próximo a Suporte/Resistência (15 pontos)
        breakdown["near_support_resistance"] = cls._score_sr_levels(data, signal_type, warnings)
        
        # 5. Padrão de Candle (15 pontos)
        breakdown["candle_pattern"] = cls._score_candle_pattern(data, signal_type, warnings)
        
        # 6. Qualidade da Sessão (10 pontos)
        breakdown["session_quality"] = cls._score_session(data, warnings)
        
        # 7. ATR/Volatilidade (5 pontos)
        breakdown["atr_favorable"] = cls._score_atr(data, warnings)
        
        # Calcular total
        total_score = sum(breakdown.values())
        grade = cls._calculate_grade(total_score)
        is_tradeable = total_score >= cls.MIN_SCORE
        
        return QualityResult(
            score=total_score,
            grade=grade,
            breakdown=breakdown,
            is_tradeable=is_tradeable,
            warnings=warnings
        )
    
    @classmethod
    def _score_trend(cls, data: Dict, signal_type: str, warnings: list) -> int:
        """Avalia alinhamento da tendência."""
        max_points = cls.WEIGHTS["trend_aligned"]
        
        ema_20 = data.get("ema_20")
        ema_50 = data.get("ema_50")
        close = data.get("close")
        
        if not all([ema_20, ema_50, close]):
            warnings.append("Dados de EMA incompletos")
            return 0
        
        if signal_type == "CALL":
            # Para CALL: Preço > EMA20 > EMA50
            if close > ema_20 > ema_50:
                return max_points
            elif ema_20 > ema_50:  # Tendência de alta, mas preço abaixo
                return max_points // 2
            else:
                warnings.append("Tendência não confirma CALL")
                return 0
        else:  # PUT
            # Para PUT: Preço < EMA20 < EMA50
            if close < ema_20 < ema_50:
                return max_points
            elif ema_20 < ema_50:  # Tendência de baixa, mas preço acima
                return max_points // 2
            else:
                warnings.append("Tendência não confirma PUT")
                return 0
    
    @classmethod
    def _score_rsi(cls, data: Dict, signal_type: str, warnings: list) -> int:
        """Avalia RSI."""
        max_points = cls.WEIGHTS["rsi_favorable"]
        
        rsi = data.get("rsi")
        if rsi is None:
            warnings.append("RSI não disponível")
            return 0
        
        if signal_type == "CALL":
            if 50 <= rsi <= 65:
                return max_points           # Ideal: momentum sem sobrecompra
            elif 45 <= rsi <= 75:
                return max_points * 2 // 3  # Aceitável
            elif rsi > 80:
                warnings.append(f"RSI em sobrecompra extrema ({rsi:.1f})")
                return 0
            else:
                return max_points // 3      # Fraco mas não bloqueante
        else:  # PUT
            if 35 <= rsi <= 50:
                return max_points           # Ideal
            elif 25 <= rsi <= 55:
                return max_points * 2 // 3  # Aceitável
            elif rsi < 20:
                warnings.append(f"RSI em sobrevenda extrema ({rsi:.1f})")
                return 0
            else:
                return max_points // 3
    
    @classmethod
    def _score_volume(cls, data: Dict, warnings: list) -> int:
        """Avalia volume."""
        max_points = cls.WEIGHTS["volume_above_avg"]
        
        volume = data.get("volume")
        volume_ma = data.get("volume_ma")
        
        if not volume or not volume_ma or volume_ma == 0:
            return max_points // 2  # Neutro
        
        volume_ratio = volume / volume_ma
        
        if volume_ratio >= 1.5:
            return max_points
        elif volume_ratio >= 1.0:
            return max_points * 2 // 3
        elif volume_ratio >= 0.8:
            return max_points // 3
        else:
            warnings.append(f"Volume baixo ({volume_ratio:.2f}x média)")
            return 0
    
    @classmethod
    def _score_sr_levels(cls, data: Dict, signal_type: str, warnings: list) -> int:
        """Avalia proximidade a suporte/resistência."""
        max_points = cls.WEIGHTS["near_support_resistance"]
        
        price_position = data.get("price_position")
        dist_support = data.get("distance_to_support_pct")
        dist_resistance = data.get("distance_to_resistance_pct")
        
        if price_position is None:
            return max_points // 2  # Neutro
        
        if signal_type == "CALL":
            # Para CALL, perto de suporte é bom
            if price_position == "NEAR_SUPPORT":
                return max_points
            elif price_position == "NEAR_RESISTANCE":
                warnings.append("CALL próximo à resistência - risco alto")
                return 0
            else:
                return max_points // 2
        else:  # PUT
            # Para PUT, perto de resistência é bom
            if price_position == "NEAR_RESISTANCE":
                return max_points
            elif price_position == "NEAR_SUPPORT":
                warnings.append("PUT próximo ao suporte - risco alto")
                return 0
            else:
                return max_points // 2
    
    @classmethod
    def _score_candle_pattern(cls, data: Dict, signal_type: str, warnings: list) -> int:
        """Avalia padrão de candle."""
        max_points = cls.WEIGHTS["candle_pattern"]
        
        pattern = data.get("candle_pattern")
        pattern_type = data.get("candle_pattern_type")
        
        if not pattern:
            return max_points // 3  # Sem padrão = neutro baixo
        
        if signal_type == "CALL":
            if pattern_type == "BULLISH":
                return max_points
            elif pattern_type == "NEUTRAL":
                warnings.append(f"Padrão {pattern} indica indecisão")
                return max_points // 3
            else:  # BEARISH
                warnings.append(f"Padrão {pattern} contrário ao sinal CALL")
                return 0
        else:  # PUT
            if pattern_type == "BEARISH":
                return max_points
            elif pattern_type == "NEUTRAL":
                warnings.append(f"Padrão {pattern} indica indecisão")
                return max_points // 3
            else:  # BULLISH
                warnings.append(f"Padrão {pattern} contrário ao sinal PUT")
                return 0
    
    @classmethod
    def _score_session(cls, data: Dict, warnings: list) -> int:
        """Avalia qualidade da sessão."""
        max_points = cls.WEIGHTS["session_quality"]
        
        session_score = data.get("session_score")
        
        if session_score is None:
            return max_points // 2  # Neutro
        
        if session_score >= 0.9:
            return max_points
        elif session_score >= 0.8:
            return max_points * 4 // 5
        elif session_score >= 0.6:
            return max_points // 2
        else:
            warnings.append("Sessão de baixa liquidez")
            return max_points // 4
    
    @classmethod
    def _score_atr(cls, data: Dict, warnings: list) -> int:
        """Avalia ATR/Volatilidade."""
        max_points = cls.WEIGHTS["atr_favorable"]
        
        atr_percent = data.get("atr_percent")
        
        if atr_percent is None:
            return max_points // 2
        
        # ATR ideal: 0.5% a 2.5% do preço
        if 0.5 <= atr_percent <= 2.5:
            return max_points
        elif 0.3 <= atr_percent <= 3.5:
            return max_points * 2 // 3
        elif atr_percent > 4.0:
            warnings.append(f"Volatilidade muito alta (ATR {atr_percent:.1f}%)")
            return 0
        else:
            warnings.append(f"Volatilidade muito baixa (ATR {atr_percent:.1f}%)")
            return max_points // 3
    
    @staticmethod
    def _calculate_grade(score: int) -> str:
        """Converte score em nota."""
        if score >= 90:
            return "A"
        elif score >= 80:
            return "B"
        elif score >= 70:
            return "C"
        elif score >= 60:
            return "D"
        else:
            return "F"
