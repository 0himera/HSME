import os

DIM = 10000
DATABASE_FILE = os.environ.get("HSME_DATABASE_FILE", "db_state.pkl")

# Manual dotenv loader to avoid external dependencies
def load_dotenv():
    # Search for .env relative to project root or current working dir
    paths_to_check = [
        ".env",
        os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    ]
    for p in paths_to_check:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        parts = line.split("=", 1)
                        if len(parts) == 2:
                            k = parts[0].strip()
                            v = parts[1].strip()
                            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                                v = v[1:-1]
                            os.environ.setdefault(k, v)
                break
            except Exception as e:
                print(f"Warning: Failed to load .env file from {p}: {e}")

load_dotenv()

# Yandex Cloud Settings
YANDEX_API_KEY = os.environ.get("YANDEX_API_KEY", "").strip('"\'')
if YANDEX_API_KEY in ("your_yandex_api_key_here", ""):
    YANDEX_API_KEY = ""
    
YANDEX_FOLDER_ID = os.environ.get("YANDEX_FOLDER_ID", "").strip('"\'')

YANDEX_GPT_MODEL_120B = f"gpt://{YANDEX_FOLDER_ID}/gpt-oss-120b/latest" if YANDEX_FOLDER_ID else ""
YANDEX_GPT_MODEL_5_1 = f"gpt://{YANDEX_FOLDER_ID}/yandexgpt-5.1/latest" if YANDEX_FOLDER_ID else ""

# Gemini Settings
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip('"\'')
if GEMINI_API_KEY in ("your_gemini_api_key_here", ""):
    GEMINI_API_KEY = ""

# Neo4j dual-storage settings
USE_NEO4J = os.environ.get("USE_NEO4J", "true").strip('"\'').lower() in ("1", "true", "yes")
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687").strip('"\'')
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j").strip('"\'')
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "hsme_password").strip('"\'')
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j").strip('"\'')
NEO4J_CONNECTION_TIMEOUT = float(os.environ.get("NEO4J_CONNECTION_TIMEOUT", "10.0").strip('"\''))
NEO4J_QUERY_TIMEOUT = float(os.environ.get("NEO4J_QUERY_TIMEOUT", "60.0").strip('"\''))
NEO4J_INDEX_AWAIT_TIMEOUT = int(os.environ.get("NEO4J_INDEX_AWAIT_TIMEOUT", "300").strip('"\''))
NEO4J_DRY_RUN = os.environ.get("NEO4J_DRY_RUN", "false").strip('"\'').lower() in ("1", "true", "yes")

# LLM settings (optional; used by corpus loader and overridable via .env)
LLM_ENV_FILE = os.environ.get("LLM_ENV_FILE", ".env").strip('"\'')
LLM_API_KEY = os.environ.get("LLM_API_KEY", "").strip('"\'')
if LLM_API_KEY in ("sk-or-v1-your-key-here", ""):
    LLM_API_KEY = ""
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "").strip('"\'') or None
LLM_FOLDER_ID = os.environ.get("LLM_FOLDER_ID", "").strip('"\'') or None
LLM_MODEL_ID = (os.environ.get("LLM_MODEL_ID") or os.environ.get("LLM_MODEL", "")).strip('"\'') or None


def read_env_file(filepath: str) -> dict[str, str]:
    """Parse KEY=VALUE lines from a dotenv-style file."""
    values: dict[str, str] = {}
    if not filepath or not os.path.exists(filepath):
        return values

    with open(filepath, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                values[key] = value
    return values


def resolve_llm_settings(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    folder_id: str | None = None,
    model_id: str | None = None,
    env_file: str | None = None,
) -> dict[str, str]:
    """Merge LLM config: CLI args > process env > .env file."""
    file_values = read_env_file(env_file or LLM_ENV_FILE)

    def pick(name: str, cli_value: str | None) -> str | None:
        if cli_value:
            val = cli_value
        else:
            val = os.environ.get(name) or file_values.get(name)
        if val:
            val = val.strip('"\'')
            if val in ("sk-or-v1-your-key-here", "your_gemini_api_key_here", "your_yandex_api_key_here", ""):
                return None
            return val
        return None

    def pick_model(cli_value: str | None) -> str | None:
        if cli_value:
            return cli_value.strip('"\'')
        for name in ("LLM_MODEL_ID", "LLM_MODEL"):
            env_value = os.environ.get(name)
            if env_value:
                return env_value.strip('"\'')
        val = file_values.get("LLM_MODEL_ID") or file_values.get("LLM_MODEL")
        return val.strip('"\'') if val else None

    resolved: dict[str, str] = {}
    for key, cli_value in (
        ("LLM_API_KEY", api_key),
        ("LLM_BASE_URL", base_url),
        ("LLM_FOLDER_ID", folder_id),
    ):
        value = pick(key, cli_value)
        if value:
            resolved[key] = value

    model_value = pick_model(model_id)
    if model_value:
        resolved["LLM_MODEL_ID"] = model_value
    return resolved
