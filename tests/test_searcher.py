# -*- coding: utf-8 -*-
"""
tests/test_searcher.py — юнит-тесты для модуля поиска
"""

import pytest
from modules.searcher import JobSearcher, Vacancy


@pytest.fixture
def searcher():
    return JobSearcher()


class TestVacancy:
    def test_salary_str_range(self):
        v = Vacancy(id="1", title="Test", company="Co", url="https://hh.ru/vacancy/1",
                    salary_from=80_000, salary_to=120_000, salary_currency="RUB")
        assert "80" in v.salary_str()
        assert "120" in v.salary_str()

    def test_salary_str_from_only(self):
        v = Vacancy(id="1", title="Test", company="Co", url="https://hh.ru/vacancy/1",
                    salary_from=100_000, salary_currency="RUB")
        s = v.salary_str()
        assert "100" in s
        assert s != "не указана"

    def test_salary_str_none(self):
        """Если зарплата не указана — строка не пустая и не содержит цифр."""
        v = Vacancy(id="1", title="Test", company="Co", url="https://hh.ru/vacancy/1")
        s = v.salary_str()
        assert len(s) > 0
        assert not any(c.isdigit() for c in s)

    def test_source_default(self):
        v = Vacancy(id="1", title="Test", company="Co", url="https://hh.ru/vacancy/1")
        assert v.source == "hh.ru"


class TestFilters:
    def test_noise_title_filtered(self, searcher):
        """NOISE_TITLE_KEYWORDS не пустой и содержит хотя бы несколько слов."""
        assert len(searcher.NOISE_TITLE_KEYWORDS) >= 3
        for kw in searcher.NOISE_TITLE_KEYWORDS:
            assert isinstance(kw, str)
            assert len(kw) > 0

    def test_senior_title_filtered(self, searcher):
        """Senior-вакансия должна отфильтровываться."""
        title = "Senior AI Engineer"
        title_lower = title.lower()
        assert any(kw in title_lower for kw in searcher.SENIOR_TITLE_KEYWORDS)

    def test_junior_title_passes(self, searcher):
        """Junior-вакансия не должна отфильтровываться."""
        title = "Junior AI Engineer"
        title_lower = title.lower()
        noise = any(kw in title_lower for kw in searcher.NOISE_TITLE_KEYWORDS)
        senior = any(kw in title_lower for kw in searcher.SENIOR_TITLE_KEYWORDS)
        assert not noise
        assert not senior


class TestSalaryParsing:
    def test_parse_salary_range_usd(self, searcher):
        """Парсинг диапазона зарплат в USD."""
        f, t, c = searcher._parse_salary_text("от 4000 до 6000 $")
        assert f == 4000
        assert t == 6000
        assert c == "USD"

    def test_parse_salary_from_only_rub(self, searcher):
        """Парсинг зарплаты 'от X' в RUB."""
        f, t, c = searcher._parse_salary_text("от 150 000 ₽")
        assert f == 150000
        assert t is None
        assert c == "RUB"

    def test_parse_salary_to_only(self, searcher):
        """Парсинг зарплаты 'до X'."""
        f, t, c = searcher._parse_salary_text("до 200 000 руб.")
        assert f is None
        assert t == 200000
        assert c == "RUB"

    def test_parse_salary_range_eur(self, searcher):
        """Парсинг диапазона в EUR."""
        f, t, c = searcher._parse_salary_text("3000 – 5000 €")
        assert f == 3000
        assert t == 5000
        assert c == "EUR"

    def test_parse_salary_empty(self, searcher):
        """Пустая строка зарплаты."""
        f, t, c = searcher._parse_salary_text("")
        assert f is None
        assert t is None
        assert c is None

    def test_parse_salary_none(self, searcher):
        """None зарплата."""
        f, t, c = searcher._parse_salary_text(None)
        assert f is None


class TestConfig:
    def test_profession_presets_not_empty(self):
        import config
        assert len(config.PROFESSION_PRESETS) >= 4
        for name, queries in config.PROFESSION_PRESETS.items():
            assert len(queries) >= 3, f"Пресет '{name}' содержит меньше 3 запросов"

    def test_active_profession_valid(self):
        import config
        assert config.ACTIVE_PROFESSION in config.PROFESSION_PRESETS
        assert len(config.SEARCH_QUERIES) >= 3


