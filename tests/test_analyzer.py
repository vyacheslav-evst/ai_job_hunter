# -*- coding: utf-8 -*-
"""
tests/test_analyzer.py — юнит-тесты для модуля анализа
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from modules.analyzer import VacancyAnalyzer, VacancyAnalysis
from modules.searcher import Vacancy


@pytest.fixture
def mock_analyzer(tmp_path):
    """Создаёт VacancyAnalyzer с моканным LLM и резюме."""
    resume = {
        "personal": {"name": "Test User", "telegram": "@test"},
        "target_roles": ["AI Engineer", "Prompt Engineer"],
        "experience_notes": "~2 месяца практики",
        "skills": {
            "prompt_engineering": ["Prompt Engineering", "JSON Schema"],
            "ai_development": ["OpenAI API", "LangChain"],
            "programming": ["Python 3.x"],
        },
        "projects": [
            {
                "name": "Test Project",
                "status": "active",
                "description": "Test description",
            }
        ],
    }
    resume_path = tmp_path / "base_resume.json"
    resume_path.write_text(json.dumps(resume), encoding="utf-8")

    with patch("config.BASE_RESUME_PATH", resume_path), \
         patch("config.OPENAI_API_KEY", "test-key"):
        analyzer = VacancyAnalyzer()
        analyzer.llm = MagicMock()
        return analyzer


def _make_vacancy(title="AI Engineer", company="TestCo", description="Test desc") -> Vacancy:
    return Vacancy(
        id="1", title=title, company=company,
        url="https://hh.ru/vacancy/1", description=description,
    )


class TestParseJsonResponse:
    def test_parse_clean_json(self, mock_analyzer):
        text = '{"score": 85, "recommendation": "APPLY"}'
        result = mock_analyzer._parse_json_response(text)
        assert result["score"] == 85
        assert result["recommendation"] == "APPLY"

    def test_parse_json_with_markdown(self, mock_analyzer):
        text = '```json\n{"score": 70}\n```'
        result = mock_analyzer._parse_json_response(text)
        assert result["score"] == 70

    def test_parse_json_with_text_around(self, mock_analyzer):
        text = 'Here is the result: {"score": 60} and some trailing text'
        result = mock_analyzer._parse_json_response(text)
        assert result["score"] == 60

    def test_parse_invalid_json(self, mock_analyzer):
        text = 'not json at all'
        result = mock_analyzer._parse_json_response(text)
        assert result is None

    def test_parse_empty_string(self, mock_analyzer):
        result = mock_analyzer._parse_json_response("")
        assert result is None


class TestBuildCandidateProfile:
    def test_profile_contains_name(self, mock_analyzer):
        profile = mock_analyzer._build_candidate_profile()
        assert "Test User" in profile

    def test_profile_contains_skills(self, mock_analyzer):
        profile = mock_analyzer._build_candidate_profile()
        assert "Prompt Engineering" in profile
        assert "Python" in profile


class TestAnalyzeVacancy:
    def test_returns_none_without_description(self, mock_analyzer):
        v = Vacancy(id="1", title="Test", company="Co", url="https://hh.ru/vacancy/1", description="")
        result = mock_analyzer.analyze_vacancy(v)
        assert result is None

    def test_parses_llm_response(self, mock_analyzer):
        v = _make_vacancy()
        mock_analyzer.llm.invoke.return_value = MagicMock(
            content=json.dumps({
                "relevance_score": 75,
                "match_level": "medium",
                "matching_skills": ["Python", "LLM"],
                "missing_skills": ["PyTorch"],
                "bonus_points": ["Strong Python"],
                "key_requirements": ["Python", "LLM API"],
                "main_tasks": ["Build AI agents"],
                "tech_stack": ["Python", "OpenAI"],
                "recommendation": "MAYBE",
                "reasoning": "Хорошее совпадение",
                "apply_tips": ["Покажи проекты"],
            })
        )
        result = mock_analyzer.analyze_vacancy(v)
        assert result is not None
        assert result.relevance_score == 75
        assert result.recommendation == "MAYBE"
        assert result.vacancy_id == "1"

    def test_returns_none_on_empty_llm_response(self, mock_analyzer):
        v = _make_vacancy()
        mock_analyzer.llm.invoke.return_value = MagicMock(content="")
        result = mock_analyzer.analyze_vacancy(v)
        assert result is None


class TestKeywordScoreEdgeCases:
    def test_junior_with_multiple_ai_keywords(self, mock_analyzer):
        v = _make_vacancy("Junior Prompt Engineer", "langchain, openai, rag, llm")
        score = mock_analyzer.keyword_score(v)
        assert score >= 60

    def test_unrelated_with_ai_word(self, mock_analyzer):
        """Должно быть 0 если вакансия — продавец (даже если в описании AI)."""
        v = _make_vacancy("Продавец", "Работа с AI клиентами")
        score = mock_analyzer.keyword_score(v)
        assert score == 0
