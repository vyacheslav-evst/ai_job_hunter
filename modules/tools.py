# -*- coding: utf-8 -*-
"""
tools.py — LangChain @tool обёртки для всех модулей AI Job Hunter.
Каждый инструмент принимает строковые аргументы и возвращает строку,
что соответствует интерфейсу ReAct-агента.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from langchain_core.tools import tool

import config
from modules.service import JobHunterService

# Единый экземпляр сервиса для всех инструментов агента
_service: JobHunterService | None = None


def _get_service() -> JobHunterService:
    """Ленивая инициализация сервиса."""
    global _service
    if not _service:
        _service = JobHunterService()
    return _service


# ─── Инструменты ──────────────────────────────────────────────────────────────

@tool
def search_vacancies(query: str) -> str:
    """
    Ищет вакансии на hh.ru И Habr Career по заданному запросу.
    Аргумент: строка поискового запроса, например "prompt engineer" или "AI engineer".
    Автоматически расширяет поиск до 3-5 связанных запросов и агрегирует
    уникальные результаты с обоих источников — это значительно увеличивает охват.
    Возвращает: краткий список найденных вакансий с названием и компанией.
    """
    try:
        service = _get_service()

        # Составляем список запросов: пользовательский + близкие из пресета AI/ML
        AI_RELATED_QUERIES = [
            "prompt engineer",
            "LLM engineer",
            "AI engineer",
            "AI trainer",
            "NLP engineer",
            "LLM developer",
            "AI автоматизация",
            "conversational AI",
        ]

        query_lower = query.lower().strip()
        related = [q for q in AI_RELATED_QUERIES if q.lower() != query_lower]
        queries_to_run = [query] + related[:3]

        # Агрегируем результаты по всем запросам с обоих источников
        seen_ids: dict[str, object] = {}

        for q in queries_to_run:
            results = service.searcher.search_hh(q, pages=3)
            for v in results:
                if v.id not in seen_ids:
                    seen_ids[v.id] = v
            results = service.searcher.search_habr(q, pages=2)
            for v in results:
                if v.id not in seen_ids:
                    seen_ids[v.id] = v

        vacancies = list(seen_ids.values())
        service.vacancies = vacancies
        service.analyses = []

        if not vacancies:
            return f"Вакансии по запросу '{query}' (и связанным запросам) не найдены."

        hh_count = sum(1 for v in vacancies if v.source == "hh.ru")
        habr_count = sum(1 for v in vacancies if v.source == "habr.career")

        lines = [
            f"Найдено {len(vacancies)} уникальных вакансий "
            f"(hh.ru: {hh_count}, Habr Career: {habr_count}) "
            f"по запросам: {', '.join(queries_to_run)}\n"
        ]
        for i, v in enumerate(vacancies[:20], 1):
            source_tag = "[H]" if v.source == "habr.career" else "[hh]"
            lines.append(f"{i}. {source_tag} {v.title} | {v.company} | {v.salary_str()}")
        if len(vacancies) > 20:
            lines.append(f"... ещё {len(vacancies) - 20} вакансий")
        return "\n".join(lines)
    except Exception as e:
        return f"Ошибка поиска: {e}"


@tool
def analyze_vacancies(limit: str = "20") -> str:
    """
    Анализирует найденные вакансии через LLM и оценивает их релевантность.
    Аргумент: максимальное количество вакансий для LLM-анализа (строка с числом, по умолчанию "20").
    Перед вызовом обязательно выполни search_vacancies.

    Работает двухэтапно:
      1. Быстрый keyword pre-filter (без LLM) — из всех найденных отбирает топ кандидатов
      2. LLM-анализ только отобранных — загружает описания и анализирует через GPT

    Возвращает: список вакансий с оценками релевантности и рекомендациями APPLY/MAYBE/SKIP.
    """
    try:
        service = _get_service()
        vacancies = service.vacancies
        if not vacancies:
            return "Сначала выполни search_vacancies для поиска вакансий."

        n_llm = min(int(limit), len(vacancies))
        analyses = service.analyze(limit=n_llm)

        if not analyses:
            return (
                f"Проанализировано {n_llm} вакансий, "
                f"но ни одна не прошла порог релевантности {config.RELEVANCE_THRESHOLD}."
            )

        lines = [
            f"Найдено: {len(vacancies)} | LLM проанализировано: {n_llm} "
            f"| Прошли порог: {len(analyses)}\n"
        ]
        for i, a in enumerate(analyses, 1):
            lines.append(
                f"{i}. {a.vacancy_title} | {a.company} | "
                f"Score: {a.relevance_score}/100 | {a.recommendation}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Ошибка анализа: {e}"


@tool
def adapt_resume(vacancy_number: str) -> str:
    """
    Адаптирует резюме под конкретную вакансию из списка анализов.
    Аргумент: номер вакансии (строка с числом, например "1" для первой вакансии).
    Перед вызовом обязательно выполни analyze_vacancies.
    Возвращает: краткое описание адаптированного резюме.
    """
    try:
        service = _get_service()
        analyses = service.analyses
        if not analyses:
            return "Сначала выполни analyze_vacancies."

        idx = int(vacancy_number) - 1
        if not (0 <= idx < len(analyses)):
            return f"Номер должен быть от 1 до {len(analyses)}."

        analysis = analyses[idx]
        adapted = service.adapt_resume(analysis)

        return (
            f"Резюме адаптировано под: {analysis.vacancy_title} | {analysis.company}\n"
            f"Summary: {adapted.get('adapted_summary', '')[:200]}...\n"
            f"Топ навыки: {', '.join(adapted.get('top_skills', [])[:5])}"
        )
    except Exception as e:
        return f"Ошибка адаптации резюме: {e}"


@tool
def generate_cover_letter(vacancy_number: str, tone: str = "professional") -> str:
    """
    Генерирует сопроводительное письмо для вакансии.
    Аргументы:
      - vacancy_number: номер вакансии (строка с числом, например "1")
      - tone: тон письма — professional, friendly или concise (по умолчанию professional)
    Перед вызовом желательно выполнить adapt_resume для лучшего результата.
    Возвращает: текст сопроводительного письма и путь к сохранённому файлу.
    """
    try:
        service = _get_service()
        analyses = service.analyses
        if not analyses:
            return "Сначала выполни analyze_vacancies."

        idx = int(vacancy_number) - 1
        if not (0 <= idx < len(analyses)):
            return f"Номер должен быть от 1 до {len(analyses)}."

        analysis = analyses[idx]
        letter = service.generate_cover_letter(analysis, tone=tone)

        return (
            f"Письмо готово для: {analysis.company}\n\n"
            f"--- ПИСЬМО ---\n{letter[:600]}{'...' if len(letter) > 600 else ''}"
        )
    except Exception as e:
        return f"Ошибка генерации письма: {e}"


@tool
def export_report(format: str = "md") -> str:
    """
    Создаёт итоговый отчёт по результатам анализа вакансий.
    Аргумент: формат отчёта — "md" для Markdown (по умолчанию).
    Перед вызовом обязательно выполни analyze_vacancies.
    Возвращает: путь к созданному файлу отчёта.
    """
    try:
        service = _get_service()
        if not service.analyses:
            return "Нет данных для отчёта. Сначала выполни analyze_vacancies."

        path = service.export_report()
        return f"Отчёт создан: {path}\nВакансий в отчёте: {len(service.analyses)}"
    except Exception as e:
        return f"Ошибка создания отчёта: {e}"


@tool
def export_all_pdf() -> str:
    """
    Создаёт три PDF-файла по результатам текущей сессии:
      1. Отчёт по вакансиям (report_*.pdf)
      2. Адаптированное резюме (resume_*.pdf) — если было адаптировано
      3. Сопроводительное письмо (cover_*.pdf) — если было сгенерировано
    Вызывай в самом конце, после export_report, adapt_resume и generate_cover_letter.
    Возвращает пути к созданным PDF-файлам.
    """
    try:
        service = _get_service()

        if not service.analyses:
            return "Нет данных (сначала выполни analyze_vacancies)"

        # Берём первый проанализированный анализ (лучший по score)
        analysis = service.analyses[0]
        adapted = service.adapted_resumes.get(analysis.vacancy_id)
        letter = service.cover_letters.get(analysis.vacancy_id)

        results_dict = service.export_pdf_package(analysis, adapted, letter)

        lines = ["PDF-пакет готов:"]
        for key, path in results_dict.items():
            label = {"report": "Отчёт", "resume": "Резюме", "cover": "Письмо"}.get(key, key)
            if path:
                lines.append(f"  {label}: {path}")
            else:
                lines.append(f"  {label}: не создан")

        return "\n".join(lines)
    except Exception as e:
        return f"Ошибка генерации PDF: {e}"


@tool
def get_session_state() -> str:
    """
    Возвращает текущее состояние сессии: количество найденных вакансий,
    результатов анализа и адаптированных резюме.
    Используй для проверки прогресса перед следующим шагом.
    """
    service = _get_service()
    vacancies = service.vacancies
    analyses = service.analyses
    adapted = service.adapted_resumes

    apply_count = sum(1 for a in analyses if a.recommendation == "APPLY")
    maybe_count = sum(1 for a in analyses if a.recommendation == "MAYBE")

    return (
        f"Состояние сессии:\n"
        f"  Найдено вакансий: {len(vacancies)}\n"
        f"  Проанализировано: {len(analyses)} (APPLY: {apply_count}, MAYBE: {maybe_count})\n"
        f"  Адаптировано резюме: {len(adapted)}\n"
    )


# ─── Экспорт всех инструментов ────────────────────────────────────────────────

ALL_TOOLS = [
    search_vacancies,
    analyze_vacancies,
    adapt_resume,
    generate_cover_letter,
    export_report,
    export_all_pdf,
    get_session_state,
]
