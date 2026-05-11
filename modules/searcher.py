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


# ─── Модель вакансии (Pydantic) ───────────────────────────────────────────────

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


# ─── Основной класс поисковика ────────────────────────────────────────────────

class JobSearcher:
    """
    Ищет вакансии на hh.ru и Habr Career через парсинг HTML.
    Представляется как обычный браузер.
    """

    HH_SEARCH_URL = "https://hh.ru/search/vacancy"
    HH_VACANCY_URL = "https://hh.ru/vacancy/{}"

    HABR_SEARCH_URL = "https://career.habr.com/vacancies"
    HABR_BASE_URL   = "https://career.habr.com"

    # Слова в названии вакансии, которые точно не AI/prompt — фильтруем как мусор
    # Возникают когда hh.ru находит слово "промт" в названии компании (напр. Промтрейдсервис)
    NOISE_TITLE_KEYWORDS = [
        "менеджер отдела продаж", "тендерный специалист", "бухгалтер",
        "водитель", "кладовщик", "сварщик", "охранник", "продавец",
        "юрист", "экономист", "логист", "секретарь",
        "графический дизайнер", "graphic designer",
    ]

    # Слова в названии, указывающие на уровень выше джуна — отсекаем до анализа
    SENIOR_TITLE_KEYWORDS = [
        "senior", "ведущий", "lead", "team lead", "teamlead",
        "principal", "staff ", "архитектор",
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

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

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

            try:
                response = self.session.get(self.HH_SEARCH_URL, params=params, timeout=15)
                response.raise_for_status()
            except requests.exceptions.RequestException as e:
                print(f"  [ОШИБКА] Страница {page}: {e}")
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

        # Дедупликация по vacancy_id (одна вакансия может появиться на нескольких страницах)
        seen: dict[str, Vacancy] = {}
        for v in vacancies:
            if v.id not in seen:
                seen[v.id] = v
        unique = list(seen.values())
        if len(unique) < len(vacancies):
            print(f"[ДЕДУПЛИКАЦИЯ] Убрано дублей: {len(vacancies) - len(unique)}")
        return unique

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
            salary_from, salary_to, salary_currency = self._parse_salary(card)

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

        except (AttributeError, ValidationError) as e:
            return None  # тихо пропускаем битые карточки

    def _parse_salary(self, card) -> tuple[Optional[int], Optional[int], Optional[str]]:
        """
        Парсит зарплату из карточки вакансии.
        Примеры: "от 80 000 RUB", "80 000–120 000 ₽", "до 200 000 руб."

        Returns:
            Кортеж (salary_from, salary_to, currency)
        """
        salary_tag = card.find("span", attrs={"data-qa": "vacancy-serp__vacancy-compensation"})
        if not salary_tag:
            return None, None, None

        text = salary_tag.get_text(strip=True)
        # Убираем неразрывные пробелы и прочий мусор
        text = text.replace("\xa0", " ").replace(" ", " ").strip()

        # Определяем валюту
        currency = "RUB"
        if "₽" in text or "руб" in text.lower() or "RUB" in text:
            currency = "RUB"
        elif "$" in text or "USD" in text:
            currency = "USD"
        elif "€" in text or "EUR" in text:
            currency = "EUR"

        # Извлекаем числа
        numbers = re.findall(r"[\d\s]+", text)
        numbers = [int(n.replace(" ", "")) for n in numbers if n.strip()]

        salary_from = salary_to = None

        if "от" in text.lower() and numbers:
            salary_from = numbers[0]
        elif "до" in text.lower() and numbers:
            salary_to = numbers[0]
        elif len(numbers) >= 2:
            salary_from, salary_to = numbers[0], numbers[1]
        elif len(numbers) == 1:
            salary_from = numbers[0]

        return salary_from, salary_to, currency

    def get_vacancy_description(self, vacancy_id: str) -> str:
        """
        Загружает полное описание вакансии по её ID.
        Используется для детального анализа через Gemini.
        """
        url = self.HH_VACANCY_URL.format(vacancy_id)
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"  [ОШИБКА] Описание {vacancy_id}: {e}")
            return ""

        soup = BeautifulSoup(response.text, "lxml")

        # Блок с описанием вакансии
        desc_block = soup.find("div", attrs={"data-qa": "vacancy-description"})
        if not desc_block:
            # Запасной вариант
            desc_block = soup.find("div", class_=re.compile("vacancy-description"))

        if desc_block:
            return desc_block.get_text(separator="\n", strip=True)[:4000]

        return ""

    def enrich_with_descriptions(self, vacancies: list[Vacancy]) -> list[Vacancy]:
        """
        Загружает полные описания для каждой вакансии.
        Нужно перед отправкой на анализ в Gemini.
        """
        print(f"\n[ЗАГРУЗКА ОПИСАНИЙ] {len(vacancies)} вакансий...")

        for i, vacancy in enumerate(vacancies, 1):
            if not vacancy.description:
                desc = self.get_vacancy_description(vacancy.id)
                vacancy.description = desc
                status = "OK" if desc else "нет текста"
                print(f"  [{i}/{len(vacancies)}] {vacancy.title[:40]} — {status}")
                time.sleep(0.8)  # пауза между запросами

        return vacancies

    def search_all_queries(self, enrich: bool = False, include_habr: bool = True) -> list[Vacancy]:
        """
        Запускает поиск по всем запросам из config.SEARCH_QUERIES.
        Ищет на hh.ru и (опционально) Habr Career.
        Автоматически убирает дублирующиеся вакансии.

        Args:
            enrich: Загружать ли полные описания (нужно для анализа через LLM)
            include_habr: Искать ли также на Habr Career
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

            try:
                response = self.session.get(
                    self.HABR_SEARCH_URL,
                    params=params,
                    timeout=15,
                    verify=False,
                )
                response.raise_for_status()
            except requests.exceptions.RequestException as e:
                print(f"  [ОШИБКА] Habr страница {page}: {e}")
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

        # Дедупликация
        seen: dict[str, Vacancy] = {}
        for v in vacancies:
            if v.id not in seen:
                seen[v.id] = v
        return list(seen.values())

    def _parse_habr_card(self, card) -> Optional[Vacancy]:
        """Парсит одну карточку вакансии с Habr Career."""
        try:
            # Название и ссылка
            title_tag = card.find("a", class_="vacancy-card__title-link")
            if not title_tag:
                return None

            title = title_tag.get_text(strip=True)
            path  = title_tag.get("href", "")
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
            salary_from, salary_to, salary_currency = self._parse_habr_salary(card)

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

    def _parse_habr_salary(self, card) -> tuple[Optional[int], Optional[int], Optional[str]]:
        """
        Парсит зарплату из карточки Habr Career.
        Примеры: "от 4000 до 6000 $", "от 150 000 ₽", "200 000 – 300 000 ₽"
        """
        sal_tag = card.find(class_=re.compile(r"salary"))
        if not sal_tag:
            return None, None, None

        text = sal_tag.get_text(strip=True).replace("\xa0", " ").replace(" ", " ")

        # Валюта
        if "$" in text or "USD" in text:
            currency = "USD"
        elif "€" in text or "EUR" in text:
            currency = "EUR"
        else:
            currency = "RUB"

        numbers = [int(n.replace(" ", "")) for n in re.findall(r"[\d][\d ]+", text) if n.strip()]

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

    def save_to_json(self, vacancies: list[Vacancy], filename: Optional[str] = None) -> Path:
        """
        Сохраняет найденные вакансии в JSON-файл в папке output/.

        Args:
            vacancies: Список вакансий для сохранения
            filename: Имя файла (генерируется автоматически если не указано)

        Returns:
            Путь к сохранённому файлу
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


# ─── Запуск для тестирования ──────────────────────────────────────────────────

if __name__ == "__main__":
    searcher = JobSearcher()

    # Тест: один запрос, одна страница
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

    # Сохраняем результат
    if vacancies:
        path = searcher.save_to_json(vacancies, "test_search.json")
        print(f"\nФайл сохранён: {path}")
