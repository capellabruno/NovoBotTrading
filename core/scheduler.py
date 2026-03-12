import time
import logging
from datetime import datetime, timedelta
from .engine import TradingEngine

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, engine: TradingEngine):
        self.engine = engine
        self.last_run_day = None
        self._state = engine.state  # pode ser None

    def start(self):
        logger.debug("Scheduler iniciado.")

        while True:
            try:
                # --- Controles do Dashboard ---
                if self._state:
                    # Verificar pedido de pause
                    if self._state.check_and_clear_pause():
                        logger.info("Bot pausado.")

                    # Enquanto pausado, aguardar
                    while self._state and self._state.is_paused:
                        if self._state.check_and_clear_resume():
                            logger.info("Bot retomado.")
                            break
                        time.sleep(5)

                    # Recarregar config se solicitado
                    if self._state.check_and_clear_reload():
                        self._reload_config()

                # --- Ciclo de Trading ---
                self.engine.run_cycle()

                # --- Relatório Diário (23:00) ---
                now = datetime.now()
                if now.hour == 23 and now.minute >= 0 and now.day != self.last_run_day:
                    self.engine.send_daily_report()
                    self.last_run_day = now.day

                # --- Otimização Adaptativa ---
                if self.engine.config.get("adaptive", {}).get("enabled", False):
                    optimizer = self.engine.optimizer
                    last_run = optimizer.last_run_time
                    interval_hours = self.engine.config.get("adaptive", {}).get("update_interval_hours", 6)

                    if not last_run or (now - last_run).total_seconds() > interval_hours * 3600:
                        optimizer.optimize_all(self.engine.symbols)

                # --- Aguardar próximo ciclo de 5min ---
                t = time.time()
                sleep_time = 300 - (t % 300)

                next_cycle = (datetime.now() + timedelta(seconds=sleep_time)).isoformat()
                if self._state:
                    self._state.end_cycle(next_cycle_time=next_cycle)

                logger.debug(f"Próximo ciclo em {sleep_time:.0f}s.")
                time.sleep(sleep_time)

            except KeyboardInterrupt:
                logger.info("Parando Scheduler...")
                break
            except Exception as e:
                logger.error(f"Erro no loop principal: {e}")
                if self._state:
                    self._state.set_error(str(e))
                time.sleep(60)

    def _reload_config(self):
        """Recarrega config do YAML e atualiza o engine."""
        try:
            from config.config_loader import load_config
            new_config = load_config()
            self.engine.config = new_config
            if self._state:
                self._state.update_config(new_config)
            logger.info("Configuração recarregada com sucesso.")
        except Exception as e:
            logger.error(f"Erro ao recarregar config: {e}")
