"""
cover_letter.py — модуль генерации сопроводительных писем
Создаёт персонализированное письмо под конкретную вакансию
на основе анализа и адаптированного резюме.
"""

import json
import re
from typing import Optional
from datetime import datetime

import config
from modules.llm_client import LLMClient
from modules.analyzer import VacancyAnalysis


# Шаблон письма для fallback (когда нет доступа к Gemini)
FALLBACK_TEMPLATE = """Здравствуйте!

Меня зовут {name}, и я хотел бы откликнуться на вакансию «{vacancy_title}» в компании {company}.

Последние {experience_period} я активно занимаюсь Prompt Engineering и разработкой AI-систем. 
За это время я создал несколько практических проектов, включая {main_project}.

Меня привлекает эта позиция потому что {why_company}. 
Я готов быстро обучаться и вносить реальный вклад с первых недель работы.

Буду рад обсудить детали — напишите мне в Telegram {telegram} или на {email}.

С уважением,
{name}"""


class CoverLetterGenerator:
    """
    Генерирует сопроводительные письма через Gemini.
    Письмо персонализировано под конкретную вакансию и компанию.
    """

    def __init__(self):
        self.llm = LLMClient()
        self.base_resume = self._load_resume()
        print(f"[COVER] Инициализирован. Модель: {self.llm.model}")

    def _load_resume(self) -> dict:
        """Загружает базовое резюме."""
        with open(config.BASE_RESUME_PATH, encoding="utf-8") as f:
            return json.load(f)

    def generate(
        self,
        analysis: VacancyAnalysis,
        adapted_resume: Optional[dict] = None,
        tone: str = "professional",
    ) -> str:
        """
        Генерирует сопроводительное письмо.

        Args:
            analysis: Результат анализа вакансии
            adapted_resume: Адаптированное резюме (опционально, улучшает качество)
            tone: Тон письма — professional / friendly / concise

        Returns:
            Текст письма в Markdown формате
        """
        print(f"[COVER] Генерирую письмо для: {analysis.vacancy_title} | {analysis.company}")

        personal = self.base_resume.get("personal", {})
        projects = self.base_resume.get("projects", [])

        # Берём топ-2 релевантных проекта из анализа или из базового резюме
        relevant_projects = []
        for bonus in analysis.bonus_points:
            for p in projects:
                if p["name"].lower() in bonus.lower():
                    relevant_projects.append(p)
                    break
        if not relevant_projects:
            relevant_projects = projects[:2]

        projects_text = "\n".join(
            f"- {p['name']}: {p['description'][:120]}"
            for p in relevant_projects[:2]
        )

        adapted_summary = ""
        if adapted_resume:
            adapted_summary = f"\nАдаптированное summary:\n{adapted_resume.get('adapted_summary', '')}"
            # Добавляем ключевые слова из адаптированного резюме если есть
            cover_kw = adapted_resume.get("cover_keywords", [])
            if cover_kw:
                adapted_summary += f"\nКлючевые слова для письма: {', '.join(cover_kw[:8])}"

        tone_instructions = {
            "professional": "Профессиональный, деловой тон. Конкретные факты, без лишних слов.",
            "friendly":     "Живой, человечный тон. Чуть менее формально, показывает личность.",
            "concise":      "Очень коротко — максимум 150 слов. Только суть.",
        }

        prompt = f"""Напиши сопроводительное письмо для отклика на вакансию.

## ДАННЫЕ КАНДИДАТА
Имя: {personal.get('name', 'Слава')}
Telegram: {personal.get('telegram', '@ysiSevera')}
Email: {personal.get('email_primary', 'slavarax@gmail.com')}
Опыт: ~2 месяца в Prompt Engineering / AI (Junior уровень)
{adapted_summary}

Ключевые проекты:
{projects_text}

Навыки которые совпадают с вакансией:
{chr(10).join(f'- {s}' for s in analysis.matching_skills)}

## ВАКАНСИЯ
Название: {analysis.vacancy_title}
Компания: {analysis.company}
Главные требования: {', '.join(analysis.key_requirements[:4])}
Советы при отклике: {', '.join(analysis.apply_tips[:2])}

## ИНСТРУКЦИЯ
Тон: {tone_instructions.get(tone, tone_instructions['professional'])}

Напиши письмо на русском языке. Требования:
1. Открывающая строка — НЕ "Здравствуйте, меня зовут...". Начни с чего-то более живого.
2. Упомяни 1-2 конкретных проекта как доказательство навыков
3. Объясни ПОЧЕМУ именно эта компания/вакансия (используй данные из вакансии)
4. Покажи готовность учиться и расти
5. Чёткий call-to-action в конце
6. Длина: 150–250 слов (не больше)
7. Формат: обычный текст, без markdown-заголовков, без ```

Письмо:"""

        try:
            letter = self.llm.chat(
                prompt=prompt,
                temperature=0.7,
                max_tokens=800,
                system="Ты — карьерный консультант. Пишешь живые, убедительные письма на русском языке.",
            )

            if not letter:
                raise ValueError("Пустой ответ от LLM")

            print(f"[COVER] Письмо готово. Слов: {len(letter.split())}")
            return letter

        except Exception as e:
            print(f"[COVER] Ошибка LLM: {e} — использую шаблон")
            return self._fallback_letter(analysis)

    def _fallback_letter(self, analysis: VacancyAnalysis) -> str:
        """
        Генерирует письмо по шаблону если Gemini недоступен.
        Используется как запасной вариант.
        """
        personal = self.base_resume.get("personal", {})
        projects = self.base_resume.get("projects", [])
        main_project = projects[1]["name"] if len(projects) > 1 else "AI Job Hunter Agent"

        return FALLBACK_TEMPLATE.format(
            name=personal.get("name", "Слава"),
            vacancy_title=analysis.vacancy_title,
            company=analysis.company,
            experience_period="2 месяца",
            main_project=main_project,
            why_company=f"меня привлекает работа с {', '.join(analysis.tech_stack[:2])}",
            telegram=personal.get("telegram", "@ysiSevera"),
            email=personal.get("email_primary", "slavarax@gmail.com"),
        )

    def save(self, letter: str, analysis: VacancyAnalysis, filename: str = None) -> str:
        """Сохраняет письмо в Markdown файл."""
        if not filename:
            company_safe = analysis.company.replace(" ", "_")[:20]
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            filename = f"cover_{company_safe}_{ts}.md"

        config.OUTPUT_DIR.mkdir(exist_ok=True)
        path = config.OUTPUT_DIR / filename

        # Добавляем заголовок с метаданными
        content = f"""# Сопроводительное письмо
**Вакансия:** {analysis.vacancy_title}
**Компания:** {analysis.company}
**Score:** {analysis.relevance_score}/100
**Дата:** {datetime.now().strftime('%d.%m.%Y')}

---

{letter}
"""

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        print(f"[COVER] Сохранено: {path}")
        return str(path)


# ─── Тест ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from modules.analyzer import VacancyAnalysis

    test_analysis = VacancyAnalysis(
        vacancy_id="test_001",
        vacancy_title="Prompt Engineer",
        company="TechCorp",
        relevance_score=82,
        match_level="high",
        recommendation="APPLY",
        reasoning="Хорошее совпадение",
        matching_skills=["Prompt Engineering", "Python", "LLM API"],
        missing_skills=["PyTorch"],
        bonus_points=["vacancy-prompt-system проект прямо релевантен"],
        key_requirements=["LLM API", "Python", "Prompt Engineering"],
        tech_stack=["Python", "GPT-4", "LangChain"],
        apply_tips=["Покажи vacancy-prompt-system"],
    )

    generator = CoverLetterGenerator()

    # Тест fallback (без Gemini)
    letter = generator._fallback_letter(test_analysis)
    print("\n[FALLBACK ПИСЬМО]")
    print(letter)

    path = generator.save(letter, test_analysis, "test_cover.md")
    print(f"\nСохранено: {path}")
