# AI Job Hunter Agent

> Автономный Python-агент для поиска AI-вакансий на hh.ru, анализа через LLM и адаптации резюме под каждую позицию.

**Стек:** Python 3.x · OpenAI API · BeautifulSoup · Pydantic · fpdf2

---

## Что умеет агент

| Команда | Что делает |
|---------|-----------|
| `/search` | Парсит hh.ru по 11 AI-запросам, фильтрует мусор и Senior-вакансии, дедуплицирует |
| `/analyze [N]` | Анализирует N вакансий через LLM: score 0–100, APPLY / MAYBE / SKIP |
| `/adapt N` | Адаптирует резюме под конкретную вакансию (без придумывания фактов) |
| `/cover N [тон]` | Генерирует персонализированное сопроводительное письмо (professional / friendly / concise) |
| `/resume N` | Экспортирует адаптированное резюме в Markdown и PDF |
| `/report` | Создаёт общий Markdown-отчёт по всем проанализированным вакансиям |
| `/run [запрос]` | Полный цикл одной командой: search → analyze → report |
| `/open N` | Открывает вакансию в браузере |
| `/list [фильтр]` | Список вакансий: `apply`, `maybe`, `skip`, `top5`, `all` |

---

## Архитектура

```
ai_job_hunter/
├── agent.py              # CLI-интерфейс, точка входа, все команды
├── config.py             # Настройки, загрузка .env
├── run.bat               # Быстрый запуск на Windows (двойной клик)
├── memory/
│   └── base_resume.json  # Долгосрочная память — базовое резюме кандидата
├── modules/
│   ├── searcher.py       # Парсинг hh.ru (BeautifulSoup), фильтрация
│   ├── analyzer.py       # Анализ вакансий через LLM, скоринг
│   ├── resume_adapter.py # Адаптация резюме под вакансию
│   ├── cover_letter.py   # Генерация сопроводительных писем
│   ├── exporter.py       # Экспорт в Markdown / PDF
│   └── llm_client.py     # LLM клиент, fallback, exponential backoff
├── output/               # Результаты работы агента (gitignored)
├── .env.example          # Шаблон переменных окружения
└── requirements.txt
```

### Как это работает

```
hh.ru HTML
    │
    ▼
searcher.py  ──→  список вакансий (Vacancy)
    │              фильтрация: мусор, Senior/Lead
    ▼
analyzer.py  ──→  LLM оценивает релевантность (VacancyAnalysis)
    │              score 0-100 · APPLY / MAYBE / SKIP
    │
    ├──→  resume_adapter.py  ──→  адаптированное резюме (JSON)
    │
    ├──→  cover_letter.py    ──→  сопроводительное письмо (MD)
    │
    └──→  exporter.py        ──→  резюме (MD + PDF)
```

---

## Быстрый старт

### 1. Клонируй репозиторий

```bash
git clone https://github.com/ysiSevera/ai_job_hunter.git
cd ai_job_hunter
```

### 2. Создай виртуальное окружение

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate
```

### 3. Установи зависимости

```bash
pip install -r requirements.txt
```

### 4. Настрой `.env`

```bash
cp .env.example .env
```

Открой `.env` и заполни:

```env
OPENROUTER_API_KEY=sk-...   # OpenAI или OpenRouter ключ
LLM_MODEL=gpt-4o-mini       # Модель (gpt-4o-mini рекомендуется)
SEARCH_AREA=113              # 113 = вся Россия, 1 = Москва
RELEVANCE_THRESHOLD=45       # Минимальный score для отображения
```

Получить ключ OpenAI: [platform.openai.com/api-keys](https://platform.openai.com/api-keys)

> **Для пользователей из России:** если OpenAI недоступен напрямую, укажи прокси:
> ```env
> HTTPS_PROXY=http://127.0.0.1:10809
> ```

### 5. Заполни своё резюме

Открой `memory/base_resume.json` и замени данные на свои: имя, навыки, проекты, целевые роли.

### 6. Запусти агента

```bash
# Windows — двойной клик на run.bat
# Или из терминала:
python agent.py
```

---

## Пример сессии

```
agent> /run
[ПОИСК] hh.ru по 11 запросам...
[ИТОГО] 87 уникальных вакансий

[АНАЛИЗ] 20 вакансий через gpt-4o-mini...
  Score: 78 | APPLY  — AI Automation Engineer
  Score: 71 | APPLY  — LLM/Agent Engineer
  Score: 65 | MAYBE  — ML-инженер в стартап
  ...

agent> /adapt 1
Адаптирую резюме под: AI Automation Engineer...

agent> /cover 1 friendly
Генерирую письмо (тон: friendly)...

agent> /resume 1
[PDF] output/resume_20260511_...pdf
```

---

## Настройки

В `config.py` можно изменить поисковые запросы:

```python
SEARCH_QUERIES = [
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
```

---

## Зависимости

| Библиотека | Назначение |
|------------|-----------|
| `openai` / `requests` | LLM API (OpenAI-совместимый) |
| `beautifulsoup4` + `lxml` | Парсинг hh.ru |
| `pydantic` | Валидация и структуры данных |
| `python-dotenv` | Загрузка .env |
| `fpdf2` | Генерация PDF |

---

## Roadmap

- [x] Парсинг hh.ru с фильтрацией Senior/мусора
- [x] Анализ через LLM (OpenAI / OpenRouter)
- [x] Адаптация резюме под вакансию
- [x] Генерация сопроводительных писем
- [x] Экспорт в PDF
- [x] Сохранение сессии между запусками
- [ ] Streamlit веб-интерфейс
- [ ] Docker + деплой на Hugging Face Spaces
- [ ] Универсальный режим (любая профессия, не только AI)
- [ ] Парсинг Habr Career
- [ ] Evaluation pipeline (метрики качества адаптации)

---

## Этот проект как портфолио

Демонстрирует:

- **Prompt Engineering** — многоэтапные промпты, JSON-first, anti-hallucination, управление температурой
- **LLM API** — OpenAI-совместимая интеграция, exponential backoff при rate limit, fallback между моделями
- **Python** — модульная архитектура, Pydantic-валидация, веб-скрапинг
- **Системное мышление** — пайплайн поиск → фильтрация → анализ → адаптация → экспорт

---

*Создан как портфолио-проект для поиска позиций Prompt Engineer / AI Engineer на российском рынке*
