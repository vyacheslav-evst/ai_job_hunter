# -*- coding: utf-8 -*-
"""
exporter.py — модуль экспорта результатов
Экспортирует резюме и отчёты в форматы: Markdown, JSON, PDF.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional

import config
from modules.analyzer import VacancyAnalysis


class Exporter:
    """
    Экспортирует данные агента в различные форматы.
    - JSON: машиночитаемый формат для хранения и передачи
    - Markdown: красивый текст для просмотра
    - PDF: для отправки работодателям
    """

    def __init__(self) -> None:
        config.OUTPUT_DIR.mkdir(exist_ok=True)

    # ─── JSON ─────────────────────────────────────────────────────────────────

    def export_json(self, data: dict | list, filename: str) -> Path:
        """Сохраняет данные в JSON файл."""
        path = config.OUTPUT_DIR / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[JSON] Сохранено: {path}")
        return path

    # ─── Markdown ─────────────────────────────────────────────────────────────

    def export_resume_md(self, adapted_resume: dict, filename: str = None) -> Path:
        """
        Экспортирует адаптированное резюме в Markdown.
        Читаемый формат — можно открыть в любом редакторе или GitHub.
        """
        if not filename:
            company = adapted_resume.get("company", "unknown").replace(" ", "_")[:20]
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            filename = f"resume_{company}_{ts}.md"

        personal = adapted_resume.get("personal", {})
        name = personal.get("name", "Слава")
        telegram = personal.get("telegram", "@ysiSevera")
        email = personal.get("email_primary", "slavarax@gmail.com")

        lines = [
            f"# {name} — {adapted_resume.get('vacancy_title', 'AI Engineer')}",
            f"",
            f"📬 {email} | Telegram: {telegram} | Удалённо",
            f"",
            f"---",
            f"",
            f"## О себе",
            f"",
            adapted_resume.get("adapted_summary", ""),
            f"",
            f"---",
            f"",
            f"## Ключевые навыки",
            f"",
        ]

        for skill in adapted_resume.get("top_skills", []):
            lines.append(f"- {skill}")

        lines += ["", "---", "", "## Проекты", ""]

        for project in adapted_resume.get("featured_projects", []):
            lines.append(f"### {project.get('name', 'Проект')}")
            lines.append(f"")
            lines.append(project.get("description", ""))
            lines.append(f"")
            for h in project.get("highlights", []):
                lines.append(f"- {h}")
            lines.append(f"")

        # Дополнительные навыки
        additional = adapted_resume.get("additional_skills", [])
        if additional:
            lines += ["---", "", "## Дополнительно", ""]
            for s in additional:
                lines.append(f"- {s}")
            lines.append("")

        # Образование
        edu = adapted_resume.get("education", {})
        if edu:
            lines += ["---", "", "## Образование", ""]
            lines.append(f"- {edu.get('formal', 'Незаконченное высшее')}")
            for item in edu.get("self_education", []):
                lines.append(f"- {item}")

        lines += [
            "", "---",
            f"",
            f"*Резюме адаптировано под вакансию {adapted_resume.get('vacancy_title', '')}*",
            f"*{adapted_resume.get('generated_at', '')[:10]}*",
        ]

        path = config.OUTPUT_DIR / filename
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        print(f"[MD] Резюме сохранено: {path}")
        return path

    def export_analysis_md(self, analyses: list[VacancyAnalysis], filename: str = None) -> Path:
        """
        Экспортирует отчёт по результатам анализа вакансий в Markdown.
        Удобный дашборд для просмотра — что откликать, что пропустить.
        """
        if not filename:
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            filename = f"report_{ts}.md"

        lines = [
            f"# AI Job Hunter — Отчёт по вакансиям",
            f"",
            f"**Дата:** {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            f"**Вакансий найдено:** {len(analyses)}",
            f"**Порог релевантности:** {config.RELEVANCE_THRESHOLD}/100",
            f"",
            f"---",
            f"",
        ]

        # Группируем по рекомендации
        apply = [a for a in analyses if a.recommendation == "APPLY"]
        maybe = [a for a in analyses if a.recommendation == "MAYBE"]
        skip  = [a for a in analyses if a.recommendation == "SKIP"]

        lines += [
            f"## Сводка",
            f"",
            f"| Решение | Кол-во |",
            f"|---------|--------|",
            f"| ✅ APPLY | {len(apply)} |",
            f"| 🤔 MAYBE | {len(maybe)} |",
            f"| ❌ SKIP  | {len(skip)} |",
            f"",
            f"---",
            f"",
        ]

        # Секция APPLY
        if apply:
            lines += ["## ✅ Рекомендуется откликнуться", ""]
            for a in apply:
                lines += self._format_analysis_block(a)

        # Секция MAYBE
        if maybe:
            lines += ["## 🤔 Возможно стоит рассмотреть", ""]
            for a in maybe:
                lines += self._format_analysis_block(a)

        # Секция SKIP
        if skip:
            lines += ["## ❌ Не подходит", ""]
            for a in skip:
                lines += self._format_analysis_block(a)

        path = config.OUTPUT_DIR / filename
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        print(f"[MD] Отчёт сохранён: {path}")
        return path

    def _format_analysis_block(self, a: VacancyAnalysis) -> list[str]:
        """Форматирует блок одной вакансии для Markdown-отчёта."""
        vacancy_url = f"https://hh.ru/vacancy/{a.vacancy_id}"
        return [
            f"### [{a.vacancy_title}]({vacancy_url}) — {a.company}",
            f"",
            f"**Score:** {a.relevance_score}/100 | **Уровень:** {a.match_level}",
            f"",
            f"**Вывод:** {a.reasoning}",
            f"",
            f"**Совпадает:** {', '.join(a.matching_skills[:4])}",
            f"",
            f"**Не хватает:** {', '.join(a.missing_skills[:3]) if a.missing_skills else 'ничего критичного'}",
            f"",
            f"**Советы при отклике:**",
            *[f"- {tip}" for tip in a.apply_tips],
            f"",
            f"---",
            f"",
        ]

    # ─── PDF ──────────────────────────────────────────────────────────────────

    def export_resume_pdf(self, adapted_resume: dict, filename: str = None) -> Optional[Path]:
        """
        Экспортирует резюме в PDF через fpdf2.
        PDF отправляется работодателю напрямую.
        """
        try:
            from fpdf import FPDF, XPos, YPos
        except ImportError:
            print("[PDF] fpdf2 не установлен. Установи: pip install fpdf2")
            return None

        if not filename:
            company = adapted_resume.get("company", "unknown").replace(" ", "_")[:20]
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            filename = f"resume_{company}_{ts}.pdf"

        personal = adapted_resume.get("personal", {})
        name = personal.get("name", "Слава")

        pdf = FPDF()
        pdf.add_page()

        font_name = self._init_pdf_fonts(pdf)

        # ── Заголовок ─────────────────────────────────────────────────────────
        pdf.set_font(font_name, "B", 18)
        pdf.cell(0, 10, name, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")

        pdf.set_font(font_name, "", 11)
        target = adapted_resume.get("vacancy_title", "AI Engineer")
        pdf.cell(0, 6, target, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")

        # Контакты
        pdf.set_font(font_name, "", 9)
        contacts = f"{personal.get('email_primary', '')} | {personal.get('telegram', '')} | Удалённо"
        pdf.cell(0, 5, contacts, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        pdf.ln(3)

        # ── Разделитель ───────────────────────────────────────────────────────
        pdf.set_draw_color(100, 100, 100)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(4)

        # ── О себе ────────────────────────────────────────────────────────────
        self._pdf_section_header(pdf, font_name, "О СЕБЕ")
        pdf.set_font(font_name, "", 10)
        summary = adapted_resume.get("adapted_summary", "")
        pdf.multi_cell(0, 5, summary)
        pdf.ln(3)

        # ── Навыки ────────────────────────────────────────────────────────────
        self._pdf_section_header(pdf, font_name, "КЛЮЧЕВЫЕ НАВЫКИ")
        pdf.set_font(font_name, "", 10)
        skills = adapted_resume.get("top_skills", [])
        # Выводим навыки в 2 колонки
        col_width = 90
        for i, skill in enumerate(skills):
            x = 10 if i % 2 == 0 else 105
            if i % 2 == 0 and i > 0:
                pdf.ln(0)
            pdf.set_x(x)
            pdf.cell(col_width, 5, f"• {skill}")
            if i % 2 == 1:
                pdf.ln(5)
        pdf.ln(5)

        # ── Проекты ───────────────────────────────────────────────────────────
        self._pdf_section_header(pdf, font_name, "ПРОЕКТЫ")
        for project in adapted_resume.get("featured_projects", [])[:3]:
            pdf.set_font(font_name, "B", 10)
            pdf.cell(0, 6, project.get("name", ""), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_font(font_name, "", 9)
            pdf.multi_cell(0, 4, project.get("description", ""))
            for h in project.get("highlights", [])[:3]:
                pdf.cell(5)
                pdf.cell(0, 4, f"— {h}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(2)

        # ── Образование ───────────────────────────────────────────────────────
        edu = adapted_resume.get("education", {})
        if edu:
            self._pdf_section_header(pdf, font_name, "ОБРАЗОВАНИЕ")
            pdf.set_font(font_name, "", 10)
            pdf.cell(0, 5, edu.get("formal", "Незаконченное высшее"),
                     new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            for item in edu.get("self_education", [])[:3]:
                pdf.cell(0, 4, f"• {item}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        path = config.OUTPUT_DIR / filename
        pdf.output(str(path))
        print(f"[PDF] Резюме сохранено: {path}")
        return path

    def _pdf_section_header(self, pdf, font_name: str, title: str) -> None:
        """Рисует заголовок секции в PDF."""
        from fpdf import XPos, YPos
        pdf.set_font(font_name, "B", 11)
        pdf.set_fill_color(240, 240, 240)
        pdf.cell(0, 7, f"  {title}", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(2)

    def _init_pdf_fonts(self, pdf) -> str:
        """Инициализирует шрифты PDF с поддержкой кириллицы. Возвращает имя шрифта."""
        import platform

        # Кандидаты шрифтов для разных ОС (порядок приоритета)
        font_candidates = []

        if platform.system() == "Windows":
            font_candidates = [
                (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
                (r"C:\Windows\Fonts\verdana.ttf", r"C:\Windows\Fonts\verdanab.ttf"),
            ]
        elif platform.system() == "Darwin":  # macOS
            font_candidates = [
                ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Helvetica.ttc"),
                ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
                ("/System/Library/Fonts/SFNSText.ttf", "/System/Library/Fonts/SFNSText.ttf"),
            ]
        else:  # Linux
            font_candidates = [
                ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
                ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                 "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
                ("/usr/share/fonts/truetype/freefont/FreeSans.ttf",
                 "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"),
            ]

        for regular_path, bold_path in font_candidates:
            if Path(regular_path).exists():
                pdf.add_font("CustomFont", "", regular_path)
                if Path(bold_path).exists():
                    pdf.add_font("CustomFont", "B", bold_path)
                return "CustomFont"

        print("[PDF] Предупреждение: шрифт с кириллицей не найден, текст может не отображаться.")
        return "Helvetica"

    def export_cover_letter_pdf(self, letter: str, analysis: "VacancyAnalysis", filename: str = None) -> Optional[Path]:
        """
        Экспортирует сопроводительное письмо в PDF.
        """
        try:
            from fpdf import FPDF, XPos, YPos
        except ImportError:
            print("[PDF] fpdf2 не установлен.")
            return None

        if not filename:
            company = analysis.company.replace(" ", "_")[:20]
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            filename = f"cover_{company}_{ts}.pdf"

        pdf = FPDF()
        pdf.add_page()
        font_name = self._init_pdf_fonts(pdf)

        # Заголовок
        pdf.set_font(font_name, "B", 16)
        pdf.cell(0, 10, "Сопроводительное письмо", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        pdf.ln(2)

        # Метаданные
        pdf.set_font(font_name, "", 10)
        pdf.set_fill_color(240, 240, 240)
        pdf.cell(0, 6, f"  Вакансия: {analysis.vacancy_title} | Компания: {analysis.company} | Score: {analysis.relevance_score}/100",
                 fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 6, f"  Дата: {datetime.now().strftime('%d.%m.%Y')}",
                 fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(5)

        # Текст письма
        pdf.set_font(font_name, "", 11)
        pdf.set_draw_color(100, 100, 100)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(4)
        pdf.multi_cell(0, 6, letter)

        path = config.OUTPUT_DIR / filename
        pdf.output(str(path))
        print(f"[PDF] Письмо сохранено: {path}")
        return path

    def export_analysis_pdf(self, analyses: list["VacancyAnalysis"], filename: str = None) -> Optional[Path]:
        """
        Экспортирует итоговый отчёт по вакансиям в PDF.
        """
        try:
            from fpdf import FPDF, XPos, YPos
        except ImportError:
            print("[PDF] fpdf2 не установлен.")
            return None

        if not filename:
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            filename = f"report_{ts}.pdf"

        pdf = FPDF()
        pdf.add_page()
        font_name = self._init_pdf_fonts(pdf)

        # Заголовок
        pdf.set_font(font_name, "B", 16)
        pdf.cell(0, 10, "AI Job Hunter — Отчёт по вакансиям", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        pdf.ln(2)

        # Сводка
        apply  = [a for a in analyses if a.recommendation == "APPLY"]
        maybe  = [a for a in analyses if a.recommendation == "MAYBE"]
        skip   = [a for a in analyses if a.recommendation == "SKIP"]

        pdf.set_font(font_name, "", 10)
        pdf.set_fill_color(240, 240, 240)
        pdf.cell(0, 6, f"  Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')} | "
                       f"Всего: {len(analyses)} | APPLY: {len(apply)} | MAYBE: {len(maybe)} | SKIP: {len(skip)}",
                 fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(4)

        rec_labels = {"APPLY": "APPLY", "MAYBE": "MAYBE", "SKIP": "SKIP"}
        rec_colors = {
            "APPLY": (0, 150, 0),
            "MAYBE": (200, 130, 0),
            "SKIP":  (180, 0, 0),
        }

        for a in analyses:
            # Новая страница если мало места
            if pdf.get_y() > 250:
                pdf.add_page()

            # Название вакансии
            pdf.set_font(font_name, "B", 11)
            color = rec_colors.get(a.recommendation, (0, 0, 0))
            pdf.set_text_color(*color)
            label = rec_labels.get(a.recommendation, a.recommendation)
            pdf.cell(0, 7, f"[{label}] {a.vacancy_title} — {a.company}",
                     new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(0, 0, 0)

            # Оценка и вывод
            pdf.set_font(font_name, "", 9)
            pdf.cell(0, 5, f"Score: {a.relevance_score}/100 | {a.match_level} | hh.ru/vacancy/{a.vacancy_id}",
                     new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.multi_cell(0, 4, a.reasoning)

            # Совпадения
            if a.matching_skills:
                pdf.set_font(font_name, "B", 9)
                pdf.cell(25, 4, "Совпадает:")
                pdf.set_font(font_name, "", 9)
                pdf.cell(0, 4, ", ".join(a.matching_skills[:4]),
                         new_x=XPos.LMARGIN, new_y=YPos.NEXT)

            pdf.ln(3)
            pdf.set_draw_color(200, 200, 200)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(3)

        path = config.OUTPUT_DIR / filename
        pdf.output(str(path))
        print(f"[PDF] Отчёт сохранён: {path}")
        return path


# ─── Тест ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from modules.analyzer import VacancyAnalysis

    exporter = Exporter()

    # Тестовые данные адаптированного резюме
    test_resume = {
        "vacancy_title": "Prompt Engineer",
        "company": "TechCorp",
        "adapted_summary": "Junior Prompt Engineer с практическим опытом проектирования LLM-пайплайнов. "
                           "Создал vacancy-prompt-system — 5-этапный пайплайн с anti-hallucination техниками. "
                           "Строю AI-агентов на Python + OpenAI API.",
        "top_skills": [
            "Prompt Engineering (few-shot, chain-of-thought)",
            "OpenAI API / GPT-4o",
            "Python 3.x — requests, Pydantic, BeautifulSoup",
            "Anti-hallucination техники",
            "JSON Schema / структурированный вывод",
            "Git / GitHub",
        ],
        "featured_projects": [
            {
                "name": "Vacancy Prompt System",
                "description": "5-этапный LLM-пайплайн для обработки вакансий. GPT-4o, JSON-first, anti-hallucination.",
                "highlights": ["Детерминированная температура (0.0) для извлечения", "Fallback-логика и самопроверка"],
            },
            {
                "name": "AI Job Hunter Agent",
                "description": "Автономный агент поиска вакансий на Python + OpenAI API.",
                "highlights": ["Парсинг hh.ru", "Анализ через LLM", "CLI-интерфейс"],
            },
        ],
        "additional_skills": ["Three.js (базовый)", "HTML/CSS/JS", "Netlify"],
        "personal": {
            "name": "Слава",
            "telegram": "@ysiSevera",
            "email_primary": "slavarax@gmail.com",
        },
        "education": {
            "formal": "Незаконченное высшее",
            "self_education": ["Prompt Engineering — практика + документация", "Python — проекты"],
        },
        "generated_at": datetime.now().isoformat(),
    }

    # Тест Markdown
    md_path = exporter.export_resume_md(test_resume, "test_resume.md")
    print(f"Markdown: {md_path}")

    # Тест PDF
    pdf_path = exporter.export_resume_pdf(test_resume, "test_resume.pdf")
    if pdf_path:
        print(f"PDF: {pdf_path}")
    else:
        print("PDF: пропущено (установи fpdf2)")
