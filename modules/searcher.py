"""
searcher.py вЂ” РјРѕРґСѓР»СЊ РїРѕРёСЃРєР° РІР°РєР°РЅСЃРёР№
РСЃС‚РѕС‡РЅРёРєРё: hh.ru (web scraping), Habr Career (web scraping)

hh.ru Р·Р°Р±Р»РѕРєРёСЂРѕРІР°Р» РїСЂСЏРјС‹Рµ API-Р·Р°РїСЂРѕСЃС‹ Р±РµР· OAuth-Р°РІС‚РѕСЂРёР·Р°С†РёРё,
РїРѕСЌС‚РѕРјСѓ РёСЃРїРѕР»СЊР·СѓРµРј РїР°СЂСЃРёРЅРі HTML-СЃС‚СЂР°РЅРёС† С‡РµСЂРµР· BeautifulSoup.
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


# в”Ђв”Ђв”Ђ РњРѕРґРµР»СЊ РІР°РєР°РЅСЃРёРё (Pydantic) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

class Vacancy(BaseModel):
    """РЎС‚СЂСѓРєС‚СѓСЂР° РѕРґРЅРѕР№ РІР°РєР°РЅСЃРёРё РїРѕСЃР»Рµ РїР°СЂСЃРёРЅРіР°."""

    id: str
    title: str
    company: str
    url: str
    salary_from: Optional[int] = None
    salary_to: Optional[int] = None
    salary_currency: Optional[str] = None
    location: str = "РќРµ СѓРєР°Р·Р°РЅРѕ"
    remote: bool = False
    description: str = ""
    requirements: str = ""
    published_at: str = ""
    source: str = "hh.ru"

    def salary_str(self) -> str:
        """Р’РѕР·РІСЂР°С‰Р°РµС‚ Р·Р°СЂРїР»Р°С‚Сѓ РІ С‡РёС‚Р°РµРјРѕРј РІРёРґРµ."""
        if self.salary_from and self.salary_to:
            return f"{self.salary_from:,}вЂ“{self.salary_to:,} {self.salary_currency or 'RUB'}"
        elif self.salary_from:
            return f"РѕС‚ {self.salary_from:,} {self.salary_currency or 'RUB'}"
        elif self.salary_to:
            return f"РґРѕ {self.salary_to:,} {self.salary_currency or 'RUB'}"
        return "РЅРµ СѓРєР°Р·Р°РЅР°"


# в”Ђв”Ђв”Ђ РћСЃРЅРѕРІРЅРѕР№ РєР»Р°СЃСЃ РїРѕРёСЃРєРѕРІРёРєР° в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

class JobSearcher:
    """
    РС‰РµС‚ РІР°РєР°РЅСЃРёРё РЅР° hh.ru Рё Habr Career С‡РµСЂРµР· РїР°СЂСЃРёРЅРі HTML.
    РџСЂРµРґСЃС‚Р°РІР»СЏРµС‚СЃСЏ РєР°Рє РѕР±С‹С‡РЅС‹Р№ Р±СЂР°СѓР·РµСЂ.
    """

    HH_SEARCH_URL = "https://hh.ru/search/vacancy"
    HH_VACANCY_URL = "https://hh.ru/vacancy/{}"

    HABR_SEARCH_URL = "https://career.habr.com/vacancies"
    HABR_BASE_URL   = "https://career.habr.com"

    # РџСѓС‚СЊ Рє С„Р°Р№Р»Сѓ РєСЌС€Р° РѕРїРёСЃР°РЅРёР№ РІР°РєР°РЅСЃРёР№
    DESCRIPTIONS_CACHE_PATH = config.OUTPUT_DIR / "descriptions_cache.json"

    # РЎР»РѕРІР° РІ РЅР°Р·РІР°РЅРёРё РІР°РєР°РЅСЃРёРё, РєРѕС‚РѕСЂС‹Рµ С‚РѕС‡РЅРѕ РЅРµ AI/prompt вЂ” С„РёР»СЊС‚СЂСѓРµРј РєР°Рє РјСѓСЃРѕСЂ
    NOISE_TITLE_KEYWORDS = [
        "РјРµРЅРµРґР¶РµСЂ РѕС‚РґРµР»Р° РїСЂРѕРґР°Р¶", "С‚РµРЅРґРµСЂРЅС‹Р№ СЃРїРµС†РёР°Р»РёСЃС‚", "Р±СѓС…РіР°Р»С‚РµСЂ",
        "РІРѕРґРёС‚РµР»СЊ", "РєР»Р°РґРѕРІС‰РёРє", "СЃРІР°СЂС‰РёРє", "РѕС…СЂР°РЅРЅРёРє", "РїСЂРѕРґР°РІРµС†",
        "СЋСЂРёСЃС‚", "СЌРєРѕРЅРѕРјРёСЃС‚", "Р»РѕРіРёСЃС‚", "СЃРµРєСЂРµС‚Р°СЂСЊ",
        "РіСЂР°С„РёС‡РµСЃРєРёР№ РґРёР·Р°Р№РЅРµСЂ", "graphic designer",
    ]

    # РЎР»РѕРІР° РІ РЅР°Р·РІР°РЅРёРё, СѓРєР°Р·С‹РІР°СЋС‰РёРµ РЅР° СѓСЂРѕРІРµРЅСЊ РІС‹С€Рµ РґР¶СѓРЅР° вЂ” РѕС‚СЃРµРєР°РµРј РґРѕ Р°РЅР°Р»РёР·Р°
    SENIOR_TITLE_KEYWORDS = [
        "senior", "РІРµРґСѓС‰РёР№", "lead", "team lead", "teamlead",
        "principal", "staff ", "Р°СЂС…РёС‚РµРєС‚РѕСЂ",
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
        # РљСЌС€ РѕРїРёСЃР°РЅРёР№: vacancy_id -> РѕРїРёСЃР°РЅРёРµ (Р·Р°РіСЂСѓР¶Р°РµС‚СЃСЏ СЃ РґРёСЃРєР° РїСЂРё СЃС‚Р°СЂС‚Рµ)
        self._desc_cache: dict[str, str] = self._load_desc_cache()

    # в”Ђв”Ђв”Ђ РљСЌС€ РѕРїРёСЃР°РЅРёР№ РІР°РєР°РЅСЃРёР№ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

    def _load_desc_cache(self) -> dict[str, str]:
        """Р—Р°РіСЂСѓР¶Р°РµС‚ РєСЌС€ РѕРїРёСЃР°РЅРёР№ РёР· С„Р°Р№Р»Р°."""
        if self.DESCRIPTIONS_CACHE_PATH.exists():
            try:
                with open(self.DESCRIPTIONS_CACHE_PATH, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_desc_cache(self) -> None:
        """РЎРѕС…СЂР°РЅСЏРµС‚ РєСЌС€ РѕРїРёСЃР°РЅРёР№ РЅР° РґРёСЃРє."""
        config.OUTPUT_DIR.mkdir(exist_ok=True)
        with open(self.DESCRIPTIONS_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(self._desc_cache, f, ensure_ascii=False, indent=2)

    # в”Ђв”Ђв”Ђ HTTP-Р·Р°РїСЂРѕСЃ СЃ retry/backoff в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

    def _get_with_retry(
        self,
        url: str,
        params: Optional[dict] = None,
        timeout: int = 15,
        verify: bool = True,
        max_retries: int = 3,
    ) -> Optional[requests.Response]:
        """
        GET-Р·Р°РїСЂРѕСЃ СЃ exponential backoff РїСЂРё РѕС€РёР±РєР°С… 429/503/ConnectionError.

        Args:
            url: URL Р·Р°РїСЂРѕСЃР°
            params: Query-РїР°СЂР°РјРµС‚СЂС‹
            timeout: РўР°Р№РјР°СѓС‚ РІ СЃРµРєСѓРЅРґР°С…
            verify: РџСЂРѕРІРµСЂСЏС‚СЊ SSL (False РґР»СЏ Habr С‡РµСЂРµР· VPN)
            max_retries: РњР°РєСЃРёРјР°Р»СЊРЅРѕРµ С‡РёСЃР»Рѕ РїРѕРІС‚РѕСЂРЅС‹С… РїРѕРїС‹С‚РѕРє

        Returns:
            Response РёР»Рё None РµСЃР»Рё РІСЃРµ РїРѕРїС‹С‚РєРё РёСЃС‡РµСЂРїР°РЅС‹
        """
        for attempt in range(max_retries):
            try:
                response = self.session.get(url, params=params, timeout=timeout, verify=verify)

                # 429 Too Many Requests вЂ” Р¶РґС‘Рј Рё РїРѕРІС‚РѕСЂСЏРµРј
                if response.status_code == 429:
                    wait = 2 ** attempt * 3  # 3, 6, 12 СЃРµРєСѓРЅРґ
                    print(f"  [RATE LIMIT] 429 вЂ” Р¶РґС‘Рј {wait}СЃ (РїРѕРїС‹С‚РєР° {attempt + 1}/{max_retries})")
                    time.sleep(wait)
                    continue

                # 503 Service Unavailable вЂ” РєРѕСЂРѕС‚РєР°СЏ РїР°СѓР·Р° Рё РїРѕРІС‚РѕСЂ
                if response.status_code == 503:
                    wait = 2 ** attempt * 2  # 2, 4, 8 СЃРµРєСѓРЅРґ
                    print(f"  [503] РЎРµСЂРІРёСЃ РЅРµРґРѕСЃС‚СѓРїРµРЅ вЂ” Р¶РґС‘Рј {wait}СЃ (РїРѕРїС‹С‚РєР° {attempt + 1}/{max_retries})")
                    time.sleep(wait)
                    continue

                response.raise_for_status()
                return response

            except requests.exceptions.ConnectionError as e:
                wait = 2 ** attempt * 2
                print(f"  [CONN ERROR] РїРѕРїС‹С‚РєР° {attempt + 1}/{max_retries} вЂ” Р¶РґС‘Рј {wait}СЃ: {e}")
                time.sleep(wait)
            except requests.exceptions.Timeout:
                print(f"  [TIMEOUT] РїРѕРїС‹С‚РєР° {attempt + 1}/{max_retries}")
                time.sleep(2 ** attempt)
            except requests.exceptions.RequestException as e:
                print(f"  [РћРЁРР‘РљРђ] {e}")
                return None  # РїСЂРѕС‡РёРµ РѕС€РёР±РєРё вЂ” РЅРµ РїРѕРІС‚РѕСЂСЏРµРј

        print(f"  [FAIL] Р’СЃРµ {max_retries} РїРѕРїС‹С‚РєРё РёСЃС‡РµСЂРїР°РЅС‹ РґР»СЏ {url}")
        return None

    def search_hh(
        self,
        query: str,
        area: int = config.SEARCH_AREA,
        only_remote: bool = config.SEARCH_ONLY_REMOTE,
        pages: int = 2,
    ) -> list[Vacancy]:
        """
        РС‰РµС‚ РІР°РєР°РЅСЃРёРё РЅР° hh.ru РїРѕ РїРѕРёСЃРєРѕРІРѕРјСѓ Р·Р°РїСЂРѕСЃСѓ.

        Args:
            query: РџРѕРёСЃРєРѕРІС‹Р№ Р·Р°РїСЂРѕСЃ (РЅР°РїСЂРёРјРµСЂ "prompt engineer")
            area: Р РµРіРёРѕРЅ (113 = РІСЃСЏ Р РѕСЃСЃРёСЏ, 1 = РњРѕСЃРєРІР°, 2 = РЎРџР±)
            only_remote: РўРѕР»СЊРєРѕ СѓРґР°Р»С‘РЅРЅР°СЏ СЂР°Р±РѕС‚Р°
            pages: РЎРєРѕР»СЊРєРѕ СЃС‚СЂР°РЅРёС† Р·Р°РіСЂСѓР¶Р°С‚СЊ (РЅР° РєР°Р¶РґРѕР№ ~20 РІР°РєР°РЅСЃРёР№)

        Returns:
            РЎРїРёСЃРѕРє РѕР±СЉРµРєС‚РѕРІ Vacancy
        """
        print(f"[РџРћРРЎРљ] hh.ru: '{query}' | СЂРµРіРёРѕРЅ: {area} | СѓРґР°Р»С‘РЅРЅРѕ: {only_remote}")

        vacancies = []

        for page in range(pages):
            params = {
                "text": query,
                "area": area,
                "page": page,
                "items_on_page": 20,
                "order_by": "publication_time",  # СЃРЅР°С‡Р°Р»Р° СЃРІРµР¶РёРµ
            }
            if only_remote:
                params["schedule"] = "remote"

            response = self._get_with_retry(self.HH_SEARCH_URL, params=params)
            if response is None:
                break

            soup = BeautifulSoup(response.text, "lxml")

            # hh.ru СЂРµРЅРґРµСЂРёС‚ РєР°СЂС‚РѕС‡РєРё СЃ Р°С‚СЂРёР±СѓС‚РѕРј data-qa="vacancy-serp__vacancy"
            cards = soup.find_all("div", attrs={"data-qa": "vacancy-serp__vacancy"})

            if not cards:
                print(f"  [РЎРўРћРџ] РЎС‚СЂР°РЅРёС†Р° {page + 1}: РєР°СЂС‚РѕС‡РµРє РЅРµ РЅР°Р№РґРµРЅРѕ")
                break

            print(f"  [РЎРўР  {page + 1}] РќР°Р№РґРµРЅРѕ РєР°СЂС‚РѕС‡РµРє: {len(cards)}")

            for card in cards:
                vacancy = self._parse_card(card)
                if vacancy:
                    vacancies.append(vacancy)

            # РџР°СѓР·Р° С‡С‚РѕР±С‹ РЅРµ С‚СЂРёРіРіРµСЂРёС‚СЊ Р·Р°С‰РёС‚Сѓ РѕС‚ Р±РѕС‚РѕРІ
            time.sleep(1.0)

        print(f"[РРўРћР“Рћ] '{query}': {len(vacancies)} РІР°РєР°РЅСЃРёР№")

        return self._dedup(vacancies)

    def _parse_card(self, card) -> Optional[Vacancy]:
        """
        РџР°СЂСЃРёС‚ РѕРґРЅСѓ РєР°СЂС‚РѕС‡РєСѓ РІР°РєР°РЅСЃРёРё РёР· HTML.
        РЎС‚СЂСѓРєС‚СѓСЂР° hh.ru РјРѕР¶РµС‚ РјРµРЅСЏС‚СЊСЃСЏ вЂ” РєРѕРґ РїРѕРєСЂС‹РІР°РµС‚ РѕСЃРЅРѕРІРЅС‹Рµ РІР°СЂРёР°РЅС‚С‹.
        """
        try:
            # РќР°Р·РІР°РЅРёРµ Рё СЃСЃС‹Р»РєР°
            title_tag = card.find("a", attrs={"data-qa": "serp-item__title"})
            if not title_tag:
                return None

            title = title_tag.get_text(strip=True)
            url = title_tag.get("href", "")

            # РР·РІР»РµРєР°РµРј ID РІР°РєР°РЅСЃРёРё РёР· URL
            id_match = re.search(r"/vacancy/(\d+)", url)
            if not id_match:
                return None
            vacancy_id = id_match.group(1)

            # РџРѕР»РЅС‹Р№ URL (РёРЅРѕРіРґР° РїСЂРёС…РѕРґРёС‚ Р±РµР· РґРѕРјРµРЅР°)
            if url.startswith("/"):
                url = f"https://hh.ru{url}"

            # РљРѕРјРїР°РЅРёСЏ
            company_tag = card.find("a", attrs={"data-qa": "vacancy-serp__vacancy-employer"})
            if not company_tag:
                company_tag = card.find("span", attrs={"data-qa": "vacancy-serp__vacancy-employer"})
            company = company_tag.get_text(strip=True) if company_tag else "РќРµ СѓРєР°Р·Р°РЅР°"

            # Р—Р°СЂРїР»Р°С‚Р°
            salary_from, salary_to, salary_currency = self._parse_salary(card)

            # Р›РѕРєР°С†РёСЏ
            location_tag = card.find("div", attrs={"data-qa": "vacancy-serp__vacancy-address"})
            location = location_tag.get_text(strip=True) if location_tag else "РќРµ СѓРєР°Р·Р°РЅРѕ"

            # РЈРґР°Р»С‘РЅРЅРѕСЃС‚СЊ
            schedule_tags = card.find_all(string=re.compile(r"СѓРґР°Р»С‘РЅРЅ|remote", re.IGNORECASE))
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

            # Р¤РёР»СЊС‚СЂСѓРµРј СЏРІРЅС‹Р№ РјСѓСЃРѕСЂ РїРѕ РЅР°Р·РІР°РЅРёСЋ РІР°РєР°РЅСЃРёРё
            title_lower = title.lower()
            if any(kw in title_lower for kw in self.NOISE_TITLE_KEYWORDS):
                return None

            # Р¤РёР»СЊС‚СЂСѓРµРј Senior/Lead/Р’РµРґСѓС‰РёР№ вЂ” РєР°РЅРґРёРґР°С‚ РґР¶СѓРЅ, С‚Р°РєРёРµ РІР°РєР°РЅСЃРёРё РЅРµ РїРѕРґС…РѕРґСЏС‚
            if any(kw in title_lower for kw in self.SENIOR_TITLE_KEYWORDS):
                return None

            return vacancy

        except (AttributeError, ValidationError):
            return None  # С‚РёС…Рѕ РїСЂРѕРїСѓСЃРєР°РµРј Р±РёС‚С‹Рµ РєР°СЂС‚РѕС‡РєРё

    def _parse_salary(self, card) -> tuple[Optional[int], Optional[int], Optional[str]]:
        """
        РџР°СЂСЃРёС‚ Р·Р°СЂРїР»Р°С‚Сѓ РёР· РєР°СЂС‚РѕС‡РєРё РІР°РєР°РЅСЃРёРё.
        РџСЂРёРјРµСЂС‹: "РѕС‚ 80 000 RUB", "80 000вЂ“120 000 в‚Ѕ", "РґРѕ 200 000 СЂСѓР±."

        Returns:
            РљРѕСЂС‚РµР¶ (salary_from, salary_to, currency)
        """
        salary_tag = card.find("span", attrs={"data-qa": "vacancy-serp__vacancy-compensation"})
        if not salary_tag:
            return None, None, None

        text = salary_tag.get_text(strip=True)
        # РЈР±РёСЂР°РµРј РЅРµСЂР°Р·СЂС‹РІРЅС‹Рµ РїСЂРѕР±РµР»С‹ Рё РїСЂРѕС‡РёР№ РјСѓСЃРѕСЂ
        text = text.replace("\xa0", " ").replace(" ", " ").strip()

        # РћРїСЂРµРґРµР»СЏРµРј РІР°Р»СЋС‚Сѓ
        currency = "RUB"
        if "в‚Ѕ" in text or "СЂСѓР±" in text.lower() or "RUB" in text:
            currency = "RUB"
        elif "$" in text or "USD" in text:
            currency = "USD"
        elif "в‚¬" in text or "EUR" in text:
            currency = "EUR"

        # РР·РІР»РµРєР°РµРј С‡РёСЃР»Р°
        numbers = re.findall(r"[\d\s]+", text)
        numbers = [int(n.replace(" ", "")) for n in numbers if n.strip()]

        salary_from = salary_to = None

        if "РѕС‚" in text.lower() and numbers:
            salary_from = numbers[0]
        elif "РґРѕ" in text.lower() and numbers:
            salary_to = numbers[0]
        elif len(numbers) >= 2:
            salary_from, salary_to = numbers[0], numbers[1]
        elif len(numbers) == 1:
            salary_from = numbers[0]

        return salary_from, salary_to, currency

    def get_vacancy_description(self, vacancy_id: str) -> str:
        """
        Р—Р°РіСЂСѓР¶Р°РµС‚ РїРѕР»РЅРѕРµ РѕРїРёСЃР°РЅРёРµ РІР°РєР°РЅСЃРёРё РїРѕ РµС‘ ID.
        Р РµР·СѓР»СЊС‚Р°С‚ РєСЌС€РёСЂСѓРµС‚СЃСЏ РІ output/descriptions_cache.json вЂ”
        РїСЂРё РїРѕРІС‚РѕСЂРЅРѕРј Р°РЅР°Р»РёР·Рµ HTTP-Р·Р°РїСЂРѕСЃ РЅРµ РґРµР»Р°РµС‚СЃСЏ.
        """
        # РџСЂРѕРІРµСЂСЏРµРј РєСЌС€
        if vacancy_id in self._desc_cache:
            print(f"  [РљР­РЁ] {vacancy_id} вЂ” РёР· РєСЌС€Р°")
            return self._desc_cache[vacancy_id]

        url = self.HH_VACANCY_URL.format(vacancy_id)
        response = self._get_with_retry(url)
        if response is None:
            return ""

        soup = BeautifulSoup(response.text, "lxml")

        # Р‘Р»РѕРє СЃ РѕРїРёСЃР°РЅРёРµРј РІР°РєР°РЅСЃРёРё
        desc_block = soup.find("div", attrs={"data-qa": "vacancy-description"})
        if not desc_block:
            desc_block = soup.find("div", class_=re.compile("vacancy-description"))

        description = ""
        if desc_block:
            description = desc_block.get_text(separator="\n", strip=True)[:4000]

        # РЎРѕС…СЂР°РЅСЏРµРј РІ РєСЌС€ (РґР°Р¶Рµ РїСѓСЃС‚РѕРµ вЂ” С‡С‚РѕР±С‹ РЅРµ Р·Р°РїСЂР°С€РёРІР°С‚СЊ СЃРЅРѕРІР°)
        self._desc_cache[vacancy_id] = description
        self._save_desc_cache()

        return description

    def enrich_with_descriptions(self, vacancies: list[Vacancy]) -> list[Vacancy]:
        """
        Р—Р°РіСЂСѓР¶Р°РµС‚ РїРѕР»РЅС‹Рµ РѕРїРёСЃР°РЅРёСЏ РґР»СЏ РєР°Р¶РґРѕР№ РІР°РєР°РЅСЃРёРё.
        РќСѓР¶РЅРѕ РїРµСЂРµРґ РѕС‚РїСЂР°РІРєРѕР№ РЅР° Р°РЅР°Р»РёР· РІ LLM.
        РћРїРёСЃР°РЅРёСЏ Р±РµСЂСѓС‚СЃСЏ РёР· РєСЌС€Р° РµСЃР»Рё СѓР¶Рµ Р·Р°РіСЂСѓР¶Р°Р»РёСЃСЊ СЂР°РЅРµРµ.
        """
        print(f"\n[Р—РђР“Р РЈР—РљРђ РћРџРРЎРђРќРР™] {len(vacancies)} РІР°РєР°РЅСЃРёР№...")

        for i, vacancy in enumerate(vacancies, 1):
            if not vacancy.description:
                desc = self.get_vacancy_description(vacancy.id)
                vacancy.description = desc
                status = "OK" if desc else "РЅРµС‚ С‚РµРєСЃС‚Р°"
                print(f"  [{i}/{len(vacancies)}] {vacancy.title[:40]} вЂ” {status}")
                time.sleep(0.8)  # РїР°СѓР·Р° РјРµР¶РґСѓ Р·Р°РїСЂРѕСЃР°РјРё (РїСЂРѕРїСѓСЃРєР°РµС‚СЃСЏ РїСЂРё РєСЌС€-С…РёС‚Рµ)

        return vacancies

    def search_all_queries(self, enrich: bool = False, include_habr: bool = True) -> list[Vacancy]:
        """
        Р—Р°РїСѓСЃРєР°РµС‚ РїРѕРёСЃРє РїРѕ РІСЃРµРј Р·Р°РїСЂРѕСЃР°Рј РёР· config.SEARCH_QUERIES.
        РС‰РµС‚ РЅР° hh.ru Рё (РѕРїС†РёРѕРЅР°Р»СЊРЅРѕ) Habr Career.
        РђРІС‚РѕРјР°С‚РёС‡РµСЃРєРё СѓР±РёСЂР°РµС‚ РґСѓР±Р»РёСЂСѓСЋС‰РёРµСЃСЏ РІР°РєР°РЅСЃРёРё (РїРѕ ID Рё РїРѕ title+company).
        """
        all_vacancies: dict[str, Vacancy] = {}

        # РџРѕРёСЃРє РЅР° hh.ru
        for query in config.SEARCH_QUERIES:
            results = self.search_hh(query)
            for v in results:
                if v.id not in all_vacancies:
                    all_vacancies[v.id] = v

        # РџРѕРёСЃРє РЅР° Habr Career
        if include_habr:
            for query in config.SEARCH_QUERIES:
                results = self.search_habr(query)
                for v in results:
                    if v.id not in all_vacancies:
                        all_vacancies[v.id] = v

        unique_vacancies = list(all_vacancies.values())
        print(f"\n[РРўРћР“Рћ РЈРќРРљРђР›Р¬РќР«РҐ] {len(unique_vacancies)} РІР°РєР°РЅСЃРёР№ (hh.ru + Habr Career)")

        if enrich:
            unique_vacancies = self.enrich_with_descriptions(unique_vacancies)

        return unique_vacancies

    def search_habr(
        self,
        query: str,
        pages: int = 2,
    ) -> list[Vacancy]:
        """
        РС‰РµС‚ РІР°РєР°РЅСЃРёРё РЅР° Habr Career РїРѕ РїРѕРёСЃРєРѕРІРѕРјСѓ Р·Р°РїСЂРѕСЃСѓ.

        Args:
            query: РџРѕРёСЃРєРѕРІС‹Р№ Р·Р°РїСЂРѕСЃ (РЅР°РїСЂРёРјРµСЂ "AI engineer")
            pages: РЎРєРѕР»СЊРєРѕ СЃС‚СЂР°РЅРёС† Р·Р°РіСЂСѓР¶Р°С‚СЊ (РЅР° РєР°Р¶РґРѕР№ ~25 РІР°РєР°РЅСЃРёР№)

        Returns:
            РЎРїРёСЃРѕРє РѕР±СЉРµРєС‚РѕРІ Vacancy
        """
        import urllib3
        urllib3.disable_warnings()

        print(f"[РџРћРРЎРљ] Habr Career: '{query}'")

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
                print(f"  [РЎРўРћРџ] Habr СЃС‚СЂР°РЅРёС†Р° {page}: РєР°СЂС‚РѕС‡РµРє РЅРµ РЅР°Р№РґРµРЅРѕ")
                break

            print(f"  [РЎРўР  {page}] Habr: РЅР°Р№РґРµРЅРѕ РєР°СЂС‚РѕС‡РµРє: {len(cards)}")

            for card in cards:
                vacancy = self._parse_habr_card(card)
                if vacancy:
                    vacancies.append(vacancy)

            time.sleep(1.0)

        print(f"[РРўРћР“Рћ] Habr '{query}': {len(vacancies)} РІР°РєР°РЅСЃРёР№")
        return self._dedup(vacancies)

    def _parse_habr_card(self, card) -> Optional[Vacancy]:
        """РџР°СЂСЃРёС‚ РѕРґРЅСѓ РєР°СЂС‚РѕС‡РєСѓ РІР°РєР°РЅСЃРёРё СЃ Habr Career."""
        try:
            # РќР°Р·РІР°РЅРёРµ Рё СЃСЃС‹Р»РєР°
            title_tag = card.find("a", class_="vacancy-card__title-link")
            if not title_tag:
                return None

            title = title_tag.get_text(strip=True)
            path  = title_tag.get("href", "")
            if not path:
                return None

            # ID РёР· РїСѓС‚Рё /vacancies/1000XXXXXX
            id_match = re.search(r"/vacancies/(\d+)", path)
            if not id_match:
                return None
            vacancy_id = f"habr_{id_match.group(1)}"
            url = f"{self.HABR_BASE_URL}{path}"

            # РљРѕРјРїР°РЅРёСЏ вЂ” СѓР±РёСЂР°РµРј emoji Рё Р»РёС€РЅРёРµ РїСЂРѕР±РµР»С‹
            comp_tag = card.find("a", class_=lambda x: x and "link-comp" in x)
            company = re.sub(r"[^\w\s\-\.]", "", comp_tag.get_text(strip=True)).strip() if comp_tag else "РќРµ СѓРєР°Р·Р°РЅР°"

            # Р—Р°СЂРїР»Р°С‚Р°
            salary_from, salary_to, salary_currency = self._parse_habr_salary(card)

            # РњРµС‚Р°: СѓСЂРѕРІРµРЅСЊ, СѓРґР°Р»С‘РЅРЅРѕСЃС‚СЊ
            meta_tag = card.find("div", class_=re.compile(r"vacancy-card__meta"))
            meta_text = meta_tag.get_text(" ", strip=True).lower() if meta_tag else ""
            is_remote = "СѓРґР°Р»С‘РЅРЅРѕ" in meta_text or "remote" in meta_text

            # Р”Р°С‚Р° РїСѓР±Р»РёРєР°С†РёРё
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
                location="РЈРґР°Р»С‘РЅРЅРѕ" if is_remote else "РќРµ СѓРєР°Р·Р°РЅРѕ",
                remote=is_remote,
                published_at=published_at,
                source="habr.career",
            )

            # РўРµ Р¶Рµ С„РёР»СЊС‚СЂС‹ С‡С‚Рѕ Рё РґР»СЏ hh.ru
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
        РџР°СЂСЃРёС‚ Р·Р°СЂРїР»Р°С‚Сѓ РёР· РєР°СЂС‚РѕС‡РєРё Habr Career.
        РџСЂРёРјРµСЂС‹: "РѕС‚ 4000 РґРѕ 6000 $", "РѕС‚ 150 000 в‚Ѕ", "200 000 вЂ“ 300 000 в‚Ѕ"
        """
        sal_tag = card.find(class_=re.compile(r"salary"))
        if not sal_tag:
            return None, None, None

        text = sal_tag.get_text(strip=True).replace("\xa0", " ").replace(" ", " ")

        # Р’Р°Р»СЋС‚Р°
        if "$" in text or "USD" in text:
            currency = "USD"
        elif "в‚¬" in text or "EUR" in text:
            currency = "EUR"
        else:
            currency = "RUB"

        numbers = [int(n.replace(" ", "")) for n in re.findall(r"[\d][\d ]+", text) if n.strip()]

        salary_from = salary_to = None
        if "РѕС‚" in text.lower() and "РґРѕ" in text.lower() and len(numbers) >= 2:
            salary_from, salary_to = numbers[0], numbers[1]
        elif "РѕС‚" in text.lower() and numbers:
            salary_from = numbers[0]
        elif "РґРѕ" in text.lower() and numbers:
            salary_to = numbers[0]
        elif len(numbers) >= 2:
            salary_from, salary_to = numbers[0], numbers[1]
        elif len(numbers) == 1:
            salary_from = numbers[0]

        return salary_from, salary_to, currency

    def _dedup(self, vacancies: list[Vacancy]) -> list[Vacancy]:
        """
        Р”РµРґСѓРїР»РёРєР°С†РёСЏ РІР°РєР°РЅСЃРёР№ РїРѕ РґРІСѓРј РєСЂРёС‚РµСЂРёСЏРј:
        1. РџРѕ vacancy_id (РѕРґРЅР° РІР°РєР°РЅСЃРёСЏ РЅР° РЅРµСЃРєРѕР»СЊРєРёС… СЃС‚СЂР°РЅРёС†Р°С…)
        2. РџРѕ РЅРѕСЂРјР°Р»РёР·РѕРІР°РЅРЅРѕР№ РїР°СЂРµ (title, company) вЂ” РѕРґРЅР° РІР°РєР°РЅСЃРёСЏ СЃ СЂР°Р·РЅС‹С… РёСЃС‚РѕС‡РЅРёРєРѕРІ
        """
        seen_ids: dict[str, Vacancy] = {}
        seen_pairs: set[tuple[str, str]] = set()
        result = []

        for v in vacancies:
            # РќРѕСЂРјР°Р»РёР·СѓРµРј РґР»СЏ СЃСЂР°РІРЅРµРЅРёСЏ: РЅРёР¶РЅРёР№ СЂРµРіРёСЃС‚СЂ, СѓР±РёСЂР°РµРј РїСЂРѕР±РµР»С‹
            norm_title   = re.sub(r"\s+", " ", v.title.lower().strip())
            norm_company = re.sub(r"\s+", " ", v.company.lower().strip())
            pair = (norm_title, norm_company)

            if v.id in seen_ids:
                continue  # РґСѓР±Р»СЊ РїРѕ ID
            if pair in seen_pairs:
                continue  # РґСѓР±Р»СЊ РїРѕ РЅР°Р·РІР°РЅРёСЋ+РєРѕРјРїР°РЅРёРё

            seen_ids[v.id] = v
            seen_pairs.add(pair)
            result.append(v)

        removed = len(vacancies) - len(result)
        if removed:
            print(f"[Р”Р•Р”РЈРџР›РРљРђР¦РРЇ] РЈР±СЂР°РЅРѕ РґСѓР±Р»РµР№: {removed}")
        return result

    def save_to_json(self, vacancies: list[Vacancy], filename: Optional[str] = None) -> Path:
        """
        РЎРѕС…СЂР°РЅСЏРµС‚ РЅР°Р№РґРµРЅРЅС‹Рµ РІР°РєР°РЅСЃРёРё РІ JSON-С„Р°Р№Р» РІ РїР°РїРєРµ output/.
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

        print(f"[РЎРћРҐР РђРќР•РќРћ] {output_path}")
        return output_path


# в”Ђв”Ђв”Ђ Р—Р°РїСѓСЃРє РґР»СЏ С‚РµСЃС‚РёСЂРѕРІР°РЅРёСЏ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

if __name__ == "__main__":
    searcher = JobSearcher()

    vacancies = searcher.search_hh(
        query="prompt engineer",
        area=113,
        only_remote=True,
        pages=1,
    )

    print(f"\n--- РџРµСЂРІС‹Рµ 5 РІР°РєР°РЅСЃРёР№ ---")
    for v in vacancies[:5]:
        print(f"\n  РљРѕРјРїР°РЅРёСЏ : {v.company}")
        print(f"  Р”РѕР»Р¶РЅРѕСЃС‚СЊ: {v.title}")
        print(f"  Р—Р°СЂРїР»Р°С‚Р° : {v.salary_str()}")
        print(f"  Р›РѕРєР°С†РёСЏ  : {v.location} {'(СѓРґР°Р»С‘РЅРЅРѕ)' if v.remote else ''}")
        print(f"  РЎСЃС‹Р»РєР°   : {v.url}")

    if vacancies:
        path = searcher.save_to_json(vacancies, "test_search.json")
        print(f"\nР¤Р°Р№Р» СЃРѕС…СЂР°РЅС‘РЅ: {path}")


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


# в”Ђв”Ђв”Ђ РњРѕРґРµР»СЊ РІР°РєР°РЅСЃРёРё (Pydantic) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

class Vacancy(BaseModel):
    """РЎС‚СЂСѓРєС‚СѓСЂР° РѕРґРЅРѕР№ РІР°РєР°РЅСЃРёРё РїРѕСЃР»Рµ РїР°СЂСЃРёРЅРіР°."""

    id: str
    title: str
    company: str
    url: str
    salary_from: Optional[int] = None
    salary_to: Optional[int] = None
    salary_currency: Optional[str] = None
    location: str = "РќРµ СѓРєР°Р·Р°РЅРѕ"
    remote: bool = False
    description: str = ""
    requirements: str = ""
    published_at: str = ""
    source: str = "hh.ru"

    def salary_str(self) -> str:
        """Р’РѕР·РІСЂР°С‰Р°РµС‚ Р·Р°СЂРїР»Р°С‚Сѓ РІ С‡РёС‚Р°РµРјРѕРј РІРёРґРµ."""
        if self.salary_from and self.salary_to:
            return f"{self.salary_from:,}вЂ“{self.salary_to:,} {self.salary_currency or 'RUB'}"
        elif self.salary_from:
            return f"РѕС‚ {self.salary_from:,} {self.salary_currency or 'RUB'}"
        elif self.salary_to:
            return f"РґРѕ {self.salary_to:,} {self.salary_currency or 'RUB'}"
        return "РЅРµ СѓРєР°Р·Р°РЅР°"


# в”Ђв”Ђв”Ђ РћСЃРЅРѕРІРЅРѕР№ РєР»Р°СЃСЃ РїРѕРёСЃРєРѕРІРёРєР° в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

class JobSearcher:
    """
    РС‰РµС‚ РІР°РєР°РЅСЃРёРё РЅР° hh.ru Рё Habr Career С‡РµСЂРµР· РїР°СЂСЃРёРЅРі HTML.
    РџСЂРµРґСЃС‚Р°РІР»СЏРµС‚СЃСЏ РєР°Рє РѕР±С‹С‡РЅС‹Р№ Р±СЂР°СѓР·РµСЂ.
    """

    HH_SEARCH_URL = "https://hh.ru/search/vacancy"
    HH_VACANCY_URL = "https://hh.ru/vacancy/{}"

    HABR_SEARCH_URL = "https://career.habr.com/vacancies"
    HABR_BASE_URL   = "https://career.habr.com"

    # РЎР»РѕРІР° РІ РЅР°Р·РІР°РЅРёРё РІР°РєР°РЅСЃРёРё, РєРѕС‚РѕСЂС‹Рµ С‚РѕС‡РЅРѕ РЅРµ AI/prompt вЂ” С„РёР»СЊС‚СЂСѓРµРј РєР°Рє РјСѓСЃРѕСЂ
    # Р’РѕР·РЅРёРєР°СЋС‚ РєРѕРіРґР° hh.ru РЅР°С…РѕРґРёС‚ СЃР»РѕРІРѕ "РїСЂРѕРјС‚" РІ РЅР°Р·РІР°РЅРёРё РєРѕРјРїР°РЅРёРё (РЅР°РїСЂ. РџСЂРѕРјС‚СЂРµР№РґСЃРµСЂРІРёСЃ)
    NOISE_TITLE_KEYWORDS = [
        "РјРµРЅРµРґР¶РµСЂ РѕС‚РґРµР»Р° РїСЂРѕРґР°Р¶", "С‚РµРЅРґРµСЂРЅС‹Р№ СЃРїРµС†РёР°Р»РёСЃС‚", "Р±СѓС…РіР°Р»С‚РµСЂ",
        "РІРѕРґРёС‚РµР»СЊ", "РєР»Р°РґРѕРІС‰РёРє", "СЃРІР°СЂС‰РёРє", "РѕС…СЂР°РЅРЅРёРє", "РїСЂРѕРґР°РІРµС†",
        "СЋСЂРёСЃС‚", "СЌРєРѕРЅРѕРјРёСЃС‚", "Р»РѕРіРёСЃС‚", "СЃРµРєСЂРµС‚Р°СЂСЊ",
        "РіСЂР°С„РёС‡РµСЃРєРёР№ РґРёР·Р°Р№РЅРµСЂ", "graphic designer",
    ]

    # РЎР»РѕРІР° РІ РЅР°Р·РІР°РЅРёРё, СѓРєР°Р·С‹РІР°СЋС‰РёРµ РЅР° СѓСЂРѕРІРµРЅСЊ РІС‹С€Рµ РґР¶СѓРЅР° вЂ” РѕС‚СЃРµРєР°РµРј РґРѕ Р°РЅР°Р»РёР·Р°
    SENIOR_TITLE_KEYWORDS = [
        "senior", "РІРµРґСѓС‰РёР№", "lead", "team lead", "teamlead",
        "principal", "staff ", "Р°СЂС…РёС‚РµРєС‚РѕСЂ",
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

    def search_hh(
        self,
        query: str,
        area: int = config.SEARCH_AREA,
        only_remote: bool = config.SEARCH_ONLY_REMOTE,
        pages: int = 2,
    ) -> list[Vacancy]:
        """
        РС‰РµС‚ РІР°РєР°РЅСЃРёРё РЅР° hh.ru РїРѕ РїРѕРёСЃРєРѕРІРѕРјСѓ Р·Р°РїСЂРѕСЃСѓ.

        Args:
            query: РџРѕРёСЃРєРѕРІС‹Р№ Р·Р°РїСЂРѕСЃ (РЅР°РїСЂРёРјРµСЂ "prompt engineer")
            area: Р РµРіРёРѕРЅ (113 = РІСЃСЏ Р РѕСЃСЃРёСЏ, 1 = РњРѕСЃРєРІР°, 2 = РЎРџР±)
            only_remote: РўРѕР»СЊРєРѕ СѓРґР°Р»С‘РЅРЅР°СЏ СЂР°Р±РѕС‚Р°
            pages: РЎРєРѕР»СЊРєРѕ СЃС‚СЂР°РЅРёС† Р·Р°РіСЂСѓР¶Р°С‚СЊ (РЅР° РєР°Р¶РґРѕР№ ~20 РІР°РєР°РЅСЃРёР№)

        Returns:
            РЎРїРёСЃРѕРє РѕР±СЉРµРєС‚РѕРІ Vacancy
        """
        print(f"[РџРћРРЎРљ] hh.ru: '{query}' | СЂРµРіРёРѕРЅ: {area} | СѓРґР°Р»С‘РЅРЅРѕ: {only_remote}")

        vacancies = []

        for page in range(pages):
            params = {
                "text": query,
                "area": area,
                "page": page,
                "items_on_page": 20,
                "order_by": "publication_time",  # СЃРЅР°С‡Р°Р»Р° СЃРІРµР¶РёРµ
            }
            if only_remote:
                params["schedule"] = "remote"

            try:
                response = self.session.get(self.HH_SEARCH_URL, params=params, timeout=15)
                response.raise_for_status()
            except requests.exceptions.RequestException as e:
                print(f"  [РћРЁРР‘РљРђ] РЎС‚СЂР°РЅРёС†Р° {page}: {e}")
                break

            soup = BeautifulSoup(response.text, "lxml")

            # hh.ru СЂРµРЅРґРµСЂРёС‚ РєР°СЂС‚РѕС‡РєРё СЃ Р°С‚СЂРёР±СѓС‚РѕРј data-qa="vacancy-serp__vacancy"
            cards = soup.find_all("div", attrs={"data-qa": "vacancy-serp__vacancy"})

            if not cards:
                print(f"  [РЎРўРћРџ] РЎС‚СЂР°РЅРёС†Р° {page + 1}: РєР°СЂС‚РѕС‡РµРє РЅРµ РЅР°Р№РґРµРЅРѕ")
                break

            print(f"  [РЎРўР  {page + 1}] РќР°Р№РґРµРЅРѕ РєР°СЂС‚РѕС‡РµРє: {len(cards)}")

            for card in cards:
                vacancy = self._parse_card(card)
                if vacancy:
                    vacancies.append(vacancy)

            # РџР°СѓР·Р° С‡С‚РѕР±С‹ РЅРµ С‚СЂРёРіРіРµСЂРёС‚СЊ Р·Р°С‰РёС‚Сѓ РѕС‚ Р±РѕС‚РѕРІ
            time.sleep(1.0)

        print(f"[РРўРћР“Рћ] '{query}': {len(vacancies)} РІР°РєР°РЅСЃРёР№")

        # Р”РµРґСѓРїР»РёРєР°С†РёСЏ РїРѕ vacancy_id (РѕРґРЅР° РІР°РєР°РЅСЃРёСЏ РјРѕР¶РµС‚ РїРѕСЏРІРёС‚СЊСЃСЏ РЅР° РЅРµСЃРєРѕР»СЊРєРёС… СЃС‚СЂР°РЅРёС†Р°С…)
        seen: dict[str, Vacancy] = {}
        for v in vacancies:
            if v.id not in seen:
                seen[v.id] = v
        unique = list(seen.values())
        if len(unique) < len(vacancies):
            print(f"[Р”Р•Р”РЈРџР›РРљРђР¦РРЇ] РЈР±СЂР°РЅРѕ РґСѓР±Р»РµР№: {len(vacancies) - len(unique)}")
        return unique

    def _parse_card(self, card) -> Optional[Vacancy]:
        """
        РџР°СЂСЃРёС‚ РѕРґРЅСѓ РєР°СЂС‚РѕС‡РєСѓ РІР°РєР°РЅСЃРёРё РёР· HTML.
        РЎС‚СЂСѓРєС‚СѓСЂР° hh.ru РјРѕР¶РµС‚ РјРµРЅСЏС‚СЊСЃСЏ вЂ” РєРѕРґ РїРѕРєСЂС‹РІР°РµС‚ РѕСЃРЅРѕРІРЅС‹Рµ РІР°СЂРёР°РЅС‚С‹.
        """
        try:
            # РќР°Р·РІР°РЅРёРµ Рё СЃСЃС‹Р»РєР°
            title_tag = card.find("a", attrs={"data-qa": "serp-item__title"})
            if not title_tag:
                return None

            title = title_tag.get_text(strip=True)
            url = title_tag.get("href", "")

            # РР·РІР»РµРєР°РµРј ID РІР°РєР°РЅСЃРёРё РёР· URL
            id_match = re.search(r"/vacancy/(\d+)", url)
            if not id_match:
                return None
            vacancy_id = id_match.group(1)

            # РџРѕР»РЅС‹Р№ URL (РёРЅРѕРіРґР° РїСЂРёС…РѕРґРёС‚ Р±РµР· РґРѕРјРµРЅР°)
            if url.startswith("/"):
                url = f"https://hh.ru{url}"

            # РљРѕРјРїР°РЅРёСЏ
            company_tag = card.find("a", attrs={"data-qa": "vacancy-serp__vacancy-employer"})
            if not company_tag:
                company_tag = card.find("span", attrs={"data-qa": "vacancy-serp__vacancy-employer"})
            company = company_tag.get_text(strip=True) if company_tag else "РќРµ СѓРєР°Р·Р°РЅР°"

            # Р—Р°СЂРїР»Р°С‚Р°
            salary_from, salary_to, salary_currency = self._parse_salary(card)

            # Р›РѕРєР°С†РёСЏ
            location_tag = card.find("div", attrs={"data-qa": "vacancy-serp__vacancy-address"})
            location = location_tag.get_text(strip=True) if location_tag else "РќРµ СѓРєР°Р·Р°РЅРѕ"

            # РЈРґР°Р»С‘РЅРЅРѕСЃС‚СЊ
            schedule_tags = card.find_all(string=re.compile(r"СѓРґР°Р»С‘РЅРЅ|remote", re.IGNORECASE))
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

            # Р¤РёР»СЊС‚СЂСѓРµРј СЏРІРЅС‹Р№ РјСѓСЃРѕСЂ РїРѕ РЅР°Р·РІР°РЅРёСЋ РІР°РєР°РЅСЃРёРё
            title_lower = title.lower()
            if any(kw in title_lower for kw in self.NOISE_TITLE_KEYWORDS):
                return None

            # Р¤РёР»СЊС‚СЂСѓРµРј Senior/Lead/Р’РµРґСѓС‰РёР№ вЂ” РєР°РЅРґРёРґР°С‚ РґР¶СѓРЅ, С‚Р°РєРёРµ РІР°РєР°РЅСЃРёРё РЅРµ РїРѕРґС…РѕРґСЏС‚
            if any(kw in title_lower for kw in self.SENIOR_TITLE_KEYWORDS):
                return None

            return vacancy

        except (AttributeError, ValidationError) as e:
            return None  # С‚РёС…Рѕ РїСЂРѕРїСѓСЃРєР°РµРј Р±РёС‚С‹Рµ РєР°СЂС‚РѕС‡РєРё

    def _parse_salary(self, card) -> tuple[Optional[int], Optional[int], Optional[str]]:
        """
        РџР°СЂСЃРёС‚ Р·Р°СЂРїР»Р°С‚Сѓ РёР· РєР°СЂС‚РѕС‡РєРё РІР°РєР°РЅСЃРёРё.
        РџСЂРёРјРµСЂС‹: "РѕС‚ 80 000 RUB", "80 000вЂ“120 000 в‚Ѕ", "РґРѕ 200 000 СЂСѓР±."

        Returns:
            РљРѕСЂС‚РµР¶ (salary_from, salary_to, currency)
        """
        salary_tag = card.find("span", attrs={"data-qa": "vacancy-serp__vacancy-compensation"})
        if not salary_tag:
            return None, None, None

        text = salary_tag.get_text(strip=True)
        # РЈР±РёСЂР°РµРј РЅРµСЂР°Р·СЂС‹РІРЅС‹Рµ РїСЂРѕР±РµР»С‹ Рё РїСЂРѕС‡РёР№ РјСѓСЃРѕСЂ
        text = text.replace("\xa0", " ").replace(" ", " ").strip()

        # РћРїСЂРµРґРµР»СЏРµРј РІР°Р»СЋС‚Сѓ
        currency = "RUB"
        if "в‚Ѕ" in text or "СЂСѓР±" in text.lower() or "RUB" in text:
            currency = "RUB"
        elif "$" in text or "USD" in text:
            currency = "USD"
        elif "в‚¬" in text or "EUR" in text:
            currency = "EUR"

        # РР·РІР»РµРєР°РµРј С‡РёСЃР»Р°
        numbers = re.findall(r"[\d\s]+", text)
        numbers = [int(n.replace(" ", "")) for n in numbers if n.strip()]

        salary_from = salary_to = None

        if "РѕС‚" in text.lower() and numbers:
            salary_from = numbers[0]
        elif "РґРѕ" in text.lower() and numbers:
            salary_to = numbers[0]
        elif len(numbers) >= 2:
            salary_from, salary_to = numbers[0], numbers[1]
        elif len(numbers) == 1:
            salary_from = numbers[0]

        return salary_from, salary_to, currency

    def get_vacancy_description(self, vacancy_id: str) -> str:
        """
        Р—Р°РіСЂСѓР¶Р°РµС‚ РїРѕР»РЅРѕРµ РѕРїРёСЃР°РЅРёРµ РІР°РєР°РЅСЃРёРё РїРѕ РµС‘ ID.
        РСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ РґР»СЏ РґРµС‚Р°Р»СЊРЅРѕРіРѕ Р°РЅР°Р»РёР·Р° С‡РµСЂРµР· Gemini.
        """
        url = self.HH_VACANCY_URL.format(vacancy_id)
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"  [РћРЁРР‘РљРђ] РћРїРёСЃР°РЅРёРµ {vacancy_id}: {e}")
            return ""

        soup = BeautifulSoup(response.text, "lxml")

        # Р‘Р»РѕРє СЃ РѕРїРёСЃР°РЅРёРµРј РІР°РєР°РЅСЃРёРё
        desc_block = soup.find("div", attrs={"data-qa": "vacancy-description"})
        if not desc_block:
            # Р—Р°РїР°СЃРЅРѕР№ РІР°СЂРёР°РЅС‚
            desc_block = soup.find("div", class_=re.compile("vacancy-description"))

        if desc_block:
            return desc_block.get_text(separator="\n", strip=True)[:4000]

        return ""

    def enrich_with_descriptions(self, vacancies: list[Vacancy]) -> list[Vacancy]:
        """
        Р—Р°РіСЂСѓР¶Р°РµС‚ РїРѕР»РЅС‹Рµ РѕРїРёСЃР°РЅРёСЏ РґР»СЏ РєР°Р¶РґРѕР№ РІР°РєР°РЅСЃРёРё.
        РќСѓР¶РЅРѕ РїРµСЂРµРґ РѕС‚РїСЂР°РІРєРѕР№ РЅР° Р°РЅР°Р»РёР· РІ Gemini.
        """
        print(f"\n[Р—РђР“Р РЈР—РљРђ РћРџРРЎРђРќРР™] {len(vacancies)} РІР°РєР°РЅСЃРёР№...")

        for i, vacancy in enumerate(vacancies, 1):
            if not vacancy.description:
                desc = self.get_vacancy_description(vacancy.id)
                vacancy.description = desc
                status = "OK" if desc else "РЅРµС‚ С‚РµРєСЃС‚Р°"
                print(f"  [{i}/{len(vacancies)}] {vacancy.title[:40]} вЂ” {status}")
                time.sleep(0.8)  # РїР°СѓР·Р° РјРµР¶РґСѓ Р·Р°РїСЂРѕСЃР°РјРё

        return vacancies

    def search_all_queries(self, enrich: bool = False, include_habr: bool = True) -> list[Vacancy]:
        """
        Р—Р°РїСѓСЃРєР°РµС‚ РїРѕРёСЃРє РїРѕ РІСЃРµРј Р·Р°РїСЂРѕСЃР°Рј РёР· config.SEARCH_QUERIES.
        РС‰РµС‚ РЅР° hh.ru Рё (РѕРїС†РёРѕРЅР°Р»СЊРЅРѕ) Habr Career.
        РђРІС‚РѕРјР°С‚РёС‡РµСЃРєРё СѓР±РёСЂР°РµС‚ РґСѓР±Р»РёСЂСѓСЋС‰РёРµСЃСЏ РІР°РєР°РЅСЃРёРё.

        Args:
            enrich: Р—Р°РіСЂСѓР¶Р°С‚СЊ Р»Рё РїРѕР»РЅС‹Рµ РѕРїРёСЃР°РЅРёСЏ (РЅСѓР¶РЅРѕ РґР»СЏ Р°РЅР°Р»РёР·Р° С‡РµСЂРµР· LLM)
            include_habr: РСЃРєР°С‚СЊ Р»Рё С‚Р°РєР¶Рµ РЅР° Habr Career
        """
        all_vacancies: dict[str, Vacancy] = {}

        # РџРѕРёСЃРє РЅР° hh.ru
        for query in config.SEARCH_QUERIES:
            results = self.search_hh(query)
            for v in results:
                if v.id not in all_vacancies:
                    all_vacancies[v.id] = v

        # РџРѕРёСЃРє РЅР° Habr Career
        if include_habr:
            for query in config.SEARCH_QUERIES:
                results = self.search_habr(query)
                for v in results:
                    if v.id not in all_vacancies:
                        all_vacancies[v.id] = v

        unique_vacancies = list(all_vacancies.values())
        print(f"\n[РРўРћР“Рћ РЈРќРРљРђР›Р¬РќР«РҐ] {len(unique_vacancies)} РІР°РєР°РЅСЃРёР№ (hh.ru + Habr Career)")

        if enrich:
            unique_vacancies = self.enrich_with_descriptions(unique_vacancies)

        return unique_vacancies

    def search_habr(
        self,
        query: str,
        pages: int = 2,
    ) -> list[Vacancy]:
        """
        РС‰РµС‚ РІР°РєР°РЅСЃРёРё РЅР° Habr Career РїРѕ РїРѕРёСЃРєРѕРІРѕРјСѓ Р·Р°РїСЂРѕСЃСѓ.

        Args:
            query: РџРѕРёСЃРєРѕРІС‹Р№ Р·Р°РїСЂРѕСЃ (РЅР°РїСЂРёРјРµСЂ "AI engineer")
            pages: РЎРєРѕР»СЊРєРѕ СЃС‚СЂР°РЅРёС† Р·Р°РіСЂСѓР¶Р°С‚СЊ (РЅР° РєР°Р¶РґРѕР№ ~25 РІР°РєР°РЅСЃРёР№)

        Returns:
            РЎРїРёСЃРѕРє РѕР±СЉРµРєС‚РѕРІ Vacancy
        """
        import urllib3
        urllib3.disable_warnings()

        print(f"[РџРћРРЎРљ] Habr Career: '{query}'")

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
                print(f"  [РћРЁРР‘РљРђ] Habr СЃС‚СЂР°РЅРёС†Р° {page}: {e}")
                break

            soup = BeautifulSoup(response.text, "lxml")
            cards = soup.find_all("div", class_="vacancy-card")

            if not cards:
                print(f"  [РЎРўРћРџ] Habr СЃС‚СЂР°РЅРёС†Р° {page}: РєР°СЂС‚РѕС‡РµРє РЅРµ РЅР°Р№РґРµРЅРѕ")
                break

            print(f"  [РЎРўР  {page}] Habr: РЅР°Р№РґРµРЅРѕ РєР°СЂС‚РѕС‡РµРє: {len(cards)}")

            for card in cards:
                vacancy = self._parse_habr_card(card)
                if vacancy:
                    vacancies.append(vacancy)

            time.sleep(1.0)

        print(f"[РРўРћР“Рћ] Habr '{query}': {len(vacancies)} РІР°РєР°РЅСЃРёР№")

        # Р”РµРґСѓРїР»РёРєР°С†РёСЏ
        seen: dict[str, Vacancy] = {}
        for v in vacancies:
            if v.id not in seen:
                seen[v.id] = v
        return list(seen.values())

    def _parse_habr_card(self, card) -> Optional[Vacancy]:
        """РџР°СЂСЃРёС‚ РѕРґРЅСѓ РєР°СЂС‚РѕС‡РєСѓ РІР°РєР°РЅСЃРёРё СЃ Habr Career."""
        try:
            # РќР°Р·РІР°РЅРёРµ Рё СЃСЃС‹Р»РєР°
            title_tag = card.find("a", class_="vacancy-card__title-link")
            if not title_tag:
                return None

            title = title_tag.get_text(strip=True)
            path  = title_tag.get("href", "")
            if not path:
                return None

            # ID РёР· РїСѓС‚Рё /vacancies/1000XXXXXX
            id_match = re.search(r"/vacancies/(\d+)", path)
            if not id_match:
                return None
            vacancy_id = f"habr_{id_match.group(1)}"
            url = f"{self.HABR_BASE_URL}{path}"

            # РљРѕРјРїР°РЅРёСЏ вЂ” СѓР±РёСЂР°РµРј emoji Рё Р»РёС€РЅРёРµ РїСЂРѕР±РµР»С‹
            comp_tag = card.find("a", class_=lambda x: x and "link-comp" in x)
            company = re.sub(r"[^\w\s\-\.]", "", comp_tag.get_text(strip=True)).strip() if comp_tag else "РќРµ СѓРєР°Р·Р°РЅР°"

            # Р—Р°СЂРїР»Р°С‚Р°
            salary_from, salary_to, salary_currency = self._parse_habr_salary(card)

            # РњРµС‚Р°: СѓСЂРѕРІРµРЅСЊ, СѓРґР°Р»С‘РЅРЅРѕСЃС‚СЊ
            meta_tag = card.find("div", class_=re.compile(r"vacancy-card__meta"))
            meta_text = meta_tag.get_text(" ", strip=True).lower() if meta_tag else ""
            is_remote = "СѓРґР°Р»С‘РЅРЅРѕ" in meta_text or "remote" in meta_text

            # Р”Р°С‚Р° РїСѓР±Р»РёРєР°С†РёРё
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
                location="РЈРґР°Р»С‘РЅРЅРѕ" if is_remote else "РќРµ СѓРєР°Р·Р°РЅРѕ",
                remote=is_remote,
                published_at=published_at,
                source="habr.career",
            )

            # РўРµ Р¶Рµ С„РёР»СЊС‚СЂС‹ С‡С‚Рѕ Рё РґР»СЏ hh.ru
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
        РџР°СЂСЃРёС‚ Р·Р°СЂРїР»Р°С‚Сѓ РёР· РєР°СЂС‚РѕС‡РєРё Habr Career.
        РџСЂРёРјРµСЂС‹: "РѕС‚ 4000 РґРѕ 6000 $", "РѕС‚ 150 000 в‚Ѕ", "200 000 вЂ“ 300 000 в‚Ѕ"
        """
        sal_tag = card.find(class_=re.compile(r"salary"))
        if not sal_tag:
            return None, None, None

        text = sal_tag.get_text(strip=True).replace("\xa0", " ").replace(" ", " ")

        # Р’Р°Р»СЋС‚Р°
        if "$" in text or "USD" in text:
            currency = "USD"
        elif "в‚¬" in text or "EUR" in text:
            currency = "EUR"
        else:
            currency = "RUB"

        numbers = [int(n.replace(" ", "")) for n in re.findall(r"[\d][\d ]+", text) if n.strip()]

        salary_from = salary_to = None
        if "РѕС‚" in text.lower() and "РґРѕ" in text.lower() and len(numbers) >= 2:
            salary_from, salary_to = numbers[0], numbers[1]
        elif "РѕС‚" in text.lower() and numbers:
            salary_from = numbers[0]
        elif "РґРѕ" in text.lower() and numbers:
            salary_to = numbers[0]
        elif len(numbers) >= 2:
            salary_from, salary_to = numbers[0], numbers[1]
        elif len(numbers) == 1:
            salary_from = numbers[0]

        return salary_from, salary_to, currency

    def save_to_json(self, vacancies: list[Vacancy], filename: Optional[str] = None) -> Path:
        """
        РЎРѕС…СЂР°РЅСЏРµС‚ РЅР°Р№РґРµРЅРЅС‹Рµ РІР°РєР°РЅСЃРёРё РІ JSON-С„Р°Р№Р» РІ РїР°РїРєРµ output/.

        Args:
            vacancies: РЎРїРёСЃРѕРє РІР°РєР°РЅСЃРёР№ РґР»СЏ СЃРѕС…СЂР°РЅРµРЅРёСЏ
            filename: РРјСЏ С„Р°Р№Р»Р° (РіРµРЅРµСЂРёСЂСѓРµС‚СЃСЏ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё РµСЃР»Рё РЅРµ СѓРєР°Р·Р°РЅРѕ)

        Returns:
            РџСѓС‚СЊ Рє СЃРѕС…СЂР°РЅС‘РЅРЅРѕРјСѓ С„Р°Р№Р»Сѓ
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

        print(f"[РЎРћРҐР РђРќР•РќРћ] {output_path}")
        return output_path


# в”Ђв”Ђв”Ђ Р—Р°РїСѓСЃРє РґР»СЏ С‚РµСЃС‚РёСЂРѕРІР°РЅРёСЏ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

if __name__ == "__main__":
    searcher = JobSearcher()

    # РўРµСЃС‚: РѕРґРёРЅ Р·Р°РїСЂРѕСЃ, РѕРґРЅР° СЃС‚СЂР°РЅРёС†Р°
    vacancies = searcher.search_hh(
        query="prompt engineer",
        area=113,
        only_remote=True,
        pages=1,
    )

    print(f"\n--- РџРµСЂРІС‹Рµ 5 РІР°РєР°РЅСЃРёР№ ---")
    for v in vacancies[:5]:
        print(f"\n  РљРѕРјРїР°РЅРёСЏ : {v.company}")
        print(f"  Р”РѕР»Р¶РЅРѕСЃС‚СЊ: {v.title}")
        print(f"  Р—Р°СЂРїР»Р°С‚Р° : {v.salary_str()}")
        print(f"  Р›РѕРєР°С†РёСЏ  : {v.location} {'(СѓРґР°Р»С‘РЅРЅРѕ)' if v.remote else ''}")
        print(f"  РЎСЃС‹Р»РєР°   : {v.url}")

    # РЎРѕС…СЂР°РЅСЏРµРј СЂРµР·СѓР»СЊС‚Р°С‚
    if vacancies:
        path = searcher.save_to_json(vacancies, "test_search.json")
        print(f"\nР¤Р°Р№Р» СЃРѕС…СЂР°РЅС‘РЅ: {path}")
