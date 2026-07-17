# -*- coding: utf-8 -*-
"""
searcher.py — модуль поиска вакансий
Источники: hh.ru (web scraping), Habr Career (web scraping)

hh.ru заблокировал прямые API-запросы без OAuth-авторизации,
поэтому используем парсинг HTML-страниц через BeautifulSoup.
"""

import re
import time
import json
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional
from bs4 import BeautifulSoup
from pydantic import BaseModel, ValidationError

import config


# ─── Модель вакансии (Pydantic) ──────────────────────────────────────────────

class Vacancy(BaseModel):
    """Структура одной вакансии после парсинга."""

    id: str
    title: str
    company: str
    url: str
    salary_from: Optional[int] = None
    salary_to: Optional[int] = None
    salary_currency: Optional[str] = None
    location: str = "Не указано"
    remote: bool = False
    description: str = ""
    requirements: str = ""
    published_at: str = ""
    source: str = "hh.ru"

    def salary_str(self) -> str:
        """Возвращает зарплату в читаемом виде."""
        if self.salary_from and self.salary_to:
            return f"{self.salary_from:,}–{self.salary_to:,} {self.salary_currency or 'RUB'}"
        elif self.salary_from:
            return f"от {self.salary_from:,} {self.salary_currency or 'RUB'}"
        elif self.salary_to:
            return f"до {self.salary_to:,} {self.salary_currency or 'RUB'}"
        return "не указана"


# ─── Основной класс поисковика ───────────────────────────────────────────────

