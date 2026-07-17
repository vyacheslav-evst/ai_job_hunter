# -*- coding: utf-8 -*-
"""
tests/test_exporter.py — юнит-тесты для модуля экспорта
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch
from modules.exporter import Exporter
from modules.analyzer import VacancyAnalysis


@pytest.fixture
def exporter(tmp_path):
    """Создаёт Exporter с временной output-директорией."""
    with patch("config.OUTPUT_DIR", tmp_path):
        exp = Exporter()
        yield exp


def _make_analysis(score=75, recommendation="APPLY") -> VacancyAnalysis:
    return VacancyAnalysis(
        vacancy_id="test_001",
        vacancy_title="Prompt Engineer",
        company="TechCorp",
        relevance_score=score,
        match_level="high" if score >= 70 else "medium" if score >= 45 else "low",
        recommendation=recommendation,
        reasoning="Тестовое описание",
        matching_skills=["Python", "LLM API"],
        missing_skills=["PyTorch"],
        bonus_points=["Strong project"],
        key_requirements=["Python", "LLM"],
        main_tasks=["Build agents"],
        tech_stack=["Python", "OpenAI"],
        apply_tips=["Покажи проекты"],
    )


class TestExportAnalysisMd:
    def test_creates_file(self, exporter, tmp_path):
        analyses = [_make_analysis()]
        path = exporter.export_analysis_md(analyses)
        assert Path(path).exists()

    def test_contains_analysis_data(self, exporter, tmp_path):
        analyses = [_make_analysis(score=85, recommendation="APPLY")]
        path = exporter.export_analysis_md(analyses)
        content = Path(path).read_text(encoding="utf-8")
        assert "Prompt Engineer" in content
        assert "TechCorp" in content
        assert "85" in content
        assert "APPLY" in content

    def test_groups_by_recommendation(self, exporter, tmp_path):
        analyses = [
            _make_analysis(score=85, recommendation="APPLY"),
            _make_analysis(score=55, recommendation="MAYBE"),
            _make_analysis(score=25, recommendation="SKIP"),
        ]
        path = exporter.export_analysis_md(analyses)
        content = Path(path).read_text(encoding="utf-8")
        assert "APPLY" in content
        assert "MAYBE" in content
        assert "SKIP" in content


class TestExportResumeMd:
    def test_creates_file(self, exporter, tmp_path):
        adapted = {
            "vacancy_title": "AI Engineer",
            "company": "TestCo",
            "adapted_summary": "Test summary",
            "top_skills": ["Python", "LLM"],
            "featured_projects": [],
            "additional_skills": [],
            "personal": {"name": "Test", "telegram": "@test", "email_primary": "test@test.com"},
            "education": {"formal": "Test"},
            "generated_at": "2025-01-01",
        }
        path = exporter.export_resume_md(adapted)
        assert Path(path).exists()
        content = Path(path).read_text(encoding="utf-8")
        assert "Test" in content
        assert "AI Engineer" in content


class TestExportResumePdf:
    def test_creates_pdf(self, exporter, tmp_path):
        """PDF создаётся если fpdf2 установлен."""
        adapted = {
            "vacancy_title": "AI Engineer",
            "company": "TestCo",
            "adapted_summary": "Test summary for PDF",
            "top_skills": ["Python", "LLM"],
            "featured_projects": [
                {"name": "Project1", "description": "Desc1", "highlights": ["H1"]}
            ],
            "additional_skills": [],
            "personal": {"name": "Test"},
            "education": {"formal": "Test"},
            "generated_at": "2025-01-01",
        }
        path = exporter.export_resume_pdf(adapted)
        if path:  # может быть None если fpdf2 не установлен
            assert Path(path).exists()
            assert Path(path).suffix == ".pdf"
