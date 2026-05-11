"""
app.py — Streamlit веб-интерфейс для AI Job Hunter Agent
Запуск: streamlit run app.py
"""

import sys
import json
import time
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

import config
from modules.searcher import JobSearcher, Vacancy
from modules.analyzer import VacancyAnalyzer, VacancyAnalysis
from modules.resume_adapter import ResumeAdapter
from modules.cover_letter import CoverLetterGenerator
from modules.exporter import Exporter


# ─── Конфигурация страницы ────────────────────────────────────────────────────

st.set_page_config(
    page_title="AI Job Hunter",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ─── Стили ────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
.vacancy-card {
    background: #1e1e2e;
    border: 1px solid #313244;
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 12px;
}
.score-high { color: #a6e3a1; font-weight: bold; }
.score-mid  { color: #f9e2af; font-weight: bold; }
.score-low  { color: #f38ba8; font-weight: bold; }
.badge-apply { background:#a6e3a1; color:#1e1e2e; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:bold; }
.badge-maybe { background:#f9e2af; color:#1e1e2e; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:bold; }
.badge-skip  { background:#f38ba8; color:#1e1e2e; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:bold; }
</style>
""", unsafe_allow_html=True)


# ─── Инициализация session_state ─────────────────────────────────────────────

def init_state():
    defaults = {
        "vacancies": [],
        "analyses": [],
        "adapted_resumes": {},   # vacancy_id -> dict
        "cover_letters": {},     # vacancy_id -> str
        "selected_idx": 0,
        "search_done": False,
        "analyze_done": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()


# ─── Кэшированные модули ─────────────────────────────────────────────────────

@st.cache_resource
def get_searcher():
    return JobSearcher()

@st.cache_resource
def get_analyzer():
    return VacancyAnalyzer()

@st.cache_resource
def get_adapter():
    return ResumeAdapter()

@st.cache_resource
def get_cover_gen():
    return CoverLetterGenerator()

@st.cache_resource
def get_exporter():
    return Exporter()


# ─── Хелперы ─────────────────────────────────────────────────────────────────

def rec_badge(rec: str) -> str:
    cls = {"APPLY": "badge-apply", "MAYBE": "badge-maybe", "SKIP": "badge-skip"}.get(rec, "")
    return f'<span class="{cls}">{rec}</span>'

def score_color(score: int) -> str:
    if score >= 65:
        return "score-high"
    elif score >= 45:
        return "score-mid"
    return "score-low"

def load_session():
    """Загружает сохранённую сессию из output/session.json."""
    path = config.OUTPUT_DIR / "session.json"
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            analyses = [VacancyAnalysis(**a) for a in data.get("analyses", [])]
            if analyses:
                st.session_state.analyses = analyses
                st.session_state.analyze_done = True
                return len(analyses)
        except Exception:
            pass
    return 0


# ─── Сайдбар ─────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🤖 AI Job Hunter")
    st.caption("Поиск AI-вакансий на hh.ru")

    st.divider()

    # Загрузка прошлой сессии
    if not st.session_state.analyze_done:
        n = load_session()
        if n:
            st.success(f"Сессия загружена: {n} вакансий")

    # Навигация
    page = st.radio(
        "Раздел",
        ["🔍 Поиск", "📊 Анализ", "📝 Резюме и письма", "📄 Отчёт"],
        label_visibility="collapsed",
    )

    st.divider()

    # Статус
    st.markdown("**Статус сессии**")
    st.markdown(f"Найдено вакансий: `{len(st.session_state.vacancies)}`")
    st.markdown(f"Проанализировано: `{len(st.session_state.analyses)}`")
    st.markdown(f"Адаптировано резюме: `{len(st.session_state.adapted_resumes)}`")

    st.divider()
    st.caption("gpt-4o-mini · hh.ru · Python")


# ─── Страница: Поиск ─────────────────────────────────────────────────────────

if page == "🔍 Поиск":
    st.title("🔍 Поиск вакансий")

    col1, col2 = st.columns([3, 1])
    with col1:
        query = st.text_input(
            "Поисковый запрос",
            placeholder="Оставь пустым для поиска по всем AI-запросам",
        )
    with col2:
        pages = st.selectbox("Страниц hh.ru", [1, 2, 3], index=1)

    col_btn, col_info = st.columns([1, 3])
    with col_btn:
        search_clicked = st.button("🔍 Найти вакансии", type="primary", use_container_width=True)
    with col_info:
        st.caption("Поиск по всем запросам занимает ~30 сек")

    if search_clicked:
        searcher = get_searcher()
        with st.spinner("Ищу вакансии на hh.ru..."):
            if query.strip():
                vacancies = searcher.search_hh(query.strip(), pages=pages)
            else:
                vacancies = searcher.search_all_queries()

        st.session_state.vacancies = vacancies
        st.session_state.search_done = True
        st.session_state.analyses = []
        st.session_state.analyze_done = False

        if vacancies:
            st.success(f"Найдено: {len(vacancies)} вакансий")
        else:
            st.warning("Вакансии не найдены. Попробуй другой запрос.")

    # Список вакансий
    if st.session_state.vacancies:
        vacancies = st.session_state.vacancies
        st.subheader(f"Найденные вакансии ({len(vacancies)})")

        for i, v in enumerate(vacancies):
            with st.expander(f"**{i+1}. {v.title}** — {v.company}"):
                col1, col2, col3 = st.columns(3)
                col1.metric("Компания", v.company)
                col2.metric("Зарплата", v.salary_str())
                col3.metric("Формат", "Удалённо" if v.remote else v.location)
                st.link_button("Открыть на hh.ru", f"https://hh.ru/vacancy/{v.id}")


# ─── Страница: Анализ ─────────────────────────────────────────────────────────

elif page == "📊 Анализ":
    st.title("📊 Анализ вакансий")

    if not st.session_state.vacancies:
        st.info("Сначала найди вакансии на вкладке **Поиск**")
    else:
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            limit = st.slider(
                "Сколько вакансий анализировать",
                min_value=5,
                max_value=min(30, len(st.session_state.vacancies)),
                value=min(15, len(st.session_state.vacancies)),
            )
        with col2:
            st.metric("Доступно вакансий", len(st.session_state.vacancies))
        with col3:
            est = limit * 5
            st.metric("Примерное время", f"~{est} сек")

        analyze_clicked = st.button("🧠 Анализировать через LLM", type="primary")

        if analyze_clicked:
            searcher = get_searcher()
            analyzer = get_analyzer()
            vacancies_to_analyze = st.session_state.vacancies[:limit]

            progress = st.progress(0, text="Загружаю описания вакансий...")

            # Загружаем описания
            for i, v in enumerate(vacancies_to_analyze):
                if not v.description:
                    v.description = searcher.get_vacancy_description(v.id)
                progress.progress((i + 1) / (limit * 2), text=f"Описание {i+1}/{limit}: {v.title[:40]}")
                time.sleep(0.3)

            # Анализируем
            results = []
            for i, v in enumerate(vacancies_to_analyze):
                progress.progress(
                    0.5 + (i + 1) / (limit * 2),
                    text=f"Анализирую {i+1}/{limit}: {v.title[:40]}"
                )
                analysis = analyzer.analyze_vacancy(v)
                if analysis and analysis.relevance_score >= config.RELEVANCE_THRESHOLD:
                    results.append(analysis)
                if i < limit - 1:
                    time.sleep(2)

            progress.empty()
            results.sort(key=lambda x: x.relevance_score, reverse=True)
            st.session_state.analyses = results
            st.session_state.analyze_done = True
            st.session_state.adapted_resumes = {}

            # Сохраняем сессию
            try:
                config.OUTPUT_DIR.mkdir(exist_ok=True)
                with open(config.OUTPUT_DIR / "session.json", "w", encoding="utf-8") as f:
                    json.dump({"analyses": [a.model_dump() for a in results]}, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

            if results:
                st.success(f"Прошли порог {config.RELEVANCE_THRESHOLD}+: **{len(results)}** вакансий")
            else:
                st.warning("Ни одна вакансия не прошла порог. Попробуй снизить RELEVANCE_THRESHOLD в .env")

    # Результаты анализа
    if st.session_state.analyses:
        analyses = st.session_state.analyses

        # Фильтры
        col1, col2 = st.columns([2, 1])
        with col1:
            filter_rec = st.selectbox("Фильтр", ["Все", "APPLY", "MAYBE", "SKIP"])
        with col2:
            st.metric("Всего проанализировано", len(analyses))

        filtered = analyses if filter_rec == "Все" else [a for a in analyses if a.recommendation == filter_rec]

        st.subheader(f"Результаты ({len(filtered)})")

        for i, a in enumerate(filtered):
            # Определяем реальный индекс в полном списке для операций
            real_idx = analyses.index(a) + 1
            badge = rec_badge(a.recommendation)
            sc_cls = score_color(a.relevance_score)

            with st.expander(f"**{real_idx}. {a.vacancy_title}** — {a.company}"):
                col1, col2, col3 = st.columns(3)
                col1.markdown(f"**Score:** <span class='{sc_cls}'>{a.relevance_score}/100</span>", unsafe_allow_html=True)
                col2.markdown(f"**Решение:** {badge}", unsafe_allow_html=True)
                col3.markdown(f"**Уровень:** `{a.match_level}`")

                st.markdown(f"**Вывод:** {a.reasoning}")

                col_left, col_right = st.columns(2)
                with col_left:
                    if a.matching_skills:
                        st.markdown("**✅ Совпадают:**")
                        for s in a.matching_skills[:5]:
                            st.markdown(f"- {s}")
                with col_right:
                    if a.missing_skills:
                        st.markdown("**❌ Не хватает:**")
                        for s in a.missing_skills[:5]:
                            st.markdown(f"- {s}")

                if a.apply_tips:
                    st.markdown("**💡 Советы при отклике:**")
                    for tip in a.apply_tips:
                        st.markdown(f"- {tip}")

                st.link_button("Открыть на hh.ru", f"https://hh.ru/vacancy/{a.vacancy_id}")


# ─── Страница: Резюме и письма ────────────────────────────────────────────────

elif page == "📝 Резюме и письма":
    st.title("📝 Резюме и сопроводительные письма")

    if not st.session_state.analyses:
        st.info("Сначала проанализируй вакансии на вкладке **Анализ**")
    else:
        analyses = st.session_state.analyses

        # Выбор вакансии
        options = [f"{i+1}. {a.vacancy_title} — {a.company} (score: {a.relevance_score})"
                   for i, a in enumerate(analyses)]
        selected = st.selectbox("Выбери вакансию", options)
        idx = int(selected.split(".")[0]) - 1
        analysis = analyses[idx]

        st.markdown(f"**Вакансия:** {analysis.vacancy_title} | **Компания:** {analysis.company}")
        st.divider()

        col1, col2 = st.columns(2)

        # ── Адаптация резюме ──
        with col1:
            st.subheader("📋 Адаптация резюме")
            adapt_clicked = st.button("⚡ Адаптировать резюме", type="primary", use_container_width=True)

            if adapt_clicked:
                adapter = get_adapter()
                with st.spinner("Адаптирую резюме..."):
                    adapted = adapter.adapt(analysis)
                    adapter.save(adapted)
                st.session_state.adapted_resumes[analysis.vacancy_id] = adapted
                st.success("Резюме адаптировано!")

            adapted = st.session_state.adapted_resumes.get(analysis.vacancy_id)
            if adapted:
                st.markdown(f"**Summary:** {adapted.get('adapted_summary', '')}")
                st.markdown(f"**Топ навыки:** {', '.join(adapted.get('top_skills', [])[:5])}")

                # Экспорт PDF
                export_clicked = st.button("📥 Скачать PDF", use_container_width=True)
                if export_clicked:
                    exporter = get_exporter()
                    with st.spinner("Генерирую PDF..."):
                        md_path = exporter.export_resume_md(adapted)
                        pdf_path = exporter.export_resume_pdf(adapted)
                    if pdf_path and Path(pdf_path).exists():
                        with open(pdf_path, "rb") as f:
                            st.download_button(
                                "💾 Сохранить PDF",
                                f,
                                file_name=Path(pdf_path).name,
                                mime="application/pdf",
                                use_container_width=True,
                            )
                    st.success(f"Markdown: `{md_path}`")

        # ── Сопроводительное письмо ──
        with col2:
            st.subheader("✉️ Сопроводительное письмо")
            tone = st.selectbox("Тон письма", ["professional", "friendly", "concise"])
            cover_clicked = st.button("✍️ Сгенерировать письмо", type="primary", use_container_width=True)

            if cover_clicked:
                cover_gen = get_cover_gen()
                adapted = st.session_state.adapted_resumes.get(analysis.vacancy_id)
                if not adapted:
                    st.warning("Рекомендуется сначала адаптировать резюме — письмо будет лучше")
                with st.spinner("Генерирую письмо..."):
                    letter = cover_gen.generate(analysis, adapted_resume=adapted, tone=tone)
                    cover_gen.save(letter, analysis)
                st.session_state.cover_letters[analysis.vacancy_id] = letter
                st.success("Письмо готово!")

            letter = st.session_state.cover_letters.get(analysis.vacancy_id)
            if letter:
                st.text_area("Письмо", letter, height=350)
                st.download_button(
                    "💾 Скачать письмо (.txt)",
                    letter,
                    file_name=f"cover_{analysis.vacancy_id}.txt",
                    mime="text/plain",
                    use_container_width=True,
                )


# ─── Страница: Отчёт ─────────────────────────────────────────────────────────

elif page == "📄 Отчёт":
    st.title("📄 Отчёт по вакансиям")

    if not st.session_state.analyses:
        st.info("Сначала проанализируй вакансии на вкладке **Анализ**")
    else:
        analyses = st.session_state.analyses

        # Сводная статистика
        apply_count = sum(1 for a in analyses if a.recommendation == "APPLY")
        maybe_count = sum(1 for a in analyses if a.recommendation == "MAYBE")
        skip_count  = sum(1 for a in analyses if a.recommendation == "SKIP")
        avg_score   = sum(a.relevance_score for a in analyses) // len(analyses)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("✅ APPLY", apply_count)
        col2.metric("🤔 MAYBE", maybe_count)
        col3.metric("❌ SKIP", skip_count)
        col4.metric("Средний score", f"{avg_score}/100")

        st.divider()

        # Генерация и скачивание отчёта
        if st.button("📄 Сгенерировать Markdown-отчёт", type="primary"):
            exporter = get_exporter()
            path = exporter.export_analysis_md(analyses)
            st.success(f"Отчёт сохранён: `{path}`")
            with open(path, encoding="utf-8") as f:
                content = f.read()
            st.download_button(
                "💾 Скачать отчёт (.md)",
                content,
                file_name=Path(path).name,
                mime="text/markdown",
                use_container_width=True,
            )

        st.divider()

        # Топ вакансий
        st.subheader("Топ вакансий по релевантности")
        for i, a in enumerate(analyses[:10], 1):
            badge = rec_badge(a.recommendation)
            sc_cls = score_color(a.relevance_score)
            st.markdown(
                f"{i}. **{a.vacancy_title}** — {a.company} &nbsp;"
                f"<span class='{sc_cls}'>{a.relevance_score}/100</span> &nbsp; {badge}",
                unsafe_allow_html=True,
            )
