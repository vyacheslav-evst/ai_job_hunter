"""
company_analyzer.py — модуль анализа компании-работодателя.

Парсит публичную страницу работодателя на hh.ru и генерирует
краткий AI-дайджест: чем занимается, какой стек, культура, размер.
Помогает кандидату понять компанию перед откликом.
"""

import re
import time
import requests
import urllib3
from typing import Optional

from bs4 import BeautifulSoup

import config
from modules.llm_client import LLMClient

# Отключаем предупреждения SSL (VPN через Happ требует verify=False)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}


class CompanyAnalyzer:
    """
    Собирает публичную информацию о компании с hh.ru
    и генерирует краткий AI-дайджест через LLM.
    """

    HH_EMPLOYER_SEARCH = "https://hh.ru/search/employer"

    def __init__(self) -> None:
        self.llm = LLMClient()
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        print(f"[COMPANY] Инициализирован. Модель: {self.llm.model}")

    def _get(self, url: str, params: Optional[dict] = None) -> Optional[requests.Response]:
        """HTTP GET с retry/backoff и verify=False для VPN."""
        proxies = {}
        proxy = config.HTTPS_PROXY or config.HTTP_PROXY
        if proxy:
            proxies = {"http": proxy, "https": proxy}

        for attempt in range(3):
            try:
                resp = self.session.get(
                    url,
                    params=params,
                    timeout=15,
                    verify=False,
                    proxies=proxies or None,
                )
                if resp.status_code == 200:
                    return resp
                if resp.status_code in (429, 503):
                    wait = 2 ** attempt * 2
                    print(f"[COMPANY] {resp.status_code} — жду {wait}с")
                    time.sleep(wait)
            except Exception as e:
                print(f"[COMPANY] Ошибка запроса (попытка {attempt + 1}): {e}")
                time.sleep(2)
        return None

    def _find_employer_id(self, company_name: str) -> Optional[str]:
        """
        Ищет ID работодателя на hh.ru по названию компании.

        Returns:
            employer_id как строку или None
        """
        resp = self._get(self.HH_EMPLOYER_SEARCH, params={"text": company_name})
        if not resp:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        # Ищем ссылку на страницу работодателя
        link = soup.find("a", href=re.compile(r"/employer/\d+"))
        if link:
            match = re.search(r"/employer/(\d+)", link["href"])
            if match:
                return match.group(1)
        return None

    def _scrape_employer_page(self, employer_id: str) -> Optional[str]:
        """
        Парсит страницу работодателя на hh.ru.

        Returns:
            Текстовое описание компании или None
        """
        url = f"https://hh.ru/employer/{employer_id}"
        resp = self._get(url)
        if not resp:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        parts = []

        # Название компании
        name_tag = soup.find("h1", {"data-qa": "bloko-header-1"}) or soup.find("h1")
        if name_tag:
            parts.append(f"Компания: {name_tag.get_text(strip=True)}")

        # Описание (несколько возможных селекторов)
        for selector in [
            {"data-qa": "employer-description"},
            {"class": re.compile(r"employer-description")},
            {"class": re.compile(r"company-description")},
        ]:
            desc = soup.find(attrs=selector)
            if desc:
                text = desc.get_text(separator=" ", strip=True)[:2000]
                parts.append(f"Описание: {text}")
                break

        # Отрасль / сфера
        industry = soup.find(attrs={"data-qa": "employer-industries"})
        if industry:
            parts.append(f"Отрасль: {industry.get_text(strip=True)}")

        # Размер компании
        size = soup.find(attrs={"data-qa": "employer-employees-count"})
        if size:
            parts.append(f"Размер: {size.get_text(strip=True)}")

        # Сайт
        site = soup.find("a", attrs={"data-qa": "employer-site"})
        if site:
            parts.append(f"Сайт: {site.get('href', '')}")

        return "\n".join(parts) if parts else None

    def analyze(self, company_name: str, vacancy_title: str = "") -> Optional[dict]:
        """
        Основной метод: ищет компанию на hh.ru и генерирует AI-дайджест.

        Args:
            company_name: Название компании
            vacancy_title: Название вакансии (для контекста)

        Returns:
            Словарь с ключами:
              - summary: краткое описание компании
              - what_they_do: чем занимается
              - tech_hints: технологии/стек если упомянуты
              - culture_hints: культура/условия если упомянуты
              - employer_url: ссылка на страницу hh
            или None при ошибке
        """
        print(f"[COMPANY] Анализирую: {company_name}")

        # Шаг 1: ищем ID работодателя
        employer_id = self._find_employer_id(company_name)
        employer_url = f"https://hh.ru/employer/{employer_id}" if employer_id else None

        # Шаг 2: парсим страницу
        raw_info = None
        if employer_id:
            raw_info = self._scrape_employer_page(employer_id)
            print(f"[COMPANY] Страница получена: {len(raw_info or '')} символов")
        else:
            print(f"[COMPANY] ID работодателя не найден — генерирую только по названию")

        # Шаг 3: LLM-дайджест
        context = raw_info or f"Компания: {company_name}"
        prompt = f"""Ты — карьерный консультант. На основе информации о компании составь краткий дайджест для кандидата.

## ИНФОРМАЦИЯ О КОМПАНИИ
{context}

## ВАКАНСИЯ
{vacancy_title or 'не указана'}

## ЗАДАЧА
Верни ТОЛЬКО валидный JSON без ```json:
{{
  "summary": "2-3 предложения: чем занимается компания, масштаб, ниша",
  "what_they_do": "Основная деятельность (1 предложение)",
  "tech_hints": "Технологии/стек если упомянуты, иначе пустая строка",
  "culture_hints": "Культура, условия, преимущества если упомянуты, иначе пустая строка",
  "red_flags": "Тревожные сигналы если есть, иначе пустая строка"
}}

Отвечай на русском языке. Если информации мало — пиши честно "информация недоступна"."""

        try:
            result = self.llm.chat_json(prompt)
            if not result:
                raw = self.llm.chat(prompt, temperature=0.3)
                result = self._parse_json(raw) if raw else None

            if result:
                result["employer_url"] = employer_url
                result["company_name"] = company_name
                print(f"[COMPANY] Дайджест готов для: {company_name}")
                return result

        except Exception as e:
            print(f"[COMPANY] Ошибка LLM: {e}")

        return None

    def _parse_json(self, text: str) -> Optional[dict]:
        """Парсит JSON из текста (убирает markdown-обёртку)."""
        import json
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text).strip()
        try:
            return json.loads(text)
        except Exception:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    import json as _json
                    return _json.loads(match.group())
                except Exception:
                    pass
        return None
