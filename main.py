"""
main.py - Ponto de entrada legacy (mantido para compatibilidade).
Para a versão completa com dashboard, use: python launcher.py
"""
import logging
import sys
import io
from core.engine import TradingEngine
from core.scheduler import Scheduler
from config.config_loader import load_config

# Configurar stdout para UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("trading_system.log", encoding='utf-8')
    ]
)

logger = logging.getLogger("Main")


def main():
    logger.info("Inicializando Sistema de Trading (modo legado - sem dashboard).")
    logger.info("Para usar o dashboard, execute: python launcher.py")

    config = load_config()
    logger.info(f"Configuração carregada. Modo: {'DRY RUN' if config['system']['dry_run'] else 'LIVE'}")

    engine = TradingEngine(config)
    scheduler = Scheduler(engine)
    scheduler.start()


if __name__ == "__main__":
    main()
