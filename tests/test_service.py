# -*- coding: utf-8 -*-
"""
tests/test_service.py — юнит-тесты для сервисного слоя
"""

import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from modules.searcher import Vacancy
from modules.analyzer import VacancyAnalysis
from modules.service import JobHunterService


@pytest.fixture
def service(tmp_path):
    """Создаёт JobHunterService с моканными зависимостями."""
    resume = {
        "personal": {"name": "Test", "telegram": "@test", "email_primary": "test@test.com"},
        "target_roles": ["AI Engineer"],
        "skills": {"prompt_engineering": ["Prompt Engineering"]},
        "projects": [],
    }
    resume_path = tmp_path / "base_resume.json"
    resume_path.write_text(json.dumps(resume), encoding="utf-8")

    with patch("config.BASE_RESUME_PATH", resume_path), \
         patch("config.OPENAI_API_KEY", "test-key"), \
         patch("config.OUTPUT_DIR", tmp_path):
        svc = JobHunterService()
        return svc


def _make_vacancy(id="1", title="AI Engineer", company="TestCo") -> Vacancy:
    return Vacancy(id=id, title=title, company=company, url=f"https://hh.ru/vacancy/{id}")


def _make_analysis(score=75) -> VacancyAnalysis:
    return VacancyAnalysis(
        vacancy_id="1",
        vacancy_title="AI Engineer",
        company="TestCo",
        relevance_score=score,
        match_level="high" if score >= 70 else "medium",
        recommendation="APPLY" if score >= 70 else "MAYBE",
        reasoning="Test reasoning",
        matching_skills=["Python"],
        missing_skills=[],
        bonus_points=[],
        key_requirements=["Python"],
        main_tasks=["Build AI"],
        tech_stack=["Python"],
        apply_tips=["Show projects"],
    )


class TestServiceSearch:
    def test_search_stores_vacancies(self, service):
        """Поиск сохраняет вакансии в состоянии."""
        vacancies = [_make_vacancy(), _make_vacancy(id="2", title="Prompt Engineer")]
        mock_searcher = MagicMock()
        mock_searcher.search_hh.return_value = vacancies
        mock_searcher.search_habr.return_value = []
        mock_searcher._dedup.return_value = vacancies
        service._searcher = mock_searcher

        result = service.search("test query")
        assert len(result) == 2
        assert len(service.vacancies) == 2

    def test_search_resets_analyses(self, service):
        """Новый поиск сбрасывает предыдущие анализы."""
        service.analyses = [_make_analysis()]
        mock_searcher = MagicMock()
        mock_searcher.search_hh.return_value = []
        mock_searcher.search_habr.return_value = []
        mock_searcher._dedup.return_value = []
        service._searcher = mock_searcher

        service.search("test")
        assert service.analyses == []


class TestServiceSaveLoadSession:
    def test_save_and_load_session(self, service, tmp_path):
        """Сохранение и загрузка сессии работают корректно."""
        service.analyses = [_make_analysis()]
        path = service.save_session()
        assert path.exists()

        # Загружаем в новый сервис (используем тот же tmp_path)
        service2 = JobHunterService()
        service2._searcher = MagicMock()  # чтобы не создавать реальный searcher
        count = service2.load_session()
        assert count == 1
        assert service2.analyses[0].vacancy_id == "1"

    def test_load_nonexistent_session(self, tmp_path):
        """Загрузка несуществующей сессии возвращает 0."""
        with patch("config.OUTPUT_DIR", tmp_path / "nonexistent"):
            svc = JobHunterService()
            count = svc.load_session()
            assert count == 0


class TestServiceExport:
    def test_export_report_without_analyses_raises(self, service):
        """Экспорт отчёта без анализов выбрасывает ошибку."""
        with pytest.raises(RuntimeError, match="Нет данных"):
            service.export_report()
