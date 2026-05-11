"""
analyzer.py — модуль анализа вакансий через LLM
Оценивает релевантность вакансии для кандидата, извлекает ключевые требования,
и выдаёт структурированный JSON-отчёт.
"""

import json
import re
import os
import time
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field

import config
from modules.llm_client import LLMClient
from modules.searcher import Vacancy


# ─── Модель результата анализа (Pydantic) ─────────────────────────────────────

class VacancyAnalysis(BaseModel):
    """Результат анализа одной вакансии через Gemini."""

    vacancy_id: str
    vacancy_title: str
    company: str

    # Скоринг
    relevance_score: int = Field(ge=0, le=100, description="Общая релевантность 0–100")
    match_level: str = Field(description="low / medium / high")

    # Что совпадает / не совпадает
    matching_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    bonus_points: list[str] = Field(default_factory=list, description="Наши сильные стороны под эту вакансию")

    # Ключевая информация из вакансии
    key_requirements: list[str] = Field(default_factory=list)
    main_tasks: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)

    # Рекомендации агента
    recommendation: str = Field(description="APPLY / SKIP / MAYBE")
    reasoning: str = Field(description="Краткое объяснение решения")
    apply_tips: list[str] = Field(default_factory=list, description="Советы при отклике")


# ─── Основной класс анализатора ───────────────────────────────────────────────

class VacancyAnalyzer:
    """
    Анализирует вакансии через Google Gemini.
    Сравнивает требования вакансии с профилем кандидата из base_resume.json.
    """

    def __init__(self) -> None:

        # Загружаем базовое резюме кандидата
        self.resume = self._load_resume()

        print(f"[ANALYZER] Инициализирован. Модель: {self.llm.model}")

    def _load_resume(self) -> dict:
        """Загружает базовое резюме из memory/base_resume.json."""
        if not config.BASE_RESUME_PATH.exists():
            raise FileNotFoundError(
                f"Файл резюме не найден: {config.BASE_RESUME_PATH}\n"
                "Убедись что memory/base_resume.json существует."
            )
        with open(config.BASE_RESUME_PATH, encoding="utf-8") as f:
            return json.load(f)

    def _build_candidate_profile(self) -> str:
        """
        Формирует краткий текстовый профиль кандидата для промпта.
        Берём самое важное из резюме — не весь JSON целиком.
        """
        r = self.resume
        personal = r.get("personal", {})
        skills = r.get("skills", {})
        projects = r.get("projects", [])

        # Строим компактный профиль
        profile_parts = [
            f"Имя: {personal.get('name', 'Слава')}",
            f"Цель: {', '.join(r.get('target_roles', []))}",
            f"Опыт: {r.get('experience_notes', '')}",
            "",
            "НАВЫКИ Prompt Engineering:",
            *[f"  - {s}" for s in skills.get("prompt_engineering", [])],
            "",
            "НАВЫКИ AI/LLM:",
            *[f"  - {s}" for s in skills.get("ai_development", [])],
            "",
            "НАВЫКИ Программирование:",
            *[f"  - {s}" for s in skills.get("programming", [])],
            "",
            "ПРОЕКТЫ:",
        ]

        for p in projects[:4]:  # берём топ-4 проекта
            profile_parts.append(f"  - {p['name']} ({p['status']}): {p['description'][:100]}...")

        return "\n".join(profile_parts)

    def analyze_vacancy(self, vacancy: Vacancy) -> Optional[VacancyAnalysis]:
        """
        Анализирует одну вакансию через Gemini.
        Возвращает структурированный отчёт с рекомендацией.

        Args:
            vacancy: Объект вакансии (должен иметь description)

        Returns:
            VacancyAnalysis или None если анализ не удался
        """
        # Если нет описания — анализировать нечего
        if not vacancy.description:
            print(f"  [ПРОПУСК] {vacancy.title} — нет описания")
            return None

        print(f"  [АНАЛИЗ] {vacancy.title} | {vacancy.company}")

        candidate_profile = self._build_candidate_profile()

        # ── Промпт ──────────────────────────────────────────────────────────
        # Используем JSON-first подход: температура 0.1 для детерминизма,
        # явная инструкция вернуть ТОЛЬКО JSON без markdown-обёртки.
        prompt = f"""Ты — карьерный аналитик. Оцени насколько вакансия подходит кандидату.

## ПРОФИЛЬ КАНДИДАТА
{candidate_profile}

## ВАКАНСИЯ
Название: {vacancy.title}
Компания: {vacancy.company}
Зарплата: {vacancy.salary_str()}
Локация: {vacancy.location} {'(удалённо)' if vacancy.remote else ''}

Описание:
{vacancy.description[:3000]}

## ЗАДАЧА
Проанализируй вакансию и верни ТОЛЬКО валидный JSON (без ```json, без пояснений).

Структура JSON:
{{
  "relevance_score": <число 0-100>,
  "match_level": "<low|medium|high>",
  "matching_skills": ["навык1", "навык2"],
  "missing_skills": ["навык1", "навык2"],
  "bonus_points": ["сильная сторона кандидата под эту вакансию"],
  "key_requirements": ["требование1", "требование2"],
  "main_tasks": ["задача1", "задача2"],
  "tech_stack": ["технология1", "технология2"],
  "recommendation": "<APPLY|MAYBE|SKIP>",
  "reasoning": "Краткое объяснение на русском (2-3 предложения)",
  "apply_tips": ["совет при отклике 1", "совет 2"]
}}

Правила оценки:
- relevance_score 80-100: отличное совпадение, рекомендация APPLY
- relevance_score 50-79: частичное совпадение, рекомендация MAYBE
- relevance_score 0-49: слабое совпадение, рекомендация SKIP
- Кандидат — джун с ~2 месяцами практики, ищет ПЕРВУЮ работу в AI. Нет коммерческого опыта.
- Если вакансия требует Senior / Lead / Ведущий / Team Lead / 3+ лет опыта — ставь score не выше 25 и recommendation SKIP
- Если вакансия требует Middle / 1-2 года опыта — ставь score не выше 45 и recommendation MAYBE
- Подходящие вакансии: Junior, стажёр, trainee, без опыта, до 1 года опыта
- В bonus_points укажи конкретные проекты кандидата которые релевантны этой вакансии"""

        try:
            raw_text = self.llm.chat_json(prompt)

            if not raw_text:
                # chat_json вернул None — пробуем chat() + ручной парсинг
                raw_str = self.llm.chat(prompt, temperature=0.1)
                if not raw_str:
                    print(f"    [ОШИБКА] Пустой ответ от LLM")
                    return None
                raw_text = self._parse_json_response(raw_str)
                if not raw_text:
                    print(f"    [ОШИБКА] Не удалось распарсить JSON из ответа LLM")
                    return None

            analysis_dict = raw_text

            # Добавляем метаданные вакансии
            analysis_dict["vacancy_id"] = vacancy.id
            analysis_dict["vacancy_title"] = vacancy.title
            analysis_dict["company"] = vacancy.company

            return VacancyAnalysis(**analysis_dict)

        except Exception as e:
            print(f"    [ОШИБКА] LLM: {e}")
            return None

    def _parse_json_response(self, text: str) -> Optional[dict]:
        """
        Парсит JSON из ответа модели.
        Модель иногда оборачивает JSON в ```json ... ``` — убираем это.
        """
        # Убираем markdown-блоки если есть
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text)
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Пытаемся найти JSON-объект внутри текста
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            return None

    def analyze_batch(self, vacancies: list[Vacancy]) -> list[VacancyAnalysis]:
        """
        Анализирует список вакансий и возвращает только те,
        что прошли порог релевантности (config.RELEVANCE_THRESHOLD).

        Args:
            vacancies: Список вакансий с описаниями

        Returns:
            Отфильтрованный и отсортированный список анализов
        """
        print(f"\n[BATCH АНАЛИЗ] {len(vacancies)} вакансий через {self.llm.model}")
        print(f"[ПОРОГ] Минимальный score: {config.RELEVANCE_THRESHOLD}")

        results = []

        for i, vacancy in enumerate(vacancies, 1):
            print(f"\n  [{i}/{len(vacancies)}]", end=" ")
            analysis = self.analyze_vacancy(vacancy)

            if analysis:
                if analysis.relevance_score >= config.RELEVANCE_THRESHOLD:
                    results.append(analysis)
                    print(f"    -> Score: {analysis.relevance_score} | {analysis.recommendation} ✓")
                else:
                    print(f"    -> Score: {analysis.relevance_score} | ниже порога, пропускаем")

            # Пауза между запросами чтобы не превысить rate limit
            if i < len(vacancies):
                time.sleep(3)

        # Сортируем по убыванию релевантности
        results.sort(key=lambda x: x.relevance_score, reverse=True)

        print(f"\n[РЕЗУЛЬТАТ] Прошли порог: {len(results)} из {len(vacancies)} вакансий")
        return results

    def save_analysis(self, analyses: list[VacancyAnalysis], filename: str = None) -> str:
        """Сохраняет результаты анализа в JSON."""
        from datetime import datetime

        if not filename:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"analysis_{ts}.json"

        config.OUTPUT_DIR.mkdir(exist_ok=True)
        output_path = config.OUTPUT_DIR / filename

        data = {
            "generated_at": datetime.now().isoformat(),
            "model": self.llm.model,
            "threshold": config.RELEVANCE_THRESHOLD,
            "total_passed": len(analyses),
            "analyses": [a.model_dump() for a in analyses],
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"[СОХРАНЕНО] {output_path}")
        return str(output_path)


