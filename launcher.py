"""
launcher.py - Ponto de entrada principal do NovoBotTrading v2
Inicia o engine de trading E o dashboard Streamlit simultaneamente.

Uso:
    python launcher.py              # Engine + Dashboard
    python launcher.py --engine     # Apenas Engine (sem dashboard)
    python launcher.py --dashboard  # Apenas Dashboard (sem engine)
"""
import argparse
import logging
import subprocess
import sys
import io
import os
import signal
import threading
import time
from pathlib import Path

# Garantir encoding UTF-8 no Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Adicionar raiz ao path
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


def setup_logging(db_manager=None, state_manager=None) -> logging.Logger:
    """Configura o sistema de logging com o handler customizado."""
    fmt = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("trading_system.log", encoding='utf-8'),
    ]

    if state_manager:
        from core.logging_handler import StateManagerHandler
        state_handler = StateManagerHandler(state_manager, db_manager, level=logging.INFO)
        state_handler.setFormatter(fmt)
        handlers.append(state_handler)

    for h in handlers:
        h.setFormatter(fmt)

    logging.basicConfig(level=logging.INFO, handlers=handlers)
    return logging.getLogger("Launcher")


def start_engine(config: dict, state_manager, db_manager):
    """Inicia o engine de trading em thread separada."""
    from core.engine import TradingEngine
    from core.scheduler import Scheduler

    engine = TradingEngine(config, state_manager=state_manager, db_manager=db_manager)
    scheduler = Scheduler(engine)
    scheduler.start()


def start_dashboard_process() -> subprocess.Popen:
    """Inicia o Streamlit como subprocesso."""
    dashboard_path = ROOT / "dashboard" / "app.py"
    cmd = [
        sys.executable, "-m", "streamlit", "run",
        str(dashboard_path),
        "--server.port", "8501",
        "--server.address", "localhost",
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc


def main():
    parser = argparse.ArgumentParser(description="NovoBotTrading Launcher")
    parser.add_argument("--engine", action="store_true", help="Apenas o engine (sem dashboard)")
    parser.add_argument("--dashboard", action="store_true", help="Apenas o dashboard (sem engine)")
    args = parser.parse_args()

    run_engine = not args.dashboard
    run_dashboard = not args.engine

    # --- Carregar configuração ---
    from config.config_loader import load_config
    config = load_config()

    # --- Inicializar StateManager e DatabaseManager ---
    from core.state_manager import StateManager
    from database.manager import DatabaseManager

    state = StateManager.get_instance()
    # Se DATABASE_URL estiver no ambiente, usa PostgreSQL (Supabase); senão SQLite local
    db = DatabaseManager(db_path=str(ROOT / "trading.db"))

    # --- Configurar logging com integração ao state ---
    logger = setup_logging(db_manager=db, state_manager=state)

    system_conf = config.get("system", {})
    use_all_symbols = system_conf.get("use_all_symbols", False)
    symbols_info = "todos os símbolos USDT (dinâmico)" if use_all_symbols else str(system_conf.get("symbols", []))

    logger.info("=" * 60)
    logger.info("NovoBotTrading v2.0 - Inicializando...")
    logger.info(f"Modo: {'DRY RUN' if system_conf.get('dry_run', False) else 'LIVE'}")
    logger.info(f"Símbolos: {symbols_info}")
    logger.info(f"Banco: {'PostgreSQL (Supabase)' if os.environ.get('DATABASE_URL') else 'SQLite local'}")
    logger.info("=" * 60)

    # --- Iniciar State API (Flask) ---
    if run_engine:
        from core.state_api import start_api
        start_api(state, port=8502)
        logger.info("State API iniciada em http://localhost:8502")

    dashboard_proc = None

    # --- Iniciar Dashboard ---
    if run_dashboard:
        logger.info("Iniciando Dashboard Streamlit...")
        try:
            dashboard_proc = start_dashboard_process()
            time.sleep(3)  # Aguardar Streamlit inicializar
            if dashboard_proc.poll() is None:
                logger.info("Dashboard disponível em http://localhost:8501")
            else:
                logger.warning("Dashboard falhou ao inicializar. Rodando apenas o engine.")
                run_dashboard = False
        except Exception as e:
            logger.error(f"Erro ao iniciar dashboard: {e}")
            logger.info("Rodando apenas o engine...")

    # --- Iniciar Engine ---
    if run_engine:
        engine_thread = threading.Thread(
            target=start_engine,
            args=(config, state, db),
            daemon=True,
            name="TradingEngine"
        )
        engine_thread.start()
        logger.info("Engine de trading iniciado.")
    else:
        engine_thread = None

    # --- Loop principal ---
    def shutdown(signum, frame):
        logger.info("Recebido sinal de encerramento. Desligando...")
        if dashboard_proc:
            dashboard_proc.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        if run_dashboard:
            logger.info("=" * 60)
            logger.info("SISTEMA ATIVO")
            logger.info("Dashboard: http://localhost:8501")
            if run_engine:
                logger.info("State API: http://localhost:8502")
            logger.info("Pressione Ctrl+C para encerrar")
            logger.info("=" * 60)

        while True:
            time.sleep(5)

            # Monitorar se o engine caiu
            if run_engine and engine_thread and not engine_thread.is_alive():
                logger.error("Engine thread morreu inesperadamente!")
                break

            # Monitorar se o dashboard caiu e tentar reiniciar
            if run_dashboard and dashboard_proc and dashboard_proc.poll() is not None:
                logger.warning("Dashboard encerrou. Reiniciando...")
                try:
                    dashboard_proc = start_dashboard_process()
                except Exception as e:
                    logger.error(f"Falha ao reiniciar dashboard: {e}")

    except KeyboardInterrupt:
        logger.info("Encerrando por Ctrl+C...")
    finally:
        if dashboard_proc:
            dashboard_proc.terminate()
        logger.info("Sistema encerrado.")


if __name__ == "__main__":
    main()
