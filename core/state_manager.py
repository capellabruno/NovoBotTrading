"""
StateManager - Singleton thread-safe que mantém o estado em tempo real do bot.
O engine escreve aqui a cada ciclo; o dashboard lê via state_api.py.
"""
import threading
import queue
from datetime import datetime
from typing import Dict, List, Optional, Any
import copy


class StateManager:
    _instance: Optional["StateManager"] = None
    _class_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "StateManager":
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._lock = threading.RLock()

        # --- Estado do Sistema ---
        self.is_running: bool = False
        self.is_paused: bool = False
        self.dry_run: bool = True
        self.cycle_number: int = 0
        self.cycle_status: str = "IDLE"   # IDLE / RUNNING / ERROR
        self.last_cycle_time: Optional[str] = None
        self.next_cycle_time: Optional[str] = None
        self.last_error: Optional[str] = None
        self.uptime_start: Optional[str] = None

        # --- Dados de Mercado ---
        self.account_balance: float = 0.0
        self.open_positions: Dict[str, dict] = {}   # symbol -> dados da posição
        self.last_prices: Dict[str, float] = {}     # symbol -> último preço
        self.last_signals: Dict[str, dict] = {}     # symbol -> resultado da análise

        # --- Config (cache) ---
        self.config: Dict[str, Any] = {}

        # --- Controles (dashboard -> engine) ---
        self.pause_requested: bool = False
        self.resume_requested: bool = False
        self.reload_config_requested: bool = False

        # --- Fila de eventos para o log viewer ---
        self.event_queue: queue.Queue = queue.Queue(maxsize=500)
        self._recent_events: List[dict] = []
        self._events_lock = threading.Lock()

    # -------------------------------------------------------------------------
    # Atualizações pelo Engine
    # -------------------------------------------------------------------------

    def set_running(self, dry_run: bool = True):
        with self._lock:
            self.is_running = True
            self.dry_run = dry_run
            self.uptime_start = datetime.utcnow().isoformat()

    def start_cycle(self, cycle_number: int):
        with self._lock:
            self.cycle_number = cycle_number
            self.cycle_status = "RUNNING"
            self.last_cycle_time = datetime.utcnow().isoformat()

    def end_cycle(self, next_cycle_time: Optional[str] = None):
        with self._lock:
            self.cycle_status = "IDLE"
            if next_cycle_time:
                self.next_cycle_time = next_cycle_time

    def set_error(self, error: str):
        with self._lock:
            self.cycle_status = "ERROR"
            self.last_error = error

    def update_balance(self, balance: float):
        with self._lock:
            self.account_balance = balance

    def update_positions(self, positions: Dict[str, dict]):
        with self._lock:
            self.open_positions = copy.deepcopy(positions)

    def update_price(self, symbol: str, price: float):
        with self._lock:
            self.last_prices[symbol] = price

    def update_signal(self, symbol: str, signal_data: dict):
        with self._lock:
            self.last_signals[symbol] = copy.deepcopy(signal_data)

    def update_config(self, config: dict):
        with self._lock:
            self.config = copy.deepcopy(config)

    # -------------------------------------------------------------------------
    # Controles pelo Dashboard
    # -------------------------------------------------------------------------

    def request_pause(self):
        with self._lock:
            self.pause_requested = True
            self.resume_requested = False

    def request_resume(self):
        with self._lock:
            self.resume_requested = True
            self.pause_requested = False

    def request_reload_config(self):
        with self._lock:
            self.reload_config_requested = True

    def check_and_clear_pause(self) -> bool:
        with self._lock:
            if self.pause_requested:
                self.pause_requested = False
                self.is_paused = True
                return True
            return False

    def check_and_clear_resume(self) -> bool:
        with self._lock:
            if self.resume_requested:
                self.resume_requested = False
                self.is_paused = False
                return True
            return False

    def check_and_clear_reload(self) -> bool:
        with self._lock:
            if self.reload_config_requested:
                self.reload_config_requested = False
                return True
            return False

    # -------------------------------------------------------------------------
    # Log de Eventos
    # -------------------------------------------------------------------------

    def add_event(self, level: str, source: str, message: str):
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "source": source,
            "message": message,
        }
        # Adiciona na fila (descarta se cheia)
        try:
            self.event_queue.put_nowait(event)
        except queue.Full:
            pass

        # Mantém lista circular dos últimos 500 eventos
        with self._events_lock:
            self._recent_events.append(event)
            if len(self._recent_events) > 500:
                self._recent_events.pop(0)

    def get_recent_events(self, n: int = 100) -> List[dict]:
        with self._events_lock:
            return list(self._recent_events[-n:])

    # -------------------------------------------------------------------------
    # Snapshot completo (para o state_api)
    # -------------------------------------------------------------------------

    def get_snapshot(self) -> dict:
        with self._lock:
            return {
                "is_running": self.is_running,
                "is_paused": self.is_paused,
                "dry_run": self.dry_run,
                "cycle_number": self.cycle_number,
                "cycle_status": self.cycle_status,
                "last_cycle_time": self.last_cycle_time,
                "next_cycle_time": self.next_cycle_time,
                "last_error": self.last_error,
                "uptime_start": self.uptime_start,
                "account_balance": self.account_balance,
                "open_positions": copy.deepcopy(self.open_positions),
                "last_prices": copy.deepcopy(self.last_prices),
                "last_signals": copy.deepcopy(self.last_signals),
                "recent_events": self.get_recent_events(50),
            }
