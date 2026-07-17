# -*- coding: utf-8 -*-
"""
service.py — единый сервисный слой для AI Job Hunter.

Инкапсулирует workflow: search → analyze → adapt → cover → export.
Используется всеми интерфейсами: CLI (agent.py), Streamlit (app.py), API (api.py).
"""

import json
from pathlib import Path
from typing import Optional
from datetime import datetime

import config
from modules.searcher import JobSearcher, Vacancy
from modules.analyzer import VacancyAnalyzer, VacancyAnalysis
from modules.resume_adapter import ResumeAdapter
from modules.cover_letter import CoverLetterGenerator
from modules.exporter import Exporter


class JobHunterService:
    """
    Единый сервис поиска работы. Хранит состояние сессии и предоставляет
    методы для каждого этапа пайплайна.

    Использование:
        service = JobHunterService()
        vacancies = service.search("prompt engineer")
        analyses = service.analyze(vacancies, limit=20)
        adapted = service.adapt_resume(analyses[0])
        letter = service.generate_cover_letter(analyses[0], adapted)
        service.export_report(analyses)
        service.export_pdf_package(analyses[0], adapted, letter)
    """

    def __init__(self) -> None:
        # Состояние сессии
        self.vacancies: list[Vacancy] = []
        self.analyses: list[VacancyAnalysis] = []
        self.adapted_resumes: dict[str, dict] = {}  # vacancy_id -> резюме
        self.cover_letters: dict[str, str] = {}      # vacancy_id -> текст письма

        # Ленивая инициализация модулей
        self._searcher: Optional[JobSearcher] = None
        self._analyzer: Optional[VacancyAnalyzer] = None
        self._adapter: Optional[ResumeAdapter] = None
        self._cover_gen: Optional[CoverLetterGenerator] = None
        self._exporter: Optional[Exporter] = None

    # ── Ленивая инициализация ────────────────────────────────────────────────

    @property
    def searcher(self) -> JobSearcher:
        if not self._searcher:
            self._searcher = JobSearcher()
        return self._searcher

    @property
    def analyzer(self) -> VacancyAnalyzer:
        if not self._analyzer:
            if not config.validate_config():
                raise RuntimeError("OPENAI_API_KEY не задан в .env файле")
            self._analyzer = VacancyAnalyzer()
        return self._analyzer

    @property
    def adapter(self) -> ResumeAdapter:
        if not self._adapter:
            self._adapter = ResumeAdapter()
        return self._adapter

    @property
    def cover_gen(self) -> CoverLetterGenerator:
        if not self._cover_gen:
            self._cover_gen = CoverLetterGenerator()
        return self._cover_gen

    @property
    def exporter(self) -> Exporter:
        if not self._exporter:
            self._exporter = Exporter()
        return self._exporter

    # ── Поиск ────────────────────────────────────────────────────────────────

    def search(
        self,
        query: Optional[str] = None,
        pages: int = 2,
        include_habr: bool = True,
    ) -> list[Vacancy]:
        """
        Ищет вакансии на hh.ru и Habr Career.

        Args:
            query: Поисковый запрос. Если None — использует все запросы из config.
            pages: Количество страниц для загрузки
            include_habr: Искать ли на Habr Career

        Returns:
            Список найденных вакансий
        """
        if query:
            self.vacancies = self.searcher.search_hh(query, pages=pages)
            if include_habr:
                self.vacancies += self.searcher.search_habr(query, pages=pages)
                self.vacancies = self.searcher._dedup(self.vacancies)
        else:
            self.vacancies = self.searcher.search_all_queries(include_habr=include_habr)

        # Сбрасываем последующие результаты при новом поиске
        self.analyses = []
        self.adapted_resumes = {}
        self.cover_letters = {}

        return self.vacancies

    # ── Анализ ───────────────────────────────────────────────────────────────

    def analyze(
        self,
        vacancies: Optional[list[Vacancy]] = None,
        limit: int = 20,
    ) -> list[VacancyAnalysis]:
        """
        Анализирует вакансии через LLM.

        Двухэтапный процесс:
        1. Keyword pre-filter (без LLM) — быстрый отсев
        2. LLM-анализ отобранных вакансий

        Args:
            vacancies: Вакансии для анализа. Если None — использует результат поиска.
            limit: Максимум вакансий для LLM-анализа

        Returns:
            Список проанализированных вакансий, отсортированный по score
        """
        vacancies = vacancies or self.vacancies
        if not vacancies:
            raise RuntimeError("Нет вакансий для анализа. Сначала выполните поиск.")

        # Pre-filter
        pre_n = min(limit * 2, len(vacancies))
        candidates = self.analyzer.pre_filter(vacancies, top_n=pre_n)
        to_analyze = candidates[:limit]

        # Загружаем описания
        enriched = self.searcher.enrich_with_descriptions(to_analyze)

        # LLM-анализ
        self.analyses = self.analyzer.analyze_batch(enriched)
        self.adapted_resumes = {}
        self.cover_letters = {}

        return self.analyses

    # ── Адаптация резюме ─────────────────────────────────────────────────────

    def adapt_resume(self, analysis: VacancyAnalysis) -> dict:
        """
        Адаптирует резюме под конкретную вакансию.

        Args:
            analysis: Результат анализа вакансии

        Returns:
            Словарь с адаптированным резюме
        """
        adapted = self.adapter.adapt(analysis)
        self.adapter.save(adapted)
        self.adapted_resumes[analysis.vacancy_id] = adapted
        return adapted

    # ── Сопроводительное письмо ──────────────────────────────────────────────

    def generate_cover_letter(
        self,
        analysis: VacancyAnalysis,
        tone: str = "professional",
    ) -> str:
        """
        Генерирует сопроводительное письмо для вакансии.

        Args:
            analysis: Результат анализа вакансии
            tone: Тон письма (professional / friendly / concise)

        Returns:
            Текст письма
        """
        adapted = self.adapted_resumes.get(analysis.vacancy_id)
        letter = self.cover_gen.generate(analysis, adapted_resume=adapted, tone=tone)
        self.cover_gen.save(letter, analysis)
        self.cover_letters[analysis.vacancy_id] = letter
        return letter

    # ── Экспорт ──────────────────────────────────────────────────────────────

    def export_report(self, analyses: Optional[list[VacancyAnalysis]] = None) -> Path:
        """Создаёт Markdown-отчёт по результатам анализа."""
        analyses = analyses or self.analyses
        if not analyses:
            raise RuntimeError("Нет данных для отчёта.")
        return self.exporter.export_analysis_md(analyses)

    def export_pdf_package(
        self,
        analysis: VacancyAnalysis,
        adapted_resume: Optional[dict] = None,
        cover_letter: Optional[str] = None,
    ) -> dict[str, Optional[Path]]:
        """
        Создаёт PDF-пакет: отчёт + резюме + письмо.

        Returns:
            Словарь с путями к созданным файлам
        """
        results = {}

        # Отчёт
        if self.analyses:
            results["report"] = self.exporter.export_analysis_pdf(self.analyses)

        # Резюме
        adapted = adapted_resume or self.adapted_resumes.get(analysis.vacancy_id)
        if adapted:
            results["resume"] = self.exporter.export_resume_pdf(adapted)

        # Письмо
        letter = cover_letter or self.cover_letters.get(analysis.vacancy_id)
        if letter:
            results["cover"] = self.exporter.export_cover_letter_pdf(letter, analysis)

        return results

    # ── Полный цикл ──────────────────────────────────────────────────────────

    def run_full_cycle(self, query: str, analyze_limit: int = 20) -> dict:
        """
        Выполняет полный цикл: поиск → анализ → отчёт.

        Args:
            query: Поисковый запрос
            analyze_limit: Максимум вакансий для LLM-анализа

        Returns:
            Словарь с результатами каждого этапа
        """
        result = {
            "query": query,
            "vacancies_count": 0,
            "analyses_count": 0,
            "report_path": None,
            "top_vacancies": [],
        }

        # 1. Поиск
        vacancies = self.search(query)
        result["vacancies_count"] = len(vacancies)

        if not vacancies:
            return result

        # 2. Анализ
        analyses = self.analyze(limit=analyze_limit)
        result["analyses_count"] = len(analyses)

        if not analyses:
            return result

        # 3. Отчёт
        report_path = self.export_report()
        result["report_path"] = str(report_path)

        # 4. Топ вакансий
        result["top_vacancies"] = [
            {
                "title": a.vacancy_title,
                "company": a.company,
                "score": a.relevance_score,
                "recommendation": a.recommendation,
            }
            for a in analyses[:5]
        ]

        return result

    # ── Сохранение/загрузка сессии ───────────────────────────────────────────

    def save_session(self) -> Path:
        """Сохраняет текущую сессию в JSON."""
        config.OUTPUT_DIR.mkdir(exist_ok=True)
        data = {
            "saved_at": datetime.now().isoformat(),
            "analyses": [a.model_dump() for a in self.analyses],
        }
        path = config.OUTPUT_DIR / "session.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return path

    def load_session(self) -> int:
        """
        Загружает последнюю сессию из JSON.

        Returns:
            Количество загруженных анализов
        """
        path = config.OUTPUT_DIR / "session.json"
        if not path.exists():
            return 0
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.analyses = [VacancyAnalysis(**a) for a in data.get("analyses", [])]
            return len(self.analyses)
        except Exception:
            return 0
