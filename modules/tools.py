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
    Ищет вакансии на hh.ru И Habr Career по заданному запросу.
    Аргумент: строка поискового запроса, например "prompt engineer" или "AI engineer".
    Автоматически расширяет поиск до 3-5 связанных запросов и агрегирует
    уникальные результаты с обоих источников — это значительно увеличивает охват.
    Возвращает: краткий список найденных вакансий с названием и компанией.
    """
    try:
        searcher = _get_searcher()

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
            # hh.ru
            for v in searcher.search_hh(q, pages=3):
                if v.id not in seen_ids:
                    seen_ids[v.id] = v
            # Habr Career
            for v in searcher.search_habr(q, pages=2):
                if v.id not in seen_ids:
                    seen_ids[v.id] = v

        vacancies = list(seen_ids.values())

        if not vacancies:
            return f"Вакансии по запросу '{query}' (и связанным запросам) не найдены."

        _session["vacancies"] = vacancies
        _session["analyses"] = []

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
        vacancies = _session.get("vacancies", [])
        if not vacancies:
            return "Сначала выполни search_vacancies для поиска вакансий."

        n_llm = min(int(limit), len(vacancies))
        searcher = _get_searcher()
        analyzer = _get_analyzer()

        # Шаг 1: keyword pre-filter (бесплатно, без LLM)
        # Отбираем топ-(n_llm * 2) чтобы дать LLM чуть больший выбор,
        # затем LLM-анализируем не более n_llm из них
        pre_n = min(n_llm * 2, len(vacancies))
        candidates = analyzer.pre_filter(vacancies, top_n=pre_n)
        to_analyze = candidates[:n_llm]

        print(f"\n[ANALYZE] Pre-filter: {len(vacancies)} → {len(candidates)} → LLM: {len(to_analyze)}")

        # Шаг 2: загружаем описания только для отобранных
        enriched = searcher.enrich_with_descriptions(to_analyze)

        # Шаг 3: LLM-анализ
        analyses = analyzer.analyze_batch(enriched)

        _session["analyses"] = analyses
        _session["adapted"] = {}

        if not analyses:
            return (
                f"После pre-filter отобрано {len(to_analyze)} вакансий, "
                f"но ни одна не прошла порог релевантности {config.RELEVANCE_THRESHOLD}."
            )

        lines = [
            f"Всего найдено: {len(vacancies)} | После keyword-фильтра: {len(candidates)} "
            f"| LLM проанализировано: {len(to_analyze)} | Прошли порог: {len(analyses)}\n"
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
        analyses = _session.get("analyses", [])
        adapted_map = _session.get("adapted", {})
        exporter = _get_exporter()
        results = []

        # 1. Отчёт по вакансиям
        if analyses:
            path = exporter.export_analysis_pdf(analyses)
            if path:
                results.append(f"Отчёт:  {path}")
        else:
            results.append("Отчёт: нет данных (сначала выполни analyze_vacancies)")

        # 2. Резюме — берём первое адаптированное
        if adapted_map:
            adapted = next(iter(adapted_map.values()))
            path = exporter.export_resume_pdf(adapted)
            if path:
                results.append(f"Резюме: {path}")
        else:
            results.append("Резюме: не адаптировано (сначала выполни adapt_resume)")

        # 3. Сопроводительное письмо — читаем из сохранённого MD-файла
        cover_path = None
        if adapted_map and analyses:
            # Ищем последний сохранённый .md файл письма
            import config as _cfg
            cover_files = sorted(_cfg.OUTPUT_DIR.glob("cover_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
            if cover_files:
                letter_text = cover_files[0].read_text(encoding="utf-8")
                # Берём анализ для самого лучшего адаптированного
                best_id = next(iter(adapted_map))
                best_analysis = next((a for a in analyses if a.vacancy_id == best_id), analyses[0])
                path = exporter.export_cover_letter_pdf(letter_text, best_analysis)
                if path:
                    results.append(f"Письмо: {path}")
            else:
                results.append("Письмо: MD-файл не найден")
        else:
            results.append("Письмо: нет данных")

        return "PDF-пакет готов:\n" + "\n".join(results)
    except Exception as e:
        return f"Ошибка генерации PDF: {e}"


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
    export_all_pdf,
    get_session_state,
]
