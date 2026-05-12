"""
tools.py — LangChain @tool обёртки для всех модулей AI Job Hunter.
Каждый инструмент принимает строковые аргументы и возвращает строку,
что соответствует интерфейсу ReAct-агента.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from langchain_core.tools import tool

import config
from modules.searcher import JobSearcher
from modules.analyzer import VacancyAnalyzer
from modules.resume_adapter import ResumeAdapter
from modules.cover_letter import CoverLetterGenerator
from modules.exporter import Exporter

# ─── Ленивые синглтоны модулей (инициализируем один раз) ─────────────────────

_searcher: JobSearcher | None = None
_analyzer: VacancyAnalyzer | None = None
_adapter: ResumeAdapter | None = None
_cover_gen: CoverLetterGenerator | None = None
_exporter: Exporter | None = None

# Разделяемое состояние сессии (агент работает со списками в памяти)
_session: dict = {
    "vacancies": [],    # list[Vacancy]
    "analyses": [],     # list[VacancyAnalysis]
    "adapted": {},      # vacancy_id -> dict
}


def _get_searcher() -> JobSearcher:
    global _searcher
    if not _searcher:
        _searcher = JobSearcher()
    return _searcher


def _get_analyzer() -> VacancyAnalyzer:
    global _analyzer
    if not _analyzer:
        _analyzer = VacancyAnalyzer()
    return _analyzer


def _get_adapter() -> ResumeAdapter:
    global _adapter
    if not _adapter:
        _adapter = ResumeAdapter()
    return _adapter


def _get_cover_gen() -> CoverLetterGenerator:
    global _cover_gen
    if not _cover_gen:
        _cover_gen = CoverLetterGenerator()
    return _cover_gen


def _get_exporter() -> Exporter:
    global _exporter
    if not _exporter:
        _exporter = Exporter()
    return _exporter


# ─── Инструменты ──────────────────────────────────────────────────────────────

@tool
def search_vacancies(query: str) -> str:
    """
    Ищет вакансии на hh.ru по заданному запросу.
    Аргумент: строка поискового запроса, например "prompt engineer" или "AI engineer".
    Возвращает: краткий список найденных вакансий с названием и компанией.
    """
    try:
        searcher = _get_searcher()
        vacancies = searcher.search_hh(query, pages=2)
        if not vacancies:
            return f"Вакансии по запросу '{query}' не найдены."

        _session["vacancies"] = vacancies
        _session["analyses"] = []  # сбрасываем анализы при новом поиске

        lines = [f"Найдено {len(vacancies)} вакансий по запросу '{query}':\n"]
        for i, v in enumerate(vacancies[:15], 1):
            lines.append(f"{i}. {v.title} | {v.company} | {v.salary_str()}")
        if len(vacancies) > 15:
            lines.append(f"... ещё {len(vacancies) - 15} вакансий")
        return "\n".join(lines)
    except Exception as e:
        return f"Ошибка поиска: {e}"


@tool
def analyze_vacancies(limit: str = "10") -> str:
    """
    Анализирует найденные вакансии через LLM и оценивает их релевантность.
    Аргумент: количество вакансий для анализа (строка с числом, по умолчанию "10").
    Перед вызовом обязательно выполни search_vacancies.
    Возвращает: список вакансий с оценками релевантности и рекомендациями APPLY/MAYBE/SKIP.
    """
    try:
        vacancies = _session.get("vacancies", [])
        if not vacancies:
            return "Сначала выполни search_vacancies для поиска вакансий."

        n = min(int(limit), len(vacancies))
        searcher = _get_searcher()
        analyzer = _get_analyzer()

        # Загружаем описания
        enriched = searcher.enrich_with_descriptions(vacancies[:n])
        analyses = analyzer.analyze_batch(enriched)

        _session["analyses"] = analyses
        _session["adapted"] = {}

        if not analyses:
            return f"Ни одна из {n} вакансий не прошла порог релевантности {config.RELEVANCE_THRESHOLD}."

        lines = [f"Проанализировано: {n} вакансий. Прошли порог: {len(analyses)}\n"]
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
        analyses = _session.get("analyses", [])
        if not analyses:
            return "Сначала выполни analyze_vacancies."

        idx = int(vacancy_number) - 1
        if not (0 <= idx < len(analyses)):
            return f"Номер должен быть от 1 до {len(analyses)}."

        analysis = analyses[idx]
        adapter = _get_adapter()
        adapted = adapter.adapt(analysis)
        adapter.save(adapted)

        _session["adapted"][analysis.vacancy_id] = adapted

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
        analyses = _session.get("analyses", [])
        if not analyses:
            return "Сначала выполни analyze_vacancies."

        idx = int(vacancy_number) - 1
        if not (0 <= idx < len(analyses)):
            return f"Номер должен быть от 1 до {len(analyses)}."

        analysis = analyses[idx]
        adapted = _session["adapted"].get(analysis.vacancy_id)

        cover_gen = _get_cover_gen()
        letter = cover_gen.generate(analysis, adapted_resume=adapted, tone=tone)
        path = cover_gen.save(letter, analysis)

        return (
            f"Письмо готово для: {analysis.company}\n"
            f"Сохранено: {path}\n\n"
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
        analyses = _session.get("analyses", [])
        if not analyses:
            return "Нет данных для отчёта. Сначала выполни analyze_vacancies."

        exporter = _get_exporter()
        path = exporter.export_analysis_md(analyses)
        return f"Отчёт создан: {path}\nВакансий в отчёте: {len(analyses)}"
    except Exception as e:
        return f"Ошибка создания отчёта: {e}"


@tool
def get_session_state() -> str:
    """
    Возвращает текущее состояние сессии: количество найденных вакансий,
    результатов анализа и адаптированных резюме.
    Используй для проверки прогресса перед следующим шагом.
    """
    vacancies = _session.get("vacancies", [])
    analyses = _session.get("analyses", [])
    adapted = _session.get("adapted", {})

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
    get_session_state,
]