class TestKeywordScore:
    """Тесты для быстрого keyword-скоринга без LLM."""

    @pytest.fixture
    def analyzer(self, tmp_path, monkeypatch):
        """Создаёт VacancyAnalyzer с моканным LLM и резюме."""
        import json
        from unittest.mock import MagicMock, patch

        # Создаём минимальное резюме
        resume = {
            "personal": {"name": "Test"},
            "target_roles": ["AI Engineer"],
            "skills": {"prompt_engineering": ["Prompt Engineering"]},
            "projects": [],
        }
        resume_path = tmp_path / "base_resume.json"
        resume_path.write_text(json.dumps(resume), encoding="utf-8")

        # Мокаем config чтобы не требовать реальный API-ключ
        with patch("config.BASE_RESUME_PATH", resume_path), \
             patch("config.OPENAI_API_KEY", "test-key"):
            from modules.analyzer import VacancyAnalyzer
            analyzer = VacancyAnalyzer()
            # Мокаем LLM чтобы не делать реальных вызовов
            analyzer.llm = MagicMock()
            return analyzer

    def _make_vacancy(self, title: str, requirements: str = "") -> Vacancy:
        return Vacancy(id="1", title=title, company="Test", url="https://hh.ru/vacancy/1",
                       requirements=requirements)

    def test_high_score_for_llm_engineer(self, analyzer):
        v = self._make_vacancy("LLM Engineer", "langchain, openai, python")
        score = analyzer.keyword_score(v)
        assert score >= 50

    def test_high_score_for_prompt_engineer(self, analyzer):
        v = self._make_vacancy("Prompt Engineer (AI)", "gpt, claude, rag")
        score = analyzer.keyword_score(v)
        assert score >= 40

    def test_zero_for_unrelated(self, analyzer):
        v = self._make_vacancy("Водитель погрузчика", "права категории B")
        score = analyzer.keyword_score(v)
        assert score == 0

    def test_penalty_for_senior(self, analyzer):
        v_junior = self._make_vacancy("Junior AI Engineer", "python, llm")
        v_senior = self._make_vacancy("Senior AI Engineer", "python, llm")
        assert analyzer.keyword_score(v_junior) > analyzer.keyword_score(v_senior)

    def test_bonus_for_junior_marker(self, analyzer):
        v_no_marker = self._make_vacancy("AI Engineer", "python, llm")
        v_junior = self._make_vacancy("Junior AI Engineer", "python, llm")
        assert analyzer.keyword_score(v_junior) >= analyzer.keyword_score(v_no_marker)

    def test_pre_filter_returns_sorted(self, analyzer):
        vacancies = [
            self._make_vacancy("Водитель", ""),
            self._make_vacancy("LLM Engineer", "langchain openai"),
            self._make_vacancy("Prompt Engineer", "gpt claude"),
            self._make_vacancy("Бухгалтер", "1С"),
        ]
        result = analyzer.pre_filter(vacancies, top_n=10)
        assert len(result) == 2  # только AI-вакансии
        s0 = analyzer.keyword_score(result[0])
        s1 = analyzer.keyword_score(result[1])
        assert s0 >= s1


class TestDedup:
    def test_dedup_by_id(self, searcher):
        """Дубли по ID удаляются."""
        v1 = Vacancy(id="1", title="AI Engineer", company="Co", url="https://hh.ru/vacancy/1")
        v2 = Vacancy(id="1", title="AI Engineer", company="Co", url="https://hh.ru/vacancy/1")
        result = searcher._dedup([v1, v2])
        assert len(result) == 1

    def test_dedup_by_title_company(self, searcher):
        """Дубли по title+company удаляются (разные источники)."""
        v1 = Vacancy(id="1", title="AI Engineer", company="TechCorp", url="https://hh.ru/vacancy/1")
        v2 = Vacancy(id="habr_999", title="AI Engineer", company="TechCorp", url="https://career.habr.com/vacancies/999")
        result = searcher._dedup([v1, v2])
        assert len(result) == 1

    def test_different_vacancies_kept(self, searcher):
        """Разные вакансии не удаляются."""
        v1 = Vacancy(id="1", title="AI Engineer", company="Co1", url="https://hh.ru/vacancy/1")
        v2 = Vacancy(id="2", title="Prompt Engineer", company="Co2", url="https://hh.ru/vacancy/2")
        result = searcher._dedup([v1, v2])
        assert len(result) == 2
