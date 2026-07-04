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
YANDEX_API_KEY = os.environ.get("YANDEX_API_KEY", "")
YANDEX_FOLDER_ID = os.environ.get("YANDEX_FOLDER_ID", "")

YANDEX_GPT_MODEL_120B = f"gpt://{YANDEX_FOLDER_ID}/gpt-oss-120b/latest" if YANDEX_FOLDER_ID else ""
YANDEX_GPT_MODEL_5_1 = f"gpt://{YANDEX_FOLDER_ID}/yandexgpt-5.1/latest" if YANDEX_FOLDER_ID else ""
