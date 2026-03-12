import time
import requests
import json
import logging
from typing import Dict, Any, Optional
from .schemas import MarketDataInput, ValidationResult
from .prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)


class MCPServer:
    def __init__(self, config: Dict[str, Any], db_manager=None):
        self.config = config
        self.mode = config.get("mode", "gemini")

        # Gemini Config
        self.gemini_api_key = config.get("gemini_api_key")
        self.gemini_model = config.get("gemini_model", "gemini-2.5-flash")
        self._gemini_client = None

        # Groq Config (fallback por rate limit do Gemini)
        self.groq_api_key = config.get("groq_api_key")
        self.groq_model = config.get("groq_model", "llama-3.3-70b-versatile")

        # Ollama Config (último recurso local)
        self.ollama_url = config.get("ollama_url", "http://localhost:11434/api/generate")
        self.ollama_model = config.get("model", "deepseek-r1:32b")

        # DatabaseManager para persistir uso de tokens
        self.db = db_manager

    def set_db(self, db_manager):
        """Injeta o DatabaseManager após a inicialização."""
        self.db = db_manager

    def _get_gemini_client(self):
        if self._gemini_client is None and self.gemini_api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.gemini_api_key)
                self._gemini_client = genai.GenerativeModel(self.gemini_model)
                logger.info(f"Cliente Gemini inicializado com modelo: {self.gemini_model}")
            except ImportError:
                logger.error("Biblioteca google-generativeai não instalada.")
            except Exception as e:
                logger.error(f"Erro ao inicializar Gemini: {e}")
        return self._gemini_client

    def _record_usage(self, provider: str, model: str, symbol: str,
                      prompt_tokens: int, completion_tokens: int,
                      approved: bool, confidence: float, latency_ms: int):
        total = prompt_tokens + completion_tokens
        logger.debug(f"[{symbol}] {provider} | tokens={total} approved={approved} latency={latency_ms}ms")
        if self.db:
            try:
                self.db.save_llm_usage(
                    provider=provider,
                    model=model,
                    symbol=symbol,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    approved=approved,
                    confidence=confidence,
                    latency_ms=latency_ms,
                )
            except Exception as e:
                logger.warning(f"Falha ao persistir LLM usage: {e}")

    def validate_signal(self, data: MarketDataInput) -> ValidationResult:
        """
        Ordem de prioridade:
        1. Gemini  (principal)
        2. Groq    (fallback - rate limit do Gemini)
        3. Ollama  (último recurso local)
        4. Mock    (somente se TUDO falhar)
        """
        logger.debug(f"[{data.symbol}] MCP validando sinal (modo={self.mode})")

        if self.mode == "mock":
            return self._mock_validation(data)

        if self.gemini_api_key:
            result = self._gemini_validation(data)
            if result is not None:
                return result
            logger.warning(f"[{data.symbol}] Gemini falhou. Tentando Groq...")

        if self.groq_api_key:
            result = self._groq_validation(data)
            if result is not None:
                return result
            logger.warning(f"[{data.symbol}] Groq falhou. Tentando Ollama...")

        result = self._ollama_validation(data)
        if result is not None:
            return result
        logger.warning(f"[{data.symbol}] Ollama falhou. Usando mock como último recurso.")

        return self._mock_validation(data)

    def _mock_validation(self, data: MarketDataInput) -> ValidationResult:
        score = 0.0
        reasons = []

        trend_ok = False
        if data.signal_type == "CALL":
            if data.close_price > data.ema_20 > data.ema_50:
                score += 0.5
                reasons.append("Tendência de alta confirmada.")
                trend_ok = True
            if 50 <= data.rsi <= 70:
                score += 0.2
                reasons.append("RSI favorável para compra.")
        elif data.signal_type == "PUT":
            if data.close_price < data.ema_20 < data.ema_50:
                score += 0.5
                reasons.append("Tendência de baixa confirmada.")
                trend_ok = True
            if 30 <= data.rsi <= 50:
                score += 0.2
                reasons.append("RSI favorável para venda.")

        if not trend_ok:
            reasons.append("Tendência não confirma o sinal.")

        if data.volume_ratio > 1.0:
            score += 0.1
            reasons.append("Volume acima da média.")

        approved = score >= 0.7
        return ValidationResult(
            approved=approved,
            confidence=round(min(score, 0.99), 2),
            reasoning="; ".join(reasons) if reasons else "Critérios mínimos não atendidos.",
            suggested_action="EXECUTE" if approved else "WAIT"
        )

    def _build_prompt(self, data: MarketDataInput) -> str:
        def fmt(v, decimals=2, suffix=""):
            if v is None:
                return "N/A"
            try:
                return f"{v:.{decimals}f}{suffix}"
            except Exception:
                return str(v)

        return USER_PROMPT_TEMPLATE.format(
            symbol=data.symbol,
            timeframe=data.timeframe,
            close_price=fmt(data.close_price, 4),
            trend=data.trend or "N/A",
            signal_type=data.signal_type or "N/A",
            ema_20=fmt(data.ema_20, 4),
            ema_50=fmt(data.ema_50, 4),
            rsi=fmt(data.rsi, 2),
            volume_ratio=fmt(data.volume_ratio, 2),
            atr_percent=fmt(data.atr_percent, 2),
            support_level=fmt(data.support_level, 4),
            distance_to_support_pct=fmt(data.distance_to_support_pct, 2),
            resistance_level=fmt(data.resistance_level, 4),
            distance_to_resistance_pct=fmt(data.distance_to_resistance_pct, 2),
            price_position=data.price_position or "MIDDLE",
            candle_pattern=data.candle_pattern or "Nenhum",
            candle_pattern_type=data.candle_pattern_type or "N/A",
            current_session=data.current_session or "N/A",
            session_score=fmt(data.session_score, 2),
            quality_score=data.quality_score or 0,
            quality_grade=data.quality_grade or "N/A",
            entry_context_3m=data.entry_context_3m or "N/A",
        )

    def _gemini_validation(self, data: MarketDataInput) -> Optional[ValidationResult]:
        client = self._get_gemini_client()
        if not client:
            logger.warning("Cliente Gemini não disponível.")
            return None

        prompt = self._build_prompt(data)
        full_prompt = f"{SYSTEM_PROMPT}\n\n{prompt}"
        t0 = time.time()

        try:
            response = client.generate_content(
                full_prompt,
                generation_config={
                    "response_mime_type": "application/json",
                    "temperature": 0.1,
                }
            )
            latency_ms = int((time.time() - t0) * 1000)
            llm_text = response.text

            prompt_tokens = 0
            completion_tokens = 0
            try:
                usage = response.usage_metadata
                prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
                completion_tokens = getattr(usage, "candidates_token_count", 0) or 0
            except Exception:
                pass

            parsed = json.loads(llm_text)
            result_data = self._extract_validation_fields(parsed)
            result = ValidationResult(**result_data)

            self._record_usage(
                provider="gemini", model=self.gemini_model, symbol=data.symbol,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                approved=result.approved, confidence=result.confidence,
                latency_ms=latency_ms,
            )
            return result

        except json.JSONDecodeError as e:
            logger.error(f"Gemini: falha ao decodificar JSON: {e}")
            return None
        except Exception as e:
            err = str(e)
            if "429" in err or "quota" in err.lower() or "rate" in err.lower():
                logger.warning("Gemini: rate limit atingido. Passando para Groq.")
            else:
                logger.error(f"Gemini: erro na chamada API: {e}")
            return None

    def _groq_validation(self, data: MarketDataInput) -> Optional[ValidationResult]:
        if not self.groq_api_key:
            return None

        prompt = self._build_prompt(data)
        full_prompt = f"{SYSTEM_PROMPT}\n\n{prompt}"
        t0 = time.time()

        try:
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.groq_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.groq_model,
                    "messages": [{"role": "user", "content": full_prompt}],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                },
                timeout=60,
            )
            latency_ms = int((time.time() - t0) * 1000)
            response.raise_for_status()
            resp_json = response.json()

            usage = resp_json.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)

            llm_text = resp_json["choices"][0]["message"]["content"]
            parsed = json.loads(llm_text)
            result_data = self._extract_validation_fields(parsed)
            result = ValidationResult(**result_data)

            self._record_usage(
                provider="groq", model=self.groq_model, symbol=data.symbol,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                approved=result.approved, confidence=result.confidence,
                latency_ms=latency_ms,
            )
            return result

        except json.JSONDecodeError as e:
            logger.error(f"Groq: falha ao decodificar JSON: {e}")
            return None
        except Exception as e:
            err = str(e)
            if "429" in err or "rate" in err.lower():
                logger.warning("Groq: rate limit atingido.")
            else:
                logger.error(f"Groq: erro na chamada API: {e}")
            return None

    def _ollama_validation(self, data: MarketDataInput) -> Optional[ValidationResult]:
        prompt = self._build_prompt(data)
        payload = {
            "model": self.ollama_model,
            "prompt": f"{SYSTEM_PROMPT}\n\n{prompt}",
            "stream": False,
            "format": "json",
        }
        t0 = time.time()
        try:
            response = requests.post(self.ollama_url, json=payload, timeout=120)
            latency_ms = int((time.time() - t0) * 1000)
            response.raise_for_status()
            resp_json = response.json()
            llm_text = resp_json.get("response", "")

            prompt_tokens = resp_json.get("prompt_eval_count", 0) or 0
            completion_tokens = resp_json.get("eval_count", 0) or 0

            parsed = json.loads(llm_text)
            result_data = self._extract_validation_fields(parsed)
            result = ValidationResult(**result_data)

            self._record_usage(
                provider="ollama", model=self.ollama_model, symbol=data.symbol,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                approved=result.approved, confidence=result.confidence,
                latency_ms=latency_ms,
            )
            return result

        except json.JSONDecodeError:
            logger.error("Ollama: falha ao decodificar JSON da resposta.")
            return None
        except Exception as e:
            logger.error(f"Ollama: erro de conexão: {e}")
            return None

    def _extract_validation_fields(self, parsed: Dict) -> Dict[str, Any]:
        approved_keys        = ['approved', 'aprovado', 'approve', 'is_approved']
        confidence_keys      = ['confidence', 'confianca', 'confiança', 'score']
        reasoning_keys       = ['reasoning', 'raciocinio', 'raciocínio', 'reason', 'justificativa', 'analise', 'análise']
        suggested_action_keys = ['suggested_action', 'acao_sugerida', 'ação_sugerida', 'action', 'acao', 'ação']

        def find_value(data: Dict, keys: list, default=None):
            for key in keys:
                if key in data:
                    return data[key]
            for value in data.values():
                if isinstance(value, dict):
                    result = find_value(value, keys, None)
                    if result is not None:
                        return result
            return default

        approved         = find_value(parsed, approved_keys, False)
        confidence       = find_value(parsed, confidence_keys, 0.5)
        reasoning        = find_value(parsed, reasoning_keys, "Sem justificativa fornecida.")
        suggested_action = find_value(parsed, suggested_action_keys, "WAIT")

        if isinstance(approved, str):
            approved = approved.lower() in ['true', 'sim', 'yes', '1', 'aprovado']

        if isinstance(confidence, str):
            try:
                confidence = float(confidence.replace(',', '.'))
            except Exception:
                confidence = 0.5

        confidence = max(0.0, min(1.0, float(confidence)))

        action_upper = str(suggested_action).upper()
        if action_upper in ['EXECUTE', 'EXECUTAR', 'BUY', 'SELL', 'COMPRAR', 'VENDER']:
            suggested_action = 'EXECUTE'
        elif action_upper in ['ABORT', 'ABORTAR', 'CANCEL', 'CANCELAR']:
            suggested_action = 'ABORT'
        else:
            suggested_action = 'WAIT'

        return {
            'approved': approved,
            'confidence': round(confidence, 2),
            'reasoning': str(reasoning),
            'suggested_action': suggested_action,
        }
