"""
State API - Mini servidor Flask que expõe o StateManager para o dashboard Streamlit.
Roda em thread separada dentro do processo do engine.
"""
import json
import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state_manager import StateManager

logger = logging.getLogger(__name__)

_state: "StateManager" = None
_config_path: str = "config/settings.yaml"


def _make_app():
    try:
        from flask import Flask, jsonify, request as flask_request
    except ImportError:
        logger.error("Flask não instalado. Execute: pip install flask")
        return None

    app = Flask(__name__)
    app.logger.disabled = True
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)

    @app.route("/state")
    def get_state():
        if _state is None:
            return jsonify({"error": "State not initialized"}), 503
        return jsonify(_state.get_snapshot())

    @app.route("/control/pause", methods=["POST"])
    def pause():
        if _state:
            _state.request_pause()
        return jsonify({"ok": True})

    @app.route("/control/resume", methods=["POST"])
    def resume():
        if _state:
            _state.request_resume()
        return jsonify({"ok": True})

    @app.route("/control/reload-config", methods=["POST"])
    def reload_config():
        if _state:
            _state.request_reload_config()
        return jsonify({"ok": True})

    @app.route("/config", methods=["GET"])
    def get_config():
        if _state is None:
            return jsonify({}), 503
        # Retorna config sem credenciais
        safe_config = {}
        for section, values in _state.config.items():
            if isinstance(values, dict):
                safe_section = {}
                for k, v in values.items():
                    if any(secret in k.lower() for secret in ["key", "secret", "token", "password"]):
                        safe_section[k] = "***"
                    else:
                        safe_section[k] = v
                safe_config[section] = safe_section
            else:
                safe_config[section] = values
        return jsonify(safe_config)

    @app.route("/config", methods=["POST"])
    def update_config():
        """Recebe um dict com as chaves a atualizar e salva no YAML."""
        try:
            import yaml
            data = flask_request.get_json(force=True)
            if not data:
                return jsonify({"error": "Nenhum dado enviado"}), 400

            with open(_config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            # Atualizar valores (apenas seções permitidas)
            allowed_sections = {"system", "quality", "risk", "mcp", "adaptive", "indicators"}
            for section, values in data.items():
                if section in allowed_sections and isinstance(values, dict):
                    config.setdefault(section, {}).update(values)

            with open(_config_path, "w", encoding="utf-8") as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

            if _state:
                _state.request_reload_config()

            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/health")
    def health():
        return jsonify({"status": "ok"})

    return app


def start_api(state_manager: "StateManager", port: int = 8502, config_path: str = "config/settings.yaml"):
    """Inicia o servidor Flask em uma thread daemon."""
    global _state, _config_path
    _state = state_manager
    _config_path = config_path

    app = _make_app()
    if app is None:
        return

    def run():
        try:
            app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
        except Exception as e:
            logger.error(f"State API falhou: {e}")

    thread = threading.Thread(target=run, daemon=True, name="StateAPI")
    thread.start()
    logger.info(f"State API iniciada em http://127.0.0.1:{port}")
