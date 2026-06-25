"""
api.py — REST API на FastAPI для AI Job Hunter Agent
Запуск: uvicorn api:app --reload --port 8000
Документация: http://localhost:8000/docs

Оборачивает существующие модули проекта (searcher, analyzer) в HTTP-эндпоинты,
чтобы агентом можно было пользоваться не только через CLI/Streamlit, но и через API.
"""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from modules.searcher import JobSearcher, Vacancy
from modules.analyzer import VacancyAnalyzer
import config

app = FastAPI(
    title="AI Job Hunter API",
    description="REST API для автономного AI-агента поиска вакансий на hh.ru и Habr Career.",
    version="1.0.0",
)


# ─── Схемы ответов (Pydantic) ──────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = "ok"
    active_profession: str
    model: str


class VacancyShort(BaseModel):
    """Краткое представление вакансии для списков."""
    id: str
    title: str
    company: str
    url: str
    salary: str
    location: str
    remote: bool
    source: str


class ScoreResponse(BaseModel):
    """Результат быстрого keyword-скоринга (без LLM, мгновенно)."""
    vacancy_id: str
    title: str
    keyword_score: int = Field(ge=0, le=100)


# ─── Эндпоинты ─────────────────────────────────────────────────────────────────

@app.get("/", response_model=HealthResponse, tags=["service"])
def health() -> HealthResponse:
    """Проверка, что API жив и возвращает активные настройки."""
    return HealthResponse(
        active_profession=config.ACTIVE_PROFESSION,
        model=config.LLM_MODEL,
    )


@app.get("/presets", tags=["search"])
def list_presets() -> dict:
    """Список доступных пресетов профессий и поисковых запросов к ним."""
    return config.PROFESSION_PRESETS


@app.get("/search", response_model=list[VacancyShort], tags=["search"])
def search_vacancies(
    query: Optional[str] = Query(
        default=None,
        description="Свой поисковый запрос. Если не указан — используются запросы активного пресета.",
    ),
    include_habr: bool = Query(default=True, description="Искать на Habr Career"),
    limit: int = Query(default=50, ge=1, le=500, description="Сколько вакансий вернуть"),
) -> list[VacancyShort]:
    """
    Поиск вакансий на hh.ru (и опционально Habr Career).

    Если `query` не передан — ищет по всем запросам активного пресета из config.py.
    """
    searcher = JobSearcher()

    if query:
        # Один конкретный запрос пользователя
        vacancies = searcher.search_hh(query)
        if include_habr:
            vacancies += searcher.search_habr(query)
    else:
        # Все запросы активного пресета
        vacancies = searcher.search_all_queries(include_habr=include_habr)

    return [
        VacancyShort(
            id=v.id,
            title=v.title,
            company=v.company,
            url=v.url,
            salary=v.salary_str(),
            location=v.location,
            remote=v.remote,
            source=v.source,
        )
        for v in vacancies[:limit]
    ]


@app.post("/score", response_model=ScoreResponse, tags=["analysis"])
def score_vacancy(vacancy: Vacancy) -> ScoreResponse:
    """
    Быстрый keyword-скоринг вакансии (0–100) без обращения к LLM.

    Дёшево и мгновенно: используется для первичного отсева
    перед дорогим LLM-анализом.
    """
    analyzer = VacancyAnalyzer()
    score = analyzer.keyword_score(vacancy)
    return ScoreResponse(
        vacancy_id=vacancy.id,
        title=vacancy.title,
        keyword_score=score,
    )


@app.post("/prefilter", response_model=list[VacancyShort], tags=["analysis"])
def prefilter_vacancies(
    vacancies: list[Vacancy],
    top_n: int = Query(default=30, ge=1, le=200),
) -> list[VacancyShort]:
    """
    Отбирает top-N вакансий по keyword-скорингу — без LLM.
    Этап перед LLM-анализом: отсеивает явный мусор и senior-позиции.
    """
    analyzer = VacancyAnalyzer()
    filtered = analyzer.pre_filter(vacancies, top_n=top_n)
    return [
        VacancyShort(
            id=v.id, title=v.title, company=v.company, url=v.url,
            salary=v.salary_str(), location=v.location, remote=v.remote, source=v.source,
        )
        for v in filtered
    ]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
