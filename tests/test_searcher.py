"""
tests/test_searcher.py — юнит-тесты для модуля поиска
"""

import re
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
        assert "от" in v.salary_str()

    def test_salary_str_none(self):
        v = Vacancy(id="1", title="Test", company="Co", url="https://hh.ru/vacancy/1")
        assert v.salary_str() == "не указана"

    def test_source_default(self):
        v = Vacancy(id="1", title="Test", company="Co", url="https://hh.ru/vacancy/1")
        assert v.source == "hh.ru"


class TestFilters:
    def test_noise_title_filtered(self, searcher):
        """Вакансия с мусорным заголовком должна отфильтровываться."""
        title = "Водитель погрузчика"
        title_lower = title.lower()
        assert any(kw in title_lower for kw in searcher.NOISE_TITLE_KEYWORDS)

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
    def test_parse_habr_salary_range_usd(self, searcher):
        """Парсинг диапазона зарплат в USD с Habr."""
        from bs4 import BeautifulSoup
        html = '<div class="card"><div class="basic-salary">от 4000 до 6000 $</div></div>'
        soup = BeautifulSoup(html, "lxml")
        card = soup.find("div", class_="card")
        salary_from, salary_to, currency = searcher._parse_habr_salary(card)
        assert salary_from == 4000
        assert salary_to == 6000
        assert currency == "USD"

    def test_parse_habr_salary_from_only(self, searcher):
        """Парсинг зарплаты 'от X' с Habr."""
        from bs4 import BeautifulSoup
        html = '<div class="card"><div class="basic-salary">от 150 000 ₽</div></div>'
        soup = BeautifulSoup(html, "lxml")
        card = soup.find("div", class_="card")
        salary_from, salary_to, currency = searcher._parse_habr_salary(card)
        assert salary_from == 150000
        assert salary_to is None
        assert currency == "RUB"


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