class JobSearcher:
    """
    Ищет вакансии на hh.ru и Habr Career через парсинг HTML.
    Представляется как обычный браузер.
    """

    HH_SEARCH_URL = "https://hh.ru/search/vacancy"
    HH_VACANCY_URL = "https://hh.ru/vacancy/{}"

    HABR_SEARCH_URL = "https://career.habr.com/vacancies"
    HABR_BASE_URL = "https://career.habr.com"

    # Путь к файлу кэша описаний вакансий
    DESCRIPTIONS_CACHE_PATH = config.OUTPUT_DIR / "descriptions_cache.json"

    # Слова в названии вакансии, которые точно не AI/prompt — фильтруем как мусор
    NOISE_TITLE_KEYWORDS = [
        "менеджер отдела продаж", "тендерный специалист", "бухгалтер",
        "водитель", "кладовщик", "сварщик", "охранник", "продавец",
        "юрист", "экономист", "логист", "секретарь",
        "графический дизайнер", "graphic designer",
    ]

    # Слова в названии, указывающие на уровень выше джуна — отсекаем до анализа
    SENIOR_TITLE_KEYWORDS = [
        "senior", "ведущий", "lead", "team lead", "teamlead",
        "principal", "staff ", "архитект",
    ]

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        # Кэш описаний: vacancy_id -> описание (загружается с диска при старте)
        self._desc_cache: dict[str, str] = self._load_desc_cache()

    # ─── Кэш описаний вакансий ───────────────────────────────────────────────

    def _load_desc_cache(self) -> dict[str, str]:
        """Загружает кэш описаний из файла."""
        if self.DESCRIPTIONS_CACHE_PATH.exists():
            try:
                with open(self.DESCRIPTIONS_CACHE_PATH, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_desc_cache(self) -> None:
        """Сохраняет кэш описаний на диск."""
        config.OUTPUT_DIR.mkdir(exist_ok=True)
        with open(self.DESCRIPTIONS_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(self._desc_cache, f, ensure_ascii=False, indent=2)

    # ─── HTTP-запрос с retry/backoff ─────────────────────────────────────────

    def _get_with_retry(
        self,
        url: str,
        params: Optional[dict] = None,
        timeout: int = 15,
        verify: bool = True,
        max_retries: int = 3,
    ) -> Optional[requests.Response]:
        """
        GET-запрос с exponential backoff при ошибках 403/429/503/ConnectionError.

        Args:
            url: URL запроса
            params: Query-параметры
            timeout: Таймаут в секундах
            verify: Проверять SSL (False для Habr через VPN)
            max_retries: Максимальное число повторных попыток

        Returns:
            Response или None если все попытки исчерпаны
        """
        for attempt in range(max_retries):
            try:
                response = self.session.get(url, params=params, timeout=timeout, verify=verify)

                # 429 Too Many Requests — ждём и повторяем
                if response.status_code == 429:
                    wait = 2 ** attempt * 3  # 3, 6, 12 секунд
                    print(f"  [RATE LIMIT] 429 — ждём {wait}с (попытка {attempt + 1}/{max_retries})")
                    time.sleep(wait)
                    continue

                # 403 Forbidden (hh.ru блокирует) — longer backoff
                if response.status_code == 403:
                    wait = 2 ** attempt * 5  # 5, 10, 20 секунд
                    print(f"  [BLOCKED] 403 — ждём {wait}с (попытка {attempt + 1}/{max_retries})")
                    time.sleep(wait)
                    continue

                # 503 Service Unavailable — короткая пауза и повтор
                if response.status_code == 503:
                    wait = 2 ** attempt * 2  # 2, 4, 8 секунд
                    print(f"  [503] Сервис недоступен — ждём {wait}с (попытка {attempt + 1}/{max_retries})")
                    time.sleep(wait)
                    continue

                response.raise_for_status()
                return response

            except requests.exceptions.ConnectionError as e:
                wait = 2 ** attempt * 2
                print(f"  [CONN ERROR] попытка {attempt + 1}/{max_retries} — ждём {wait}с: {e}")
                time.sleep(wait)
            except requests.exceptions.Timeout:
                print(f"  [TIMEOUT] попытка {attempt + 1}/{max_retries}")
                time.sleep(2 ** attempt)
            except requests.exceptions.RequestException as e:
                print(f"  [ОШИБКА] {e}")
                return None  # прочие ошибки — не повторяем

        print(f"  [FAIL] Все {max_retries} попытки исчерпаны для {url}")
        return None

    def _parse_salary_text(self, text: str) -> tuple[Optional[int], Optional[int], Optional[str]]:
        """
        Универсальный парсинг текста зарплаты.
        Примеры: "от 80 000 RUB", "80 000–120 000 ₽", "до 200 000 руб.",
                 "от 4000 до 6000 $", "150 000 €"

        Returns:
            Кортеж (salary_from, salary_to, currency)
        """
        if not text:
            return None, None, None

        # Убираем неразрывные пробелы и прочий мусор
        text = text.replace("\xa0", " ").replace("\u2009", " ").strip()

        # Определяем валюту
        if "$" in text or "USD" in text:
            currency = "USD"
        elif "€" in text or "EUR" in text:
            currency = "EUR"
        else:
            currency = "RUB"

        # Извлекаем числа
        numbers = re.findall(r"[\d][\d ]*", text)
        numbers = [int(n.replace(" ", "")) for n in numbers if n.strip()]

        salary_from = salary_to = None

        if "от" in text.lower() and "до" in text.lower() and len(numbers) >= 2:
            salary_from, salary_to = numbers[0], numbers[1]
        elif "от" in text.lower() and numbers:
            salary_from = numbers[0]
        elif "до" in text.lower() and numbers:
            salary_to = numbers[0]
        elif len(numbers) >= 2:
            salary_from, salary_to = numbers[0], numbers[1]
        elif len(numbers) == 1:
            salary_from = numbers[0]

        return salary_from, salary_to, currency

    # ─── Поиск на hh.ru ─────────────────────────────────────────────────────

    def search_hh(
        self,
        query: str,
        area: int = config.SEARCH_AREA,
        only_remote: bool = config.SEARCH_ONLY_REMOTE,
        pages: int = 2,
    ) -> list[Vacancy]:
        """
        Ищет вакансии на hh.ru по поисковому запросу.

        Args:
            query: Поисковый запрос (например "prompt engineer")
            area: Регион (113 = вся Россия, 1 = Москва, 2 = СПб)
            only_remote: Только удалённая работа
            pages: Сколько страниц загружать (на каждой ~20 вакансий)

        Returns:
            Список объектов Vacancy
        """
        print(f"[ПОИСК] hh.ru: '{query}' | регион: {area} | удалённо: {only_remote}")

        vacancies = []

        for page in range(pages):
            params = {
                "text": query,
                "area": area,
                "page": page,
                "items_on_page": 20,
                "order_by": "publication_time",  # сначала свежие
            }
            if only_remote:
                params["schedule"] = "remote"

            response = self._get_with_retry(self.HH_SEARCH_URL, params=params)
            if response is None:
                break

            soup = BeautifulSoup(response.text, "lxml")

            # hh.ru рендерит карточки с атрибутом data-qa="vacancy-serp__vacancy"
            cards = soup.find_all("div", attrs={"data-qa": "vacancy-serp__vacancy"})

            if not cards:
                print(f"  [СТОП] Страница {page + 1}: карточек не найдено")
                break

            print(f"  [СТР {page + 1}] Найдено карточек: {len(cards)}")

            for card in cards:
                vacancy = self._parse_card(card)
                if vacancy:
                    vacancies.append(vacancy)

            # Пауза чтобы не триггерить защиту от ботов
            time.sleep(1.0)

        print(f"[ИТОГО] '{query}': {len(vacancies)} вакансий")

        return self._dedup(vacancies)

    def _parse_card(self, card) -> Optional[Vacancy]:
        """
        Парсит одну карточку вакансии из HTML.
        Структура hh.ru может меняться — код покрывает основные варианты.
        """
        try:
            # Название и ссылка
            title_tag = card.find("a", attrs={"data-qa": "serp-item__title"})
            if not title_tag:
                return None

            title = title_tag.get_text(strip=True)
            url = title_tag.get("href", "")

            # Извлекаем ID вакансии из URL
            id_match = re.search(r"/vacancy/(\d+)", url)
            if not id_match:
                return None
            vacancy_id = id_match.group(1)

            # Полный URL (иногда приходит без домена)
            if url.startswith("/"):
                url = f"https://hh.ru{url}"

            # Компания
            company_tag = card.find("a", attrs={"data-qa": "vacancy-serp__vacancy-employer"})
            if not company_tag:
                company_tag = card.find("span", attrs={"data-qa": "vacancy-serp__vacancy-employer"})
            company = company_tag.get_text(strip=True) if company_tag else "Не указана"

            # Зарплата
            salary_tag = card.find("span", attrs={"data-qa": "vacancy-serp__vacancy-compensation"})
            salary_text = salary_tag.get_text(strip=True) if salary_tag else ""
            salary_from, salary_to, salary_currency = self._parse_salary_text(salary_text)

            # Локация
            location_tag = card.find("div", attrs={"data-qa": "vacancy-serp__vacancy-address"})
            location = location_tag.get_text(strip=True) if location_tag else "Не указано"

            # Удалённость
            schedule_tags = card.find_all(string=re.compile(r"удалённ|remote", re.IGNORECASE))
            is_remote = len(schedule_tags) > 0

            vacancy = Vacancy(
                id=vacancy_id,
                title=title,
                company=company,
                url=url,
                salary_from=salary_from,
                salary_to=salary_to,
                salary_currency=salary_currency,
                location=location,
                remote=is_remote,
                source="hh.ru",
            )

            # Фильтруем явный мусор по названию вакансии
            title_lower = title.lower()
            if any(kw in title_lower for kw in self.NOISE_TITLE_KEYWORDS):
                return None

            # Фильтруем Senior/Lead/Ведущий — кандидат джун, такие вакансии не подходят
            if any(kw in title_lower for kw in self.SENIOR_TITLE_KEYWORDS):
                return None

            return vacancy

        except (AttributeError, ValidationError):
            return None  # тихо пропускаем битые карточки

    # ─── Поиск на Habr Career ───────────────────────────────────────────────

    def search_habr(
        self,
        query: str,
        pages: int = 2,
    ) -> list[Vacancy]:
        """
        Ищет вакансии на Habr Career по поисковому запросу.

        Args:
            query: Поисковый запрос (например "AI engineer")
            pages: Сколько страниц загружать (на каждой ~25 вакансий)

        Returns:
            Список объектов Vacancy
        """
        import urllib3
        urllib3.disable_warnings()

        print(f"[ПОИСК] Habr Career: '{query}'")

        vacancies = []

        for page in range(1, pages + 1):
            params = {
                "q": query,
                "type": "all",
                "page": page,
            }

            response = self._get_with_retry(
                self.HABR_SEARCH_URL, params=params, verify=False
            )
            if response is None:
                break

            soup = BeautifulSoup(response.text, "lxml")
            cards = soup.find_all("div", class_="vacancy-card")

            if not cards:
                print(f"  [СТОП] Habr страница {page}: карточек не найдено")
                break

            print(f"  [СТР {page}] Habr: найдено карточек: {len(cards)}")

            for card in cards:
                vacancy = self._parse_habr_card(card)
                if vacancy:
                    vacancies.append(vacancy)

            time.sleep(1.0)

        print(f"[ИТОГО] Habr '{query}': {len(vacancies)} вакансий")
        return self._dedup(vacancies)

    def _parse_habr_card(self, card) -> Optional[Vacancy]:
        """Парсит одну карточку вакансии с Habr Career."""
        try:
            # Название и ссылка
            title_tag = card.find("a", class_="vacancy-card__title-link")
            if not title_tag:
                return None

            title = title_tag.get_text(strip=True)
            path = title_tag.get("href", "")
            if not path:
                return None

            # ID из пути /vacancies/1000XXXXXX
            id_match = re.search(r"/vacancies/(\d+)", path)
            if not id_match:
                return None
            vacancy_id = f"habr_{id_match.group(1)}"
            url = f"{self.HABR_BASE_URL}{path}"

            # Компания — убираем emoji и лишние пробелы
            comp_tag = card.find("a", class_=lambda x: x and "link-comp" in x)
            company = re.sub(r"[^\w\s\-\.]", "", comp_tag.get_text(strip=True)).strip() if comp_tag else "Не указана"

            # Зарплата
            sal_tag = card.find(class_=re.compile(r"salary"))
            salary_text = sal_tag.get_text(strip=True) if sal_tag else ""
            salary_from, salary_to, salary_currency = self._parse_salary_text(salary_text)

            # Мета: уровень, удалённость
            meta_tag = card.find("div", class_=re.compile(r"vacancy-card__meta"))
            meta_text = meta_tag.get_text(" ", strip=True).lower() if meta_tag else ""
            is_remote = "удалённо" in meta_text or "remote" in meta_text

            # Дата публикации
            date_tag = card.find("time")
            published_at = date_tag.get("datetime", "") if date_tag else ""

            vacancy = Vacancy(
                id=vacancy_id,
                title=title,
                company=company,
                url=url,
                salary_from=salary_from,
                salary_to=salary_to,
                salary_currency=salary_currency,
                location="Удалённо" if is_remote else "Не указано",
                remote=is_remote,
                published_at=published_at,
                source="habr.career",
            )

            # Те же фильтры что и для hh.ru
            title_lower = title.lower()
            if any(kw in title_lower for kw in self.NOISE_TITLE_KEYWORDS):
                return None
            if any(kw in title_lower for kw in self.SENIOR_TITLE_KEYWORDS):
                return None

            return vacancy

        except (AttributeError, ValidationError):
            return None

    # ─── Описания вакансий ──────────────────────────────────────────────────

    def get_vacancy_description(self, vacancy_id: str) -> str:
        """
        Загружает полное описание вакансии по её ID.
        Поддерживает оба источника: hh.ru (числовой ID) и Habr Career (habr_XXXXX).
        Результат кэшируется в output/descriptions_cache.json.
        """
        # Проверяем кэш
        if vacancy_id in self._desc_cache:
            print(f"  [КЭШ] {vacancy_id} — из кэша")
            return self._desc_cache[vacancy_id]

        # Определяем источник по ID
        if vacancy_id.startswith("habr_"):
            habr_id = vacancy_id[len("habr_"):]
            url = f"{self.HABR_BASE_URL}/vacancies/{habr_id}"
            response = self._get_with_retry(url, verify=False)
            if response is None:
                return ""
            soup = BeautifulSoup(response.text, "lxml")
            # Habr Career: описание в div.vacancy-description или article
            desc_block = soup.find("div", class_=re.compile(r"vacancy-description|job-description"))
            if not desc_block:
                desc_block = soup.find("article")
            description = desc_block.get_text(separator="\n", strip=True)[:4000] if desc_block else ""
        else:
            url = self.HH_VACANCY_URL.format(vacancy_id)
            response = self._get_with_retry(url)
            if response is None:
                return ""
            soup = BeautifulSoup(response.text, "lxml")
            desc_block = soup.find("div", attrs={"data-qa": "vacancy-description"})
            if not desc_block:
                desc_block = soup.find("div", class_=re.compile("vacancy-description"))
            description = desc_block.get_text(separator="\n", strip=True)[:4000] if desc_block else ""

        # Сохраняем в кэш
        self._desc_cache[vacancy_id] = description
        self._save_desc_cache()

        return description

    def enrich_with_descriptions(self, vacancies: list[Vacancy]) -> list[Vacancy]:
        """
        Загружает полные описания для каждой вакансии.
        Нужно перед отправкой на анализ в LLM.
        Описания берутся из кэша если уже загружались ранее.
        """
        print(f"\n[ЗАГРУЗКА ОПИСАНИЙ] {len(vacancies)} вакансий...")

        for i, vacancy in enumerate(vacancies, 1):
            if not vacancy.description:
                desc = self.get_vacancy_description(vacancy.id)
                vacancy.description = desc
                status = "OK" if desc else "нет текста"
                print(f"  [{i}/{len(vacancies)}] {vacancy.title[:40]} — {status}")
                time.sleep(0.8)  # пауза между запросами (пропускается при кэш-хите)

        return vacancies

    # ─── Агрегация ──────────────────────────────────────────────────────────

    def search_all_queries(self, enrich: bool = False, include_habr: bool = True) -> list[Vacancy]:
        """
        Запускает поиск по всем запросам из config.SEARCH_QUERIES.
        Ищет на hh.ru и (опционально) Habr Career.
        Автоматически убирает дублирующиеся вакансии (по ID и по title+company).
        """
        all_vacancies: dict[str, Vacancy] = {}

        # Поиск на hh.ru
        for query in config.SEARCH_QUERIES:
            results = self.search_hh(query)
            for v in results:
                if v.id not in all_vacancies:
                    all_vacancies[v.id] = v

        # Поиск на Habr Career
        if include_habr:
            for query in config.SEARCH_QUERIES:
                results = self.search_habr(query)
                for v in results:
                    if v.id not in all_vacancies:
                        all_vacancies[v.id] = v

        unique_vacancies = list(all_vacancies.values())
        print(f"\n[ИТОГО УНИКАЛЬНЫХ] {len(unique_vacancies)} вакансий (hh.ru + Habr Career)")

        if enrich:
            unique_vacancies = self.enrich_with_descriptions(unique_vacancies)

        return unique_vacancies

    # ─── Дедупликация ───────────────────────────────────────────────────────

    def _dedup(self, vacancies: list[Vacancy]) -> list[Vacancy]:
        """
        Дедупликация вакансий по двум критериям:
        1. По vacancy_id (одна вакансия на нескольких страницах)
        2. По нормализованной паре (title, company) — одна вакансия с разных источников
        """
        seen_ids: dict[str, Vacancy] = {}
        seen_pairs: set[tuple[str, str]] = set()
        result = []

        for v in vacancies:
            # Нормализуем для сравнения: нижний регистр, убираем пробелы
            norm_title = re.sub(r"\s+", " ", v.title.lower().strip())
            norm_company = re.sub(r"\s+", " ", v.company.lower().strip())
            pair = (norm_title, norm_company)

            if v.id in seen_ids:
                continue  # дубль по ID
            if pair in seen_pairs:
                continue  # дубль по названию+компании

            seen_ids[v.id] = v
            seen_pairs.add(pair)
            result.append(v)

        removed = len(vacancies) - len(result)
        if removed:
            print(f"[ДЕДУПЛИКАЦИЯ] Убрано дублей: {removed}")
        return result

    # ─── Сохранение ─────────────────────────────────────────────────────────

    def save_to_json(self, vacancies: list[Vacancy], filename: Optional[str] = None) -> Path:
        """
        Сохраняет найденные вакансии в JSON-файл в папке output/.
        """
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"vacancies_{timestamp}.json"

        config.OUTPUT_DIR.mkdir(exist_ok=True)
        output_path = config.OUTPUT_DIR / filename

        data = {
            "generated_at": datetime.now().isoformat(),
            "total": len(vacancies),
            "vacancies": [v.model_dump() for v in vacancies],
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"[СОХРАНЕНО] {output_path}")
        return output_path


# ─── Запуск для тестирования ─────────────────────────────────────────────────

if __name__ == "__main__":
    searcher = JobSearcher()

    vacancies = searcher.search_hh(
        query="prompt engineer",
        area=113,
        only_remote=True,
        pages=1,
    )

    print(f"\n--- Первые 5 вакансий ---")
    for v in vacancies[:5]:
        print(f"\n  Компания : {v.company}")
        print(f"  Должность: {v.title}")
        print(f"  Зарплата : {v.salary_str()}")
        print(f"  Локация  : {v.location} {'(удалённо)' if v.remote else ''}")
        print(f"  Ссылка   : {v.url}")

    if vacancies:
        path = searcher.save_to_json(vacancies, "test_search.json")
        print(f"\nФайл сохранён: {path}")