# ─── Запуск для тестирования ──────────────────────────────────────────────────

if __name__ == "__main__":
    from modules.searcher import JobSearcher

    # Шаг 1: ищем вакансии
    searcher = JobSearcher()
    vacancies = searcher.search_hh(query="prompt engineer", area=113, only_remote=True, pages=1)

    if not vacancies:
        print("Вакансии не найдены — проверь соединение")
        exit(1)

    # Шаг 2: загружаем описание для первой вакансии
    print("\n[ТЕСТ] Загружаем описание первой вакансии...")
    test_vacancy = vacancies[0]
    test_vacancy.description = searcher.get_vacancy_description(test_vacancy.id)

    print(f"Описание загружено: {len(test_vacancy.description)} символов")

    # Шаг 3: анализируем через LLM
    print("\n[ТЕСТ] Запускаем анализ через LLM...")
    analyzer = VacancyAnalyzer()
    analysis = analyzer.analyze_vacancy(test_vacancy)

    if analysis:
        print(f"\n{'='*50}")
        print(f"ВАКАНСИЯ : {analysis.vacancy_title}")
        print(f"КОМПАНИЯ : {analysis.company}")
        print(f"SCORE    : {analysis.relevance_score}/100 ({analysis.match_level})")
        print(f"РЕШЕНИЕ  : {analysis.recommendation}")
        print(f"ПРИЧИНА  : {analysis.reasoning}")
        print(f"\nСОВПАДАЮТ : {', '.join(analysis.matching_skills[:3])}")
        print(f"НЕ ХВАТАЕТ: {', '.join(analysis.missing_skills[:3])}")
        print(f"\nСОВЕТЫ:")
        for tip in analysis.apply_tips:
            print(f"  - {tip}")
        print(f"{'='*50}")
    else:
        print("Анализ не удался")
