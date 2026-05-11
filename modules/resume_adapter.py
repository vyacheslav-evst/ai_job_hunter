"""
resume_adapter.py — модуль адаптации резюме под конкретную вакансию
Берёт базовое резюме, анализ вакансии и через LLM создаёт
адаптированную версию резюме с акцентом на нужные навыки.
"""

import json
from typing import Optional
from datetime import datetime

import config
from modules.llm_client import LLMClient
from modules.analyzer import VacancyAnalysis


class ResumeAdapter:
    """
    Адаптирует базовое резюме под конкретную вакансию.
    Стратегия: не придумываем новые факты, но переставляем акценты,
    перефразируем формулировки под язык вакансии, выдвигаем нужные проекты вперёд.
    """

    def __init__(self):
        self.llm = LLMClient()
        self.base_resume = self._load_base_resume()
        print(f"[ADAPTER] Инициализирован. Модель: {self.llm.model}")

    def _load_base_resume(self) -> dict:
        """Загружает базовое резюме из файла."""
        with open(config.BASE_RESUME_PATH, encoding="utf-8") as f:
            return json.load(f)

    def adapt(self, analysis: VacancyAnalysis) -> dict:
        """
        Создаёт адаптированную версию резюме под конкретную вакансию.

        Args:
            analysis: Результат анализа вакансии через analyzer.py

        Returns:
            Словарь с адаптированным резюме (готов для exporter.py)
        """
        print(f"[ADAPTER] Адаптирую резюме под: {analysis.vacancy_title} | {analysis.company}")

        prompt = f"""Ты — карьерный консультант. Адаптируй резюме кандидата под конкретную вакансию.

## БАЗОВОЕ РЕЗЮМЕ (JSON)
{json.dumps(self.base_resume, ensure_ascii=False, indent=2)[:4000]}

## ВАКАНСИЯ
Название: {analysis.vacancy_title}
Компания: {analysis.company}

Ключевые требования вакансии:
{chr(10).join(f'- {r}' for r in analysis.key_requirements)}

Технический стек:
{chr(10).join(f'- {t}' for t in analysis.tech_stack)}

Что совпадает у кандидата:
{chr(10).join(f'- {s}' for s in analysis.matching_skills)}

Сильные стороны кандидата под эту вакансию:
{chr(10).join(f'- {b}' for b in analysis.bonus_points)}

## ЗАДАЧА
Создай адаптированную версию резюме. Верни ТОЛЬКО валидный JSON без ```json.

Правила:
1. НЕ придумывай новые факты, навыки или опыт которого нет в базовом резюме
2. Переформулируй summary под язык этой вакансии
3. Выдвини вперёд проекты и навыки которые релевантны этой вакансии
4. Добавь ключевые слова из вакансии туда где они честно подходят
5. Сократи нерелевантные части
6. Сохрани все реальные данные (имя, контакты, проекты)

Структура JSON:
{{
  "vacancy_title": "{analysis.vacancy_title}",
  "company": "{analysis.company}",
  "adapted_summary": "переписанное summary под эту вакансию",
  "top_skills": ["топ-7 навыков релевантных этой вакансии"],
  "featured_projects": [
    {{
      "name": "название проекта",
      "description": "переформулированное описание акцентом на релевантность",
      "highlights": ["ключевой результат 1", "ключевой результат 2"]
    }}
  ],
  "additional_skills": ["остальные навыки"],
  "cover_keywords": ["ключевые слова из вакансии для cover letter"]
}}"""

        try:
            adapted = self.llm.chat_json(prompt, temperature=0.3, max_tokens=2000)

            if not adapted:
                raise ValueError("Пустой ответ от LLM")

            # Добавляем неизменяемые личные данные из базового резюме
            adapted["personal"] = self.base_resume.get("personal", {})
            adapted["education"] = self.base_resume.get("education", {})
            adapted["generated_at"] = datetime.now().isoformat()

            print(f"[ADAPTER] Готово. Топ навыков: {len(adapted.get('top_skills', []))}")
            return adapted

        except Exception as e:
            print(f"[ADAPTER] Ошибка LLM: {e}")
            # Возвращаем базовое резюме без изменений как fallback
            return {
                "vacancy_title": analysis.vacancy_title,
                "company": analysis.company,
                "adapted_summary": self.base_resume.get("summary", ""),
                "top_skills": self.base_resume.get("skills", {}).get("prompt_engineering", []),
                "featured_projects": self.base_resume.get("projects", [])[:3],
                "additional_skills": [],
                "cover_keywords": analysis.tech_stack,
                "personal": self.base_resume.get("personal", {}),
                "education": self.base_resume.get("education", {}),
                "generated_at": datetime.now().isoformat(),
                "fallback": True,
            }

    def save(self, adapted_resume: dict, filename: str = None) -> str:
        """Сохраняет адаптированное резюме в JSON."""
        if not filename:
            company_safe = adapted_resume.get("company", "unknown").replace(" ", "_")[:20]
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            filename = f"resume_{company_safe}_{ts}.json"

        config.OUTPUT_DIR.mkdir(exist_ok=True)
        path = config.OUTPUT_DIR / filename

        with open(path, "w", encoding="utf-8") as f:
            json.dump(adapted_resume, f, ensure_ascii=False, indent=2)

        print(f"[ADAPTER] Сохранено: {path}")
        return str(path)


# ─── Тест ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from modules.analyzer import VacancyAnalysis

    # Создаём тестовый анализ (без реального вызова API)
    test_analysis = VacancyAnalysis(
        vacancy_id="test_001",
        vacancy_title="Prompt Engineer / AI Engineer",
        company="TechCorp",
        relevance_score=82,
        match_level="high",
        recommendation="APPLY",
        reasoning="Хорошее совпадение по Prompt Engineering навыкам",
        matching_skills=["Prompt Engineering", "Python", "LLM API", "JSON Schema"],
        missing_skills=["PyTorch", "fine-tuning"],
        bonus_points=["vacancy-prompt-system — прямо релевантный проект"],
        key_requirements=["Опыт с LLM API", "Python", "Prompt Engineering"],
        tech_stack=["Python", "GPT-4", "LangChain", "FastAPI"],
        apply_tips=["Покажи vacancy-prompt-system как пример работы"],
    )

    adapter = ResumeAdapter()
    result = adapter.adapt(test_analysis)
    print("\n[РЕЗУЛЬТАТ]")
    print(f"Summary: {result.get('adapted_summary', '')[:200]}")
    print(f"Top skills: {result.get('top_skills', [])}")
