"""
app.py — Streamlit веб-интерфейс для AI Job Hunter Agent
Запуск: streamlit run app.py
"""

import sys
import json
import time
import csv as csv_module
import io
from datetime import datetime
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
from modules.interview_prep import InterviewPrep
from modules.company_analyzer import CompanyAnalyzer


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
        "adapted_resumes": {},      # vacancy_id -> dict
        "cover_letters": {},        # vacancy_id -> str
        "interview_questions": {},  # vacancy_id -> dict
        "company_info": {},         # vacancy_id -> dict
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

@st.cache_resource
def get_interview_prep():
    return InterviewPrep()

@st.cache_resource
def get_company_analyzer():
    return CompanyAnalyzer()


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
    """Загружает последнюю сохранённую сессию из output/session.json."""
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


def list_sessions() -> list[dict]:
    """
    Возвращает список сохранённых сессий из output/sessions/.
    Каждая запись: {"filename": ..., "date": ..., "count": ...}
    """
    sessions_dir = config.OUTPUT_DIR / "sessions"
    if not sessions_dir.exists():
        return []
    result = []
    for path in sorted(sessions_dir.glob("session_*.json"), reverse=True):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            result.append({
                "filename": path.name,
                "path": str(path),
                "date": data.get("saved_at", path.stem.replace("session_", "")),
                "count": len(data.get("analyses", [])),
            })
        except Exception:
            pass
    return result


