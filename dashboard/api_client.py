"""
Cliente HTTP para comunicar com a State API do engine.
"""
import requests
import logging

logger = logging.getLogger(__name__)

STATE_API_URL = "http://127.0.0.1:8502"
TIMEOUT = 5


def get_state() -> dict:
    try:
        r = requests.get(f"{STATE_API_URL}/state", timeout=TIMEOUT)
        return r.json()
    except Exception:
        return None


def get_config() -> dict:
    try:
        r = requests.get(f"{STATE_API_URL}/config", timeout=TIMEOUT)
        return r.json()
    except Exception:
        return {}


def send_pause():
    try:
        requests.post(f"{STATE_API_URL}/control/pause", timeout=TIMEOUT)
    except Exception:
        pass


def send_resume():
    try:
        requests.post(f"{STATE_API_URL}/control/resume", timeout=TIMEOUT)
    except Exception:
        pass


def update_config(data: dict) -> bool:
    try:
        r = requests.post(f"{STATE_API_URL}/config", json=data, timeout=TIMEOUT)
        return r.json().get("ok", False)
    except Exception:
        return False


def is_engine_online() -> bool:
    try:
        r = requests.get(f"{STATE_API_URL}/health", timeout=1)
        return r.status_code == 200
    except Exception:
        return False
