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


# ─── OpenRouter (основной LLM провайдер) ──────────────────────────────────────
# OpenRouter даёт доступ к сотням моделей через единый OpenAI-совместимый API.
# Бесплатные модели помечены суффиксом :free
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL: str = "https://api.openai.com/v1"
LLM_MODEL: str = os.getenv("LLM_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")

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
SEARCH_QUERIES: list[str] = [
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
]
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
    if not OPENROUTER_API_KEY:
        print("[CONFIG] ОШИБКА: OPENROUTER_API_KEY не задан в .env файле")
        return False
    return True
