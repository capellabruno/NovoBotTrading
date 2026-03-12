"""
Handler de logging customizado que alimenta o StateManager e o DatabaseManager.
"""
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state_manager import StateManager
    from database.manager import DatabaseManager


class StateManagerHandler(logging.Handler):
    """
    Envia todos os registros de log para o StateManager (para o dashboard)
    e opcionalmente para o DatabaseManager (persistência).
    """
    def __init__(self, state_manager: "StateManager",
                 db_manager: "DatabaseManager" = None,
                 level=logging.INFO):
        super().__init__(level)
        self.state = state_manager
        self.db = db_manager

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            self.state.add_event(record.levelname, record.name, msg)

            # Só persistir WARNING+ no DB para não sobrecarregar
            if self.db and record.levelno >= logging.WARNING:
                self.db.log_event(record.levelname, record.name, msg[:2000])
        except Exception:
            self.handleError(record)
