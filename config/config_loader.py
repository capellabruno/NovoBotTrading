"""
Config Loader com suporte a variáveis de ambiente via .env
Substitui automaticamente valores "ENV" pelo conteúdo das variáveis de ambiente.
"""
import os
import sys
import yaml
import logging

logger = logging.getLogger(__name__)

# Mapeamento: (seção, chave) -> nome da variável de ambiente
ENV_MAPPING = {
    ("execution", "api_key"): "BYBIT_API_KEY",
    ("execution", "api_secret"): "BYBIT_API_SECRET",
    ("signals", "telegram_token"): "TELEGRAM_TOKEN",
    ("signals", "telegram_chat_id"): "TELEGRAM_CHAT_ID",
    ("mcp", "gemini_api_key"): "GEMINI_API_KEY",
    ("mcp", "groq_api_key"): "GROQ_API_KEY",
}


def load_dotenv(path: str = ".env"):
    """Carrega variáveis do arquivo .env sem depender de python-dotenv."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key and key not in os.environ:
                os.environ[key] = value


def load_config(path: str = "config/settings.yaml") -> dict:
    """
    Carrega configuração do YAML e substitui placeholders "ENV"
    pelos valores das variáveis de ambiente (ou do arquivo .env).
    """
    load_dotenv()

    if not os.path.exists(path):
        logger.error(f"Arquivo de configuração não encontrado: {path}")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Substituir placeholders ENV
    for (section, key), env_var in ENV_MAPPING.items():
        section_data = config.get(section, {})
        if section_data.get(key) == "ENV" or not section_data.get(key):
            env_val = os.environ.get(env_var)
            if env_val:
                config.setdefault(section, {})[key] = env_val
            else:
                logger.warning(f"Variável de ambiente {env_var} não definida para {section}.{key}")

    # DRY_RUN: variável de ambiente tem prioridade sobre o settings.yaml
    # Use DRY_RUN=true para simular ou DRY_RUN=false para live
    dry_run_env = os.environ.get("DRY_RUN")
    if dry_run_env is not None:
        config.setdefault("system", {})["dry_run"] = dry_run_env.strip().lower() in ("1", "true", "yes")
        logger.info(f"dry_run definido pela variável de ambiente DRY_RUN={dry_run_env!r}")

    return config
