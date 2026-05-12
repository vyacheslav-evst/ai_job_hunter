"""
config.py — центральный модуль конфигурации
Загружает все настройки из .env файла
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Загружаем .env файл из корня проекта
BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

# Принудительно включаем UTF-8 для корректного вывода в Windows
os.environ.setdefault("PYTHONUTF8", "1")


# ─── OpenAI API ───────────────────────────────────────────────────────────────
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o-mini")

# ─── OpenRouter (устарело, оставлено для обратной совместимости) ──────────────
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL: str = "https://api.openai.com/v1"

# ─── Google Gemini (устарело, оставлено для обратной совместимости) ───────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = "gemini-2.0-flash"

# ─── Telegram ─────────────────────────────────────────────────────────────────
_tg_api_id_raw = os.getenv("TELEGRAM_API_ID", "0")
TELEGRAM_API_ID: int = int(_tg_api_id_raw) if _tg_api_id_raw.isdigit() else 0
TELEGRAM_API_HASH: str = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_PHONE: str = os.getenv("TELEGRAM_PHONE", "")

# Каналы Telegram с вакансиями по AI/ML
TELEGRAM_CHANNELS: list[str] = [
    "aiwork",
    "ai_jobs_ru",
    "machinelearning_jobs",
    "remotejobs_ru",
]

# ─── Настройки поиска hh.ru ───────────────────────────────────────────────────
HH_BASE_URL: str = "https://api.hh.ru"

# Пресеты запросов для разных профессий
PROFESSION_PRESETS: dict[str, list[str]] = {
    "AI/ML Engineer": [
        "prompt engineer",
        "AI engineer",
        "LLM engineer",
        "NLP engineer",
        "conversational AI",
        "AI trainer",
        "AI content specialist",
        "LLM developer",
        "AI автоматизация",
        "чат-бот разработчик",
        "ML инженер junior",
    ],
    "Python Developer": [
        "python developer",
        "python разработчик",
        "backend python",
        "django developer",
        "fastapi developer",
        "python junior",
    ],
    "Data Analyst": [
        "data analyst",
        "аналитик данных",
        "бизнес-аналитик data",
        "sql analyst",
        "junior data analyst",
        "BI аналитик",
    ],
    "Frontend Developer": [
        "frontend developer",
        "react developer",
        "vue developer",
        "javascript developer",
        "typescript developer",
        "frontend junior",
    ],
}

# Активный пресет (можно переопределить через .env PROFESSION_PRESET)
_preset_name: str = os.getenv("PROFESSION_PRESET", "AI/ML Engineer")
SEARCH_QUERIES: list[str] = PROFESSION_PRESETS.get(_preset_name, PROFESSION_PRESETS["AI/ML Engineer"])
ACTIVE_PROFESSION: str = _preset_name if _preset_name in PROFESSION_PRESETS else "AI/ML Engineer"

SEARCH_AREA: int = int(os.getenv("SEARCH_AREA", "113"))  # 113 = вся Россия
SEARCH_ONLY_REMOTE: bool = True

# ─── Настройки агента ─────────────────────────────────────────────────────────
RELEVANCE_THRESHOLD: int = int(os.getenv("RELEVANCE_THRESHOLD", "60"))

# ─── Пути к файлам ────────────────────────────────────────────────────────────
MEMORY_DIR: Path = BASE_DIR / "memory"
OUTPUT_DIR: Path = BASE_DIR / "output"
BASE_RESUME_PATH: Path = MEMORY_DIR / "base_resume.json"


# ─── Прокси (для доступа к Google API из России) ─────────────────────────────
HTTPS_PROXY: str = os.getenv("HTTPS_PROXY", "")
HTTP_PROXY: str = os.getenv("HTTP_PROXY", "")

def apply_proxy():
    """
    Применяет прокси-настройки к переменным окружения.
    requests автоматически подхватывает HTTPS_PROXY / HTTP_PROXY из окружения.
    """
    if HTTPS_PROXY:
        os.environ["HTTPS_PROXY"] = HTTPS_PROXY
        os.environ["https_proxy"] = HTTPS_PROXY
    if HTTP_PROXY:
        os.environ["HTTP_PROXY"] = HTTP_PROXY
        os.environ["http_proxy"] = HTTP_PROXY


def validate_config() -> bool:
    """Проверяет что обязательные ключи заполнены."""
    if not OPENAI_API_KEY:
        print("[CONFIG] ОШИБКА: OPENAI_API_KEY не задан в .env файле")
        return False
    return True
