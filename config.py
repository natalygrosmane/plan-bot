import os
from pathlib import Path

# Base directory
BASE_DIR = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

# Telegram Bot Token
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

# Allowed users (comma-separated IDs)
_raw_allowed = os.getenv("ALLOWED_USER_IDS", "").strip()
ALLOWED_USER_IDS = set()
if _raw_allowed:
    for item in _raw_allowed.split(","):
        cleaned = item.strip()
        if cleaned.isdigit():
            ALLOWED_USER_IDS.add(int(cleaned))

# AI Provider ("gemini", "groq", "openai")
AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini").strip().lower()

# API Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

# Timezone
TIMEZONE_STR = os.getenv("TIMEZONE", "Asia/Bangkok").strip()
try:
    from zoneinfo import ZoneInfo
    TIMEZONE = ZoneInfo(TIMEZONE_STR)
except Exception:
    try:
        import pytz
        TIMEZONE = pytz.timezone(TIMEZONE_STR)
    except Exception:
        from datetime import timezone
        TIMEZONE = timezone.utc

# File paths
INBOX_FILE = BASE_DIR / "inbox.md"
TODO_FILE = BASE_DIR / "todo.md"
BACKLOG_FILE = BASE_DIR / "backlog.md"
TEMP_DIR = BASE_DIR / "temp_audio"
TEMP_DIR.mkdir(exist_ok=True)
