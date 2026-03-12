"""
Módulo de Filtro de Sessões de Mercado.
Avalia a qualidade do horário atual para trading baseado em liquidez e volatilidade.
"""
from datetime import datetime, timezone
from typing import Dict, Tuple

class SessionFilter:
    """
    Filtro de sessões de mercado para cripto.
    Baseado nos horários de maior liquidez e volatilidade.
    """
    
    # Sessões em horário UTC
    SESSIONS: Dict[str, Tuple[int, int]] = {
        "ASIAN": (0, 8),         # 00:00-08:00 UTC - Menor volatilidade
        "LONDON": (8, 16),       # 08:00-16:00 UTC - Alta volatilidade
        "NEW_YORK": (13, 21),    # 13:00-21:00 UTC - Maior volume
        "OVERLAP": (13, 16),     # 13:00-16:00 UTC - London + NY (máxima liquidez)
        "OFF_HOURS": (21, 24),   # 21:00-00:00 UTC - Baixa liquidez
    }
    
    # Scores de qualidade por sessão (0.0 a 1.0)
    SESSION_SCORES: Dict[str, float] = {
        "OVERLAP": 1.0,      # Melhor momento
        "NEW_YORK": 0.9,     # Muito bom
        "LONDON": 0.85,      # Muito bom
        "ASIAN": 0.6,        # Moderado
        "OFF_HOURS": 0.4,    # Baixa qualidade
        "UNKNOWN": 0.5,      # Fallback
    }
    
    @classmethod
    def get_current_session(cls, dt: datetime = None) -> str:
        """
        Retorna a sessão atual baseada no horário UTC.
        
        Args:
            dt: Datetime para verificar. Se None, usa hora atual.
            
        Returns:
            Nome da sessão: "OVERLAP", "NEW_YORK", "LONDON", "ASIAN", "OFF_HOURS"
        """
        if dt is None:
            dt = datetime.now(timezone.utc)
        
        # Converter para UTC se necessário
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
            
        hour = dt.hour
        
        # Verificar Overlap primeiro (prioridade)
        start, end = cls.SESSIONS["OVERLAP"]
        if start <= hour < end:
            return "OVERLAP"
        
        # Verificar outras sessões
        for session, (start, end) in cls.SESSIONS.items():
            if session == "OVERLAP":
                continue
            if start <= hour < end:
                return session
        
        return "UNKNOWN"
    
    @classmethod
    def get_session_score(cls, dt: datetime = None) -> float:
        """
        Retorna o score de qualidade da sessão atual (0.0 a 1.0).
        
        Args:
            dt: Datetime para verificar. Se None, usa hora atual.
            
        Returns:
            Score entre 0.0 e 1.0
        """
        session = cls.get_current_session(dt)
        return cls.SESSION_SCORES.get(session, 0.5)
    
    @classmethod
    def is_high_liquidity_session(cls, dt: datetime = None) -> bool:
        """
        Verifica se estamos em uma sessão de alta liquidez.
        
        Args:
            dt: Datetime para verificar. Se None, usa hora atual.
            
        Returns:
            True se sessão tem liquidez >= 0.8
        """
        return cls.get_session_score(dt) >= 0.8
    
    @classmethod
    def get_session_info(cls, dt: datetime = None) -> dict:
        """
        Retorna informações completas sobre a sessão atual.
        
        Args:
            dt: Datetime para verificar. Se None, usa hora atual.
            
        Returns:
            dict com session, score, is_high_liquidity, recommendation
        """
        session = cls.get_current_session(dt)
        score = cls.SESSION_SCORES.get(session, 0.5)
        is_high = score >= 0.8
        
        if score >= 0.9:
            recommendation = "IDEAL"
        elif score >= 0.8:
            recommendation = "GOOD"
        elif score >= 0.6:
            recommendation = "MODERATE"
        else:
            recommendation = "AVOID"
        
        return {
            "current_session": session,
            "session_score": round(score, 2),
            "is_high_liquidity": is_high,
            "recommendation": recommendation
        }


# Funções helper para uso direto
def get_current_session() -> str:
    """Retorna nome da sessão atual."""
    return SessionFilter.get_current_session()

def get_session_score() -> float:
    """Retorna score da sessão atual (0.0 a 1.0)."""
    return SessionFilter.get_session_score()

def is_good_time_to_trade() -> bool:
    """Retorna True se é um bom momento para operar."""
    return SessionFilter.is_high_liquidity_session()
