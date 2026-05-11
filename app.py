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
from modules.evaluator import (
    load_feedback, save_feedback, record_outcome,
    compute_metrics, OUTCOME_LABELS,
)


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
/* ── Общий минималистичный сброс ── */
section[data-testid="stSidebar"] { background: #16161e !important; }
.stApp { background: #1a1a2e; }

/* ── Карточка вакансии ── */
.vacancy-card {
    background: #1e1e2e;
    border: 1px solid #313244;
    border-radius: 10px;
    padding: 16px 20px;
    margin-bottom: 10px;
    transition: border-color .2s;
}
.vacancy-card:hover { border-color: #89b4fa; }

/* ── Статус-бейдж «проанализирована» ── */
.analyzed-tag {
    display: inline-block;
    background: #a6e3a1;
    color: #1e1e2e;
    font-size: 11px;
    font-weight: 700;
    padding: 2px 7px;
    border-radius: 4px;
    margin-left: 6px;
    vertical-align: middle;
}

/* ── Score-цвета ── */
.score-high { color: #a6e3a1; font-weight: bold; }
.score-mid  { color: #f9e2af; font-weight: bold; }
.score-low  { color: #f38ba8; font-weight: bold; }

/* ── Recommendation badges ── */
.badge-apply { background:#a6e3a1; color:#1e1e2e; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:bold; }
.badge-maybe { background:#f9e2af; color:#1e1e2e; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:bold; }
.badge-skip  { background:#f38ba8; color:#1e1e2e; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:bold; }

/* ── Подсказка-переход ── */
.step-hint {
    background: #313244;
    border-left: 3px solid #89b4fa;
    border-radius: 6px;
    padding: 10px 16px;
    margin-top: 14px;
    font-size: 14px;
    color: #cdd6f4;
}
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


def load_seen_ids() -> set:
    """Загружает ID вакансий, которые уже показывались в прошлых сессиях."""
    path = config.OUTPUT_DIR / "seen_ids.json"
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def save_seen_ids(ids: set) -> None:
    """Сохраняет ID показанных вакансий."""
    config.OUTPUT_DIR.mkdir(exist_ok=True)
    with open(config.OUTPUT_DIR / "seen_ids.json", "w", encoding="utf-8") as f:
        json.dump(list(ids), f)


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
        ["🔍 Поиск", "📊 Анализ", "📝 Резюме и письма", "📄 Отчёт", "📈 Оценка агента"],
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
            placeholder="Оставь пустым для поиска по всем запросам выбранной профессии",
        )
    with col2:
        pages = st.selectbox("Страниц", [1, 2, 3], index=1)

    col_prof, col_salary, col_habr = st.columns([2, 2, 1])
    with col_prof:
        profession = st.selectbox(
            "Профессия",
            list(config.PROFESSION_PRESETS.keys()),
            index=list(config.PROFESSION_PRESETS.keys()).index(config.ACTIVE_PROFESSION),
        )
    with col_salary:
        salary_min = st.number_input(
            "Мин. зарплата (RUB, 0 = не фильтровать)",
            min_value=0,
            max_value=1_000_000,
            step=10_000,
            value=0,
        )
    with col_habr:
        include_habr = st.checkbox("Habr Career", value=True)

    col_btn, col_seen, col_info = st.columns([1, 1, 2])
    with col_btn:
        search_clicked = st.button("🔍 Найти вакансии", type="primary", use_container_width=True)
    with col_seen:
        hide_seen = st.checkbox("Скрыть виденные", value=True, help="Скрыть вакансии из прошлых поисков")
    with col_info:
        st.caption(f"Запросов: {len(config.PROFESSION_PRESETS[profession])} · Поиск ~30–60 сек")

    if search_clicked:
        searcher = get_searcher()
        # Применяем выбранный пресет профессии
        queries_to_use = config.PROFESSION_PRESETS[profession]

        with st.spinner("Ищу вакансии..."):
            if query.strip():
                vacancies = searcher.search_hh(query.strip(), pages=pages)
                if include_habr:
                    habr = searcher.search_habr(query.strip(), pages=pages)
                    seen_ids = {v.id for v in vacancies}
                    vacancies += [v for v in habr if v.id not in seen_ids]
            else:
                all_vacs: dict[str, object] = {}
                for q in queries_to_use:
                    for v in searcher.search_hh(q, pages=pages):
                        if v.id not in all_vacs:
                            all_vacs[v.id] = v
                if include_habr:
                    for q in queries_to_use:
                        for v in searcher.search_habr(q, pages=pages):
                            if v.id not in all_vacs:
                                all_vacs[v.id] = v
                vacancies = list(all_vacs.values())

        # Фильтр по зарплате
        if salary_min > 0:
            before = len(vacancies)
            vacancies = [
                v for v in vacancies
                if (v.salary_from and v.salary_from >= salary_min)
                or (v.salary_to   and v.salary_to   >= salary_min)
            ]
            filtered_out = before - len(vacancies)
            if filtered_out:
                st.info(f"Отфильтровано по зарплате: {filtered_out} вакансий")

        # Дедупликация между сессиями
        seen_ids = load_seen_ids()
        if hide_seen and seen_ids:
            before = len(vacancies)
            vacancies = [v for v in vacancies if v.id not in seen_ids]
            hidden = before - len(vacancies)
            if hidden:
                st.info(f"Скрыто виденных ранее: {hidden} вакансий")

        # Запоминаем все показанные ID
        new_ids = seen_ids | {v.id for v in vacancies}
        save_seen_ids(new_ids)

        st.session_state.vacancies = vacancies
        st.session_state.search_done = True
        st.session_state.analyses = []
        st.session_state.analyze_done = False

        if vacancies:
            hh_cnt    = sum(1 for v in vacancies if v.source == "hh.ru")
            habr_cnt  = sum(1 for v in vacancies if v.source == "habr.career")
            st.success(f"Найдено: **{len(vacancies)}** вакансий (hh.ru: {hh_cnt}, Habr: {habr_cnt})")
        else:
            st.warning("Вакансии не найдены. Попробуй другой запрос.")

    # Список вакансий
    if st.session_state.vacancies:
        vacancies = st.session_state.vacancies
        st.subheader(f"Найденные вакансии ({len(vacancies)})")

        # IDs уже проанализированных вакансий для статус-бейджа
        analyzed_ids = {a.vacancy_id for a in st.session_state.analyses}

        for i, v in enumerate(vacancies):
            source_badge = "🟠 Habr" if v.source == "habr.career" else "🟢 hh.ru"
            analyzed_tag = '<span class="analyzed-tag">✔ проанализирована</span>' if v.id in analyzed_ids else ""
            label = f"**{i+1}. {v.title}** — {v.company}  {source_badge}"
            with st.expander(label):
                if analyzed_tag:
                    st.markdown(analyzed_tag, unsafe_allow_html=True)
                col1, col2, col3 = st.columns(3)
                col1.metric("Компания", v.company)
                col2.metric("Зарплата", v.salary_str())
                col3.metric("Формат", "Удалённо" if v.remote else v.location)
                st.link_button("Открыть вакансию", v.url)

        # Подсказка-переход к анализу
        st.markdown(
            '<div class="step-hint">👉 Вакансии найдены — перейди на вкладку <b>📊 Анализ</b>, '
            'чтобы оценить их через LLM.</div>',
            unsafe_allow_html=True,
        )


# ─── Страница: Анализ ─────────────────────────────────────────────────────────

elif page == "📊 Анализ":
    st.title("📊 Анализ вакансий")

    if not st.session_state.vacancies:
        st.info("Сначала найди вакансии на вкладке **🔍 Поиск**")
    else:
        vacancies_all = st.session_state.vacancies
        n_total = len(vacancies_all)

        # ── Режим выбора: слайдер или чекбоксы ──
        mode = st.radio(
            "Способ выбора вакансий",
            ["Слайдер (первые N)", "Вручную (чекбоксы)"],
            horizontal=True,
        )

        if mode == "Слайдер (первые N)":
            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                limit = st.slider(
                    "Сколько вакансий анализировать",
                    min_value=1,
                    max_value=n_total,
                    value=min(15, n_total),
                )
            with col2:
                st.metric("Доступно вакансий", n_total)
            with col3:
                est = limit * 5
                st.metric("Примерное время", f"~{est} сек")
            vacancies_to_analyze = vacancies_all[:limit]
        else:
            st.markdown(f"**Выбери вакансии для анализа** (доступно: {n_total})")
            selected_ids = []
            for i, v in enumerate(vacancies_all):
                label = f"{i+1}. {v.title} — {v.company}"
                if st.checkbox(label, key=f"chk_{v.id}"):
                    selected_ids.append(v.id)
            vacancies_to_analyze = [v for v in vacancies_all if v.id in selected_ids]
            limit = len(vacancies_to_analyze)
            if limit:
                st.caption(f"Выбрано: {limit} · ~{limit * 5} сек")
            else:
                st.warning("Выбери хотя бы одну вакансию")

        analyze_clicked = st.button(
            "🧠 Анализировать через LLM",
            type="primary",
            disabled=(limit == 0),
        )

        if analyze_clicked:
            searcher = get_searcher()
            analyzer = get_analyzer()
            # vacancies_to_analyze уже определён выше (слайдер или чекбоксы)

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
                st.markdown(
                    '<div class="step-hint">👉 Анализ готов — перейди на вкладку '
                    '<b>📝 Резюме и письма</b> или <b>📄 Отчёт</b>.</div>',
                    unsafe_allow_html=True,
                )
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
        st.info("Сначала проанализируй вакансии на вкладке **📊 Анализ**")
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
        st.info("Сначала проанализируй вакансии на вкладке **📊 Анализ**")
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


# ─── Страница: Оценка агента ─────────────────────────────────────────────────

elif page == "📈 Оценка агента":
    st.title("📈 Оценка качества рекомендаций")
    st.caption("Отмечай реальные исходы — агент учится, ты видишь его точность")

    feedback = load_feedback()
    metrics = compute_metrics(feedback)

    # Метрики
    if metrics:
        st.subheader("Метрики")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Оценено вакансий", metrics["total_recorded"])
        c2.metric(
            "Precision APPLY",
            f"{metrics['precision_apply']}%" if metrics["precision_apply"] is not None else "—",
            help="Доля APPLY-вакансий, по которым реально откликнулся",
        )
        c3.metric(
            "Invite Rate",
            f"{metrics['invite_rate']}%" if metrics["invite_rate"] is not None else "—",
            help="Доля откликов, по которым пригласили",
        )
        c4.metric(
            "Accuracy",
            f"{metrics['accuracy']}%" if metrics["accuracy"] is not None else "—",
            help="Общая точность решений агента",
        )
        st.divider()

    # Форма записи исхода
    if st.session_state.analyses:
        st.subheader("Записать исход")
        analyses = st.session_state.analyses
        options = [f"{i+1}. {a.vacancy_title} — {a.company} [{a.recommendation}]"
                   for i, a in enumerate(analyses)]
        selected = st.selectbox("Вакансия", options)
        idx = int(selected.split(".")[0]) - 1
        a = analyses[idx]

        already = feedback.get(a.vacancy_id, {})
        current_outcome = already.get("outcome", None)
        outcome_options = list(OUTCOME_LABELS.keys())
        outcome_idx = outcome_options.index(current_outcome) if current_outcome in outcome_options else 0

        outcome = st.radio(
            "Что произошло?",
            outcome_options,
            format_func=lambda x: OUTCOME_LABELS[x],
            index=outcome_idx,
            horizontal=True,
        )

        if st.button("💾 Сохранить", type="primary"):
            record_outcome(
                vacancy_id=a.vacancy_id,
                vacancy_title=a.vacancy_title,
                company=a.company,
                agent_recommendation=a.recommendation,
                relevance_score=a.relevance_score,
                outcome=outcome,
            )
            st.success("Исход записан!")
            st.rerun()
    else:
        st.info("Сначала проанализируй вакансии на вкладке **Анализ**")

    # История фидбэка
    if feedback:
        st.divider()
        st.subheader(f"История ({len(feedback)} записей)")
        for vid, entry in sorted(
            feedback.items(),
            key=lambda x: x[1].get("recorded_at", ""),
            reverse=True,
        ):
            outcome_label = OUTCOME_LABELS.get(entry["outcome"], entry["outcome"])
            rec_label = rec_badge(entry["agent_recommendation"])
            st.markdown(
                f"**{entry['vacancy_title']}** — {entry['company']} &nbsp;"
                f"score: `{entry['relevance_score']}` &nbsp; агент: {rec_label} &nbsp; исход: **{outcome_label}**",
                unsafe_allow_html=True,
            )
