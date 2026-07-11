"""App configuration loaded from environment / .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


DB_PATH = BASE_DIR / _env("AT_DB_PATH", "data/tracker.db")
TIMEZONE = _env("AT_TIMEZONE", "America/Chicago")
SCRAPE_HOUR = int(_env("AT_SCRAPE_HOUR", "6"))
DEFAULT_ZIP = _env("AT_ZIP", "55113")
DEFAULT_RADIUS_MIN = int(_env("AT_RADIUS_MINUTES", "15"))

SMTP_HOST = _env("AT_SMTP_HOST")
SMTP_PORT = int(_env("AT_SMTP_PORT", "587"))
SMTP_USER = _env("AT_SMTP_USER")
SMTP_PASSWORD = _env("AT_SMTP_PASSWORD")
EMAIL_FROM = _env("AT_EMAIL_FROM")
EMAIL_TO = _env("AT_EMAIL_TO")

NTFY_TOPIC = _env("AT_NTFY_TOPIC")

LLM_PROVIDER = _env("AT_LLM_PROVIDER")
LLM_API_KEY = _env("AT_LLM_API_KEY")
LLM_MODEL = _env("AT_LLM_MODEL")

REQUEST_TIMEOUT = 30
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 ActivityTracker/1.0"
)

CATEGORIES = [
    "athletics",
    "creative arts",
    "stem / education",
    "aquatics",
    "parks & rec / community ed",
    "ymca / community centers",
    "sports leagues",
]
