"""
interview_prep.py — модуль подготовки к собеседованию.

Генерирует персонализированные вопросы на основе конкретной вакансии
и резюме кандидата:
  - вопросы которые зададут кандидату (с подсказками как отвечать)
  - вопросы которые кандидат может задать компании
"""

import json
import re
from typing import Optional

import config
from modules.llm_client import LLMClient
from modules.analyzer import VacancyAnalysis


class InterviewPrep:
    """
    Генерирует вопросы для подготовки к собеседованию.
    Персонализирует под конкретную вакансию и профиль кандидата.
    """

    def __init__(self) -> None:
        self.llm = LLMClient()
        self.base_resume: dict = self._load_resume()
        print(f"[INTERVIEW] Инициализирован. Модель: {self.llm.model}")

    def _load_resume(self) -> dict:
        """Загружает базовое резюме кандидата."""
        with open(config.BASE_RESUME_PATH, encoding="utf-8") as f:
            return json.load(f)

    def _build_candidate_summary(self) -> str:
        """Формирует краткий текстовый профиль кандидата для промпта."""
        r = self.base_resume
        skills = r.get("skills", {})
        projects = r.get("projects", [])

        lines = [
            f"Имя: {r.get('personal', {}).get('name', 'Кандидат')}",
            f"Уровень: Junior, ~2 месяца практики в AI/Prompt Engineering",
            f"Опыт: {r.get('experience_notes', '')}",
            "",
            "Навыки Prompt Engineering: " + ", ".join(skills.get("prompt_engineering", [])[:4]),
            "Навыки AI/Dev: " + ", ".join(skills.get("ai_development", [])[:4]),
            "Программирование: " + ", ".join(skills.get("programming", [])[:4]),
            "",
            "Проекты:",
        ]
        for p in projects[:4]:
            lines.append(f"  - {p['name']}: {p['description'][:100]}")

        return "\n".join(lines)

    def generate(self, analysis: VacancyAnalysis) -> Optional[dict]:
        """
        Генерирует вопросы для подготовки к собеседованию.

        Args:
            analysis: Результат анализа вакансии

        Returns:
            Словарь с ключами:
              - questions_for_me: list[dict] — {question, hint}
              - questions_for_them: list[str]
            или None при ошибке LLM
        """
        print(f"[INTERVIEW] Генерирую вопросы для: {analysis.vacancy_title} | {analysis.company}")

        candidate = self._build_candidate_summary()

        prompt = f"""Ты — опытный HR-консультант. Помоги кандидату подготовиться к собеседованию.

## ПРОФИЛЬ КАНДИДАТА
{candidate}

Совпадающие навыки с вакансией: {', '.join(analysis.matching_skills[:6])}
Слабые стороны (чего не хватает): {', '.join(analysis.missing_skills[:4])}
Сильные стороны под эту вакансию: {', '.join(analysis.bonus_points[:3])}

## ВАКАНСИЯ
Название: {analysis.vacancy_title}
Компания: {analysis.company}
Ключевые требования: {', '.join(analysis.key_requirements[:6])}
Основные задачи: {', '.join(analysis.main_tasks[:4])}
Стек: {', '.join(analysis.tech_stack[:6])}

## ЗАДАЧА
Сгенерируй вопросы для подготовки к собеседованию. Верни ТОЛЬКО валидный JSON без ```json.

Формат:
{{
  "questions_for_me": [
    {{
      "question": "Вопрос который зададут кандидату",
      "hint": "Краткая подсказка как ответить, ссылаясь на конкретные проекты/навыки кандидата"
    }}
  ],
  "questions_for_them": [
    "Вопрос который кандидат может задать компании"
  ]
}}

Требования:
- questions_for_me: 6–8 вопросов, заточенных под ЭТУ вакансию и ЭТОТ профиль кандидата
- questions_for_them: 4–5 вопросов (о стеке, процессах, онбординге, росте)
- hint: конкретный, ссылается на реальные проекты кандидата из профиля выше
- Вопросы на русском языке
- Учитывай что кандидат — джун без коммерческого опыта"""

        try:
            result = self.llm.chat_json(prompt)

            if not result:
                # Fallback: пробуем chat() + ручной парсинг
                raw = self.llm.chat(prompt, temperature=0.3)
                if not raw:
                    return None
                result = self._parse_json(raw)

            if not result:
                return None

            # Валидируем структуру
            if "questions_for_me" not in result or "questions_for_them" not in result:
                return None

            print(f"[INTERVIEW] Готово: {len(result['questions_for_me'])} вопросов к кандидату, "
                  f"{len(result['questions_for_them'])} — компании")
            return result

        except Exception as e:
            print(f"[INTERVIEW] Ошибка LLM: {e}")
            return None

    def _parse_json(self, text: str) -> Optional[dict]:
        """Парсит JSON из ответа модели (убирает markdown-обёртку если есть)."""
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text)
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
        return None