def save_session_history(analyses: list) -> None:
    """
    Сохраняет текущую сессию в output/sessions/session_YYYYMMDD_HHMMSS.json
    и обновляет output/session.json (последняя сессия для быстрой загрузки).
    """
    config.OUTPUT_DIR.mkdir(exist_ok=True)
    now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    data = {
        "saved_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "analyses": [a.model_dump() for a in analyses],
    }
    # Последняя сессия (для автозагрузки)
    with open(config.OUTPUT_DIR / "session.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # История сессий
    sessions_dir = config.OUTPUT_DIR / "sessions"
    sessions_dir.mkdir(exist_ok=True)
    with open(sessions_dir / f"session_{now_str}.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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
        ["🔍 Поиск", "📊 Анализ", "📝 Резюме и письма", "📄 Отчёт", "📈 Оценка агента", "✏️ Моё резюме"],
        label_visibility="collapsed",
    )

    st.divider()

    # Статус
    st.markdown("**Статус сессии**")
    st.markdown(f"Найдено вакансий: `{len(st.session_state.vacancies)}`")
    st.markdown(f"Проанализировано: `{len(st.session_state.analyses)}`")
    st.markdown(f"Адаптировано резюме: `{len(st.session_state.adapted_resumes)}`")

    # История сессий
    sessions = list_sessions()
    if sessions:
        st.divider()
        st.markdown("**История сессий**")
        options = [f"{s['date']} ({s['count']} вак.)" for s in sessions]
        chosen = st.selectbox("Загрузить сессию", options, label_visibility="collapsed")
        if st.button("📂 Загрузить", use_container_width=True):
            chosen_idx = options.index(chosen)
            chosen_path = sessions[chosen_idx]["path"]
            try:
                with open(chosen_path, encoding="utf-8") as f:
                    data = json.load(f)
                analyses = [VacancyAnalysis(**a) for a in data.get("analyses", [])]
                st.session_state.analyses = analyses
                st.session_state.analyze_done = True
                st.success(f"Загружено: {len(analyses)} вакансий")
                st.rerun()
            except Exception as e:
                st.error(f"Ошибка загрузки: {e}")

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
        queries_to_use = config.PROFESSION_PRESETS[profession]

        # Прогресс-бар при поиске
        progress = st.progress(0, text="Начинаю поиск...")
        all_vacs: dict[str, object] = {}

        if query.strip():
            query_list = [query.strip()]
            sources = ["hh"] + (["habr"] if include_habr else [])
        else:
            query_list = queries_to_use
            sources = ["hh"] + (["habr"] if include_habr else [])

        total_steps = len(query_list) * len(sources)
        step = 0

        for src in sources:
            for q in query_list:
                step += 1
                src_label = "hh.ru" if src == "hh" else "Habr Career"
                progress.progress(step / total_steps, text=f"[{step}/{total_steps}] {src_label}: «{q}»")
                if src == "hh":
                    results = searcher.search_hh(q, pages=pages)
                else:
                    results = searcher.search_habr(q, pages=pages)
                for v in results:
                    if v.id not in all_vacs:
                        all_vacs[v.id] = v

        progress.empty()
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
            hh_cnt   = sum(1 for v in vacancies if v.source == "hh.ru")
            habr_cnt = sum(1 for v in vacancies if v.source == "habr.career")
            st.success(f"Найдено: **{len(vacancies)}** вакансий (hh.ru: {hh_cnt}, Habr: {habr_cnt})")
        else:
            st.warning("Вакансии не найдены. Попробуй другой запрос.")

    # Список вакансий
    if st.session_state.vacancies:
        vacancies = st.session_state.vacancies

        # ── Сортировка и фильтрация ──
        col_sort, col_remote, col_src = st.columns([2, 1, 1])
        with col_sort:
            sort_by = st.selectbox(
                "Сортировка",
                ["По умолчанию", "Зарплата ↓", "Зарплата ↑", "Название А-Я"],
                label_visibility="collapsed",
            )
        with col_remote:
            only_remote = st.checkbox("Только удалённые", value=False)
        with col_src:
            src_filter = st.selectbox(
                "Источник",
                ["Все", "hh.ru", "Habr Career"],
                label_visibility="collapsed",
            )

        # Применяем фильтры
        filtered_vacs = vacancies
        if only_remote:
            filtered_vacs = [v for v in filtered_vacs if v.remote]
        if src_filter == "hh.ru":
            filtered_vacs = [v for v in filtered_vacs if v.source == "hh.ru"]
        elif src_filter == "Habr Career":
            filtered_vacs = [v for v in filtered_vacs if v.source == "habr.career"]

        # Применяем сортировку
        if sort_by == "Зарплата ↓":
            filtered_vacs = sorted(filtered_vacs, key=lambda v: v.salary_from or 0, reverse=True)
        elif sort_by == "Зарплата ↑":
            filtered_vacs = sorted(filtered_vacs, key=lambda v: v.salary_from or 0)
        elif sort_by == "Название А-Я":
            filtered_vacs = sorted(filtered_vacs, key=lambda v: v.title.lower())

        st.subheader(f"Найденные вакансии ({len(filtered_vacs)} из {len(vacancies)})")

        # ── Экспорт в CSV ──
        if filtered_vacs:
            buf = io.StringIO()
            writer = csv_module.writer(buf)
            writer.writerow(["Название", "Компания", "Зарплата", "Удалённо", "Источник", "Ссылка"])
            for v in filtered_vacs:
                writer.writerow([v.title, v.company, v.salary_str(), "Да" if v.remote else "Нет", v.source, v.url])
            st.download_button(
                "📥 Скачать CSV",
                buf.getvalue().encode("utf-8-sig"),
                file_name="vacancies.csv",
                mime="text/csv",
            )

        # IDs уже проанализированных вакансий для статус-бейджа
        analyzed_ids = {a.vacancy_id for a in st.session_state.analyses}

        for i, v in enumerate(filtered_vacs):
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

            # Сохраняем сессию (последняя + история)
            try:
                save_session_history(results)
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

                # ── Анализ компании ────────────────────────────────────────
                company_key = a.vacancy_id
                existing_info = st.session_state.company_info.get(company_key)

                if st.button(
                    "🏢 Анализ компании",
                    key=f"company_{company_key}",
                    use_container_width=True,
                ):
                    analyzer_co = get_company_analyzer()
                    with st.spinner(f"Анализирую {a.company}..."):
                        info = analyzer_co.analyze(a.company, vacancy_title=a.vacancy_title)
                    if info:
                        st.session_state.company_info[company_key] = info
                        existing_info = info
                        st.success("Готово!")
                    else:
                        st.warning("Не удалось получить информацию о компании")

                if existing_info:
                    with st.container(border=True):
                        st.markdown(f"**🏢 {existing_info.get('company_name', a.company)}**")
                        if existing_info.get("summary"):
                            st.markdown(existing_info["summary"])
                        col_c1, col_c2 = st.columns(2)
                        with col_c1:
                            if existing_info.get("what_they_do"):
                                st.markdown(f"**Деятельность:** {existing_info['what_they_do']}")
                            if existing_info.get("tech_hints"):
                                st.markdown(f"**Технологии:** {existing_info['tech_hints']}")
                        with col_c2:
                            if existing_info.get("culture_hints"):
                                st.markdown(f"**Культура:** {existing_info['culture_hints']}")
                            if existing_info.get("red_flags"):
                                st.markdown(f"**⚠️ Red flags:** {existing_info['red_flags']}")
                        if existing_info.get("employer_url"):
                            st.link_button(
                                "Страница работодателя на hh",
                                existing_info["employer_url"],
                            )


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

        tab_resume, tab_cover, tab_interview = st.tabs(
            ["📋 Адаптация резюме", "✉️ Сопроводительное письмо", "🎤 Подготовка к собеседованию"]
        )

        # ── Адаптация резюме ──
        with tab_resume:
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
        with tab_cover:
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

        # ── Подготовка к собеседованию ──
        with tab_interview:
            st.caption("Персональные вопросы под эту вакансию и твоё резюме")
            interview_clicked = st.button(
                "🎤 Подготовить вопросы", type="primary", use_container_width=True
            )

            if interview_clicked:
                prep = get_interview_prep()
                with st.spinner("Генерирую вопросы..."):
                    questions = prep.generate(analysis)
                if questions:
                    st.session_state.interview_questions[analysis.vacancy_id] = questions
                    st.success("Готово!")
                else:
                    st.error("Не удалось сгенерировать вопросы. Проверь соединение с LLM.")

            questions = st.session_state.interview_questions.get(analysis.vacancy_id)
            if questions:
                st.subheader("❓ Вопросы которые тебе зададут")
                for i, q in enumerate(questions.get("questions_for_me", []), 1):
                    with st.expander(f"{i}. {q.get('question', '')}"):
                        st.markdown(f"**Как отвечать:** {q.get('hint', '')}")

                st.divider()
                st.subheader("🙋 Вопросы которые ты можешь задать")
                for q in questions.get("questions_for_them", []):
                    st.markdown(f"- {q}")

                # Экспорт вопросов как текст
                export_text = "ВОПРОСЫ К СОБЕСЕДОВАНИЮ\n"
                export_text += f"Вакансия: {analysis.vacancy_title} — {analysis.company}\n\n"
                export_text += "ВОПРОСЫ КО МНЕ:\n"
                for i, q in enumerate(questions.get("questions_for_me", []), 1):
                    export_text += f"\n{i}. {q.get('question', '')}\n"
                    export_text += f"   → {q.get('hint', '')}\n"
                export_text += "\nВОПРОСЫ К КОМПАНИИ:\n"
                for q in questions.get("questions_for_them", []):
                    export_text += f"- {q}\n"

                st.download_button(
                    "💾 Скачать вопросы (.txt)",
                    export_text,
                    file_name=f"interview_{analysis.vacancy_id}.txt",
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

        # ── Графики ──────────────────────────────────────────────────────────
        st.divider()
        st.subheader("Графики")

        col_left, col_right = st.columns(2)

        with col_left:
            # Распределение исходов (bar chart)
            outcome_counts: dict[str, int] = {}
            for entry in feedback.values():
                label = OUTCOME_LABELS.get(entry["outcome"], entry["outcome"])
                outcome_counts[label] = outcome_counts.get(label, 0) + 1
            if outcome_counts:
                st.caption("Распределение исходов")
                st.bar_chart(outcome_counts)

        with col_right:
            # Ключевые метрики как прогресс-бары
            st.caption("Ключевые метрики (%)")
            for label, key in [
                ("Precision APPLY", "precision_apply"),
                ("Invite Rate", "invite_rate"),
                ("Accuracy", "accuracy"),
            ]:
                val = metrics.get(key)
                if val is not None:
                    st.markdown(f"**{label}:** {val}%")
                    st.progress(int(val) / 100)
                else:
                    st.markdown(f"**{label}:** — *(нет данных)*")

        # Распределение рекомендаций агента vs реальных исходов
        if len(feedback) >= 3:
            st.divider()
            st.caption("Рекомендации агента vs реальные исходы")
            rec_outcome: dict[str, dict[str, int]] = {}
            for entry in feedback.values():
                rec = entry["agent_recommendation"]
                out = OUTCOME_LABELS.get(entry["outcome"], entry["outcome"])
                if rec not in rec_outcome:
                    rec_outcome[rec] = {}
                rec_outcome[rec][out] = rec_outcome[rec].get(out, 0) + 1
            # Строим плоский словарь для bar_chart
            chart_data: dict[str, int] = {}
            for rec, outcomes in rec_outcome.items():
                for out, cnt in outcomes.items():
                    chart_data[f"{rec} → {out}"] = cnt
            st.bar_chart(chart_data)

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


# ─── Страница: Редактор резюме ────────────────────────────────────────────────

RESUME_PATH = Path(__file__).parent / "memory" / "base_resume.json"
RESUME_EXAMPLE_PATH = Path(__file__).parent / "memory" / "base_resume.example.json"


def _load_resume() -> dict:
    """Загружает base_resume.json; если нет — берёт example как заготовку."""
    path = RESUME_PATH if RESUME_PATH.exists() else RESUME_EXAMPLE_PATH
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_resume(data: dict) -> None:
    """Сохраняет резюме в memory/base_resume.json."""
    RESUME_PATH.parent.mkdir(exist_ok=True)
    with open(RESUME_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _list_to_text(lst: list) -> str:
    """Список строк → многострочный текст (для text_area)."""
    return "\n".join(str(x) for x in lst)


def _text_to_list(text: str) -> list:
    """Многострочный текст → список строк (убирает пустые строки)."""
    return [line.strip() for line in text.splitlines() if line.strip()]


if page == "✏️ Моё резюме":
    st.title("✏️ Редактор резюме")
    st.caption("Изменения сохраняются в `memory/base_resume.json` и сразу используются агентом.")

    try:
        resume = _load_resume()
    except Exception as e:
        st.error(f"Не удалось загрузить резюме: {e}")
        st.stop()

    # Флаг — было ли сохранение
    saved = False

    with st.form("resume_editor", border=False):

        # ── Личные данные ──────────────────────────────────────────────────────
        st.subheader("👤 Личные данные")
        personal = resume.get("personal", {})
        col1, col2 = st.columns(2)
        with col1:
            p_name = st.text_input("Имя", value=personal.get("name", ""))
            p_email = st.text_input("Email (основной)", value=personal.get("email_primary", ""))
            p_email2 = st.text_input("Email (дополнительный)", value=personal.get("email_secondary", ""))
        with col2:
            p_telegram = st.text_input("Telegram", value=personal.get("telegram", ""))
            p_location = st.text_input("Город / страна", value=personal.get("location", ""))
            p_formats_raw = personal.get("work_format", [])
            p_formats = st.multiselect(
                "Формат работы",
                options=["remote", "hybrid", "office"],
                default=[f for f in p_formats_raw if f in ["remote", "hybrid", "office"]],
            )
        p_languages = st.text_area(
            "Языки (каждый с новой строки)",
            value=_list_to_text(personal.get("languages", [])),
            height=80,
        )

        st.divider()

        # ── Цель ──────────────────────────────────────────────────────────────
        st.subheader("🎯 Цель и позиционирование")
        summary = st.text_area(
            "О себе / Summary",
            value=resume.get("summary", ""),
            height=120,
        )
        target_roles = st.text_area(
            "Целевые роли (каждая с новой строки)",
            value=_list_to_text(resume.get("target_roles", [])),
            height=120,
        )

        st.divider()

        # ── Навыки ────────────────────────────────────────────────────────────
        st.subheader("🛠 Навыки")
        skills = resume.get("skills", {})
        sk_prompt = st.text_area(
            "Prompt Engineering (каждый навык с новой строки)",
            value=_list_to_text(skills.get("prompt_engineering", [])),
            height=120,
        )
        sk_ai = st.text_area(
            "AI Development (каждый навык с новой строки)",
            value=_list_to_text(skills.get("ai_development", [])),
            height=100,
        )
        sk_prog = st.text_area(
            "Программирование (каждый навык с новой строки)",
            value=_list_to_text(skills.get("programming", [])),
            height=100,
        )
        sk_tools = st.text_area(
            "Инструменты (каждый с новой строки)",
            value=_list_to_text(skills.get("tools", [])),
            height=80,
        )

        st.divider()

        # ── Проекты ───────────────────────────────────────────────────────────
        st.subheader("🚀 Проекты")
        st.caption("Редактируется в формате JSON — по одному проекту.")
        projects = resume.get("projects", [])
        projects_json = st.text_area(
            "Список проектов (JSON)",
            value=json.dumps(projects, ensure_ascii=False, indent=2),
            height=300,
        )

        st.divider()

        # ── Опыт и образование ────────────────────────────────────────────────
        st.subheader("📚 Опыт и образование")
        experience_notes = st.text_area(
            "Заметки об опыте",
            value=resume.get("experience_notes", ""),
            height=80,
        )
        education = resume.get("education", {})
        edu_formal = st.text_input("Формальное образование", value=education.get("formal", ""))
        edu_self = st.text_area(
            "Самообразование (каждый пункт с новой строки)",
            value=_list_to_text(education.get("self_education", [])),
            height=100,
        )

        st.divider()

        # ── Soft skills и ключевые слова ──────────────────────────────────────
        st.subheader("💬 Soft Skills и ключевые слова")
        soft_skills = st.text_area(
            "Soft skills (каждый с новой строки)",
            value=_list_to_text(resume.get("soft_skills", [])),
            height=100,
        )
        keywords = st.text_area(
            "Ключевые слова для матчинга (через запятую)",
            value=", ".join(resume.get("keywords_for_matching", [])),
            height=80,
        )

        st.divider()

        submitted = st.form_submit_button("💾 Сохранить резюме", type="primary", use_container_width=True)

    if submitted:
        # Валидация JSON проектов
        try:
            parsed_projects = json.loads(projects_json)
        except json.JSONDecodeError as e:
            st.error(f"Ошибка в JSON проектов: {e}")
            st.stop()

        # Разбираем ключевые слова
        kw_list = [k.strip() for k in keywords.split(",") if k.strip()]

        # Собираем итоговый словарь
        updated = {
            "meta": resume.get("meta", {}),
            "personal": {
                "name": p_name,
                "telegram": p_telegram,
                "email_primary": p_email,
                "email_secondary": p_email2,
                "location": p_location,
                "work_format": p_formats,
                "languages": _text_to_list(p_languages),
            },
            "target_roles": _text_to_list(target_roles),
            "summary": summary,
            "skills": {
                "prompt_engineering": _text_to_list(sk_prompt),
                "ai_development": _text_to_list(sk_ai),
                "programming": _text_to_list(sk_prog),
                "tools": _text_to_list(sk_tools),
            },
            "projects": parsed_projects,
            "experience_notes": experience_notes,
            "education": {
                "formal": edu_formal,
                "self_education": _text_to_list(edu_self),
            },
            "soft_skills": _text_to_list(soft_skills),
            "keywords_for_matching": kw_list,
        }

        # Обновляем дату
        updated["meta"]["last_updated"] = datetime.now().strftime("%Y-%m-%d")

        try:
            _save_resume(updated)
            st.success("✅ Резюме сохранено в `memory/base_resume.json`")
        except Exception as e:
            st.error(f"Ошибка сохранения: {e}")
