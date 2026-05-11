"""
agent.py — главный файл AI Job Hunter Agent
Точка входа. CLI-интерфейс для управления агентом.

Команды:
  /search   — найти вакансии на hh.ru
  /analyze  — проанализировать вакансии через LLM (OpenRouter)
  /adapt    — адаптировать резюме под вакансию
  /cover    — сгенерировать сопроводительное письмо
  /resume   — экспортировать резюме (MD / PDF)
  /help     — показать справку
  /quit     — выход
"""

import sys
import json
import webbrowser
from pathlib import Path

# Добавляем корень проекта в путь (для импорта config и modules)
sys.path.insert(0, str(Path(__file__).parent))

import config
from modules.searcher import JobSearcher, Vacancy
from modules.analyzer import VacancyAnalyzer, VacancyAnalysis
from modules.resume_adapter import ResumeAdapter
from modules.cover_letter import CoverLetterGenerator
from modules.exporter import Exporter


# ─── Цвета для терминала (ANSI) ───────────────────────────────────────────────
class C:
    """Цвета для красивого вывода в терминал."""
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    CYAN   = "\033[96m"
    GRAY   = "\033[90m"


def print_header():
    """Выводит баннер при запуске агента."""
    print(f"""
{C.CYAN}{C.BOLD}
╔══════════════════════════════════════════════╗
║        AI JOB HUNTER AGENT  v1.0            ║
║   Python + OpenRouter LLM | by @ysiSevera   ║
╚══════════════════════════════════════════════╝
{C.RESET}""")


def print_help():
    """Выводит справку по командам."""
    print(f"""
{C.BOLD}Доступные команды:{C.RESET}

  {C.GREEN}/search{C.RESET}           Найти вакансии на hh.ru по всем запросам
  {C.GREEN}/search <запрос>{C.RESET}  Найти по конкретному запросу (пример: /search AI trainer)
  {C.GREEN}/analyze [N]{C.RESET}      Проанализировать N вакансий через LLM (по умолчанию 10)
  {C.GREEN}/adapt <N>{C.RESET}        Адаптировать резюме под вакансию №N из списка
  {C.GREEN}/cover <N> [тон]{C.RESET}  Сгенерировать письмо (тон: professional/friendly/concise)
  {C.GREEN}/resume <N>{C.RESET}       Экспортировать резюме в MD и PDF для вакансии №N
  {C.GREEN}/open <N>{C.RESET}         Открыть вакансию №N в браузере
  {C.GREEN}/list{C.RESET}             Показать список вакансий
  {C.GREEN}/list apply|maybe|skip{C.RESET} Фильтр по рекомендации
  {C.GREEN}/list top5{C.RESET}        Топ 5 по релевантности
  {C.GREEN}/list all{C.RESET}         Все найденные вакансии
  {C.GREEN}/list vacancies{C.RESET}   Сырые вакансии (даже после /analyze)
  {C.GREEN}/report{C.RESET}           Создать Markdown-отчёт по результатам анализа
  {C.GREEN}/run [запрос]{C.RESET}     Полный цикл: search → analyze → report
  {C.GREEN}/help{C.RESET}             Показать эту справку
  {C.GREEN}/quit{C.RESET}             Выйти из агента

{C.GRAY}Рабочий процесс:
  Быстрый:  /run prompt engineer  — полный цикл одной командой
  Ручной:
  1. /search        — найти вакансии
  2. /analyze 15    — проанализировать (можно указать кол-во)
  3. /list apply    — посмотреть лучшие
  4. /open 1        — открыть в браузере
  5. /adapt 1       — адаптировать резюме под лучшую вакансию
  6. /cover 1       — написать письмо
  7. /resume 1      — экспортировать в PDF{C.RESET}
""")


class Agent:
    """
    Главный класс агента. Хранит состояние сессии:
    найденные вакансии, результаты анализа, адаптированные резюме.
    """

    def __init__(self):
        # Состояние сессии (в памяти, не сохраняется между запусками)
        self.vacancies: list[Vacancy] = []
        self.analyses: list[VacancyAnalysis] = []
        self.adapted_resumes: dict[str, dict] = {}  # vacancy_id -> резюме

        # Ленивая инициализация модулей (создаём только когда нужны)
        self._searcher: JobSearcher | None = None
        self._analyzer: VacancyAnalyzer | None = None
        self._adapter: ResumeAdapter | None = None
        self._cover_gen: CoverLetterGenerator | None = None
        self._exporter: Exporter | None = None

    # ── Свойства с ленивой инициализацией ─────────────────────────────────────

    @property
    def searcher(self) -> JobSearcher:
        if not self._searcher:
            self._searcher = JobSearcher()
        return self._searcher

    @property
    def analyzer(self) -> VacancyAnalyzer:
        if not self._analyzer:
            if not config.validate_config():
                raise RuntimeError("OPENROUTER_API_KEY не задан в .env файле")
            self._analyzer = VacancyAnalyzer()
        return self._analyzer

    @property
    def adapter(self) -> ResumeAdapter:
        if not self._adapter:
            self._adapter = ResumeAdapter()
        return self._adapter

    @property
    def cover_gen(self) -> CoverLetterGenerator:
        if not self._cover_gen:
            self._cover_gen = CoverLetterGenerator()
        return self._cover_gen

    @property
    def exporter(self) -> Exporter:
        if not self._exporter:
            self._exporter = Exporter()
        return self._exporter

    # ── Команды ───────────────────────────────────────────────────────────────

    def cmd_search(self, args: list[str]):
        """
        /search [запрос]
        Ищет вакансии. Без аргументов — по всем запросам из config.
        """
        if args:
            # Конкретный запрос от пользователя
            query = " ".join(args)
            self.vacancies = self.searcher.search_hh(query, pages=2)
        else:
            # Все запросы из config.SEARCH_QUERIES
            self.vacancies = self.searcher.search_all_queries()

        if self.vacancies:
            total = len(self.vacancies)
            shown = min(10, total)
            print(f"\n{C.GREEN}Найдено: {total} вакансий{C.RESET} (показаны первые {shown})")
            self._print_vacancies_list(self.vacancies[:shown])
            if total > shown:
                print(f"{C.GRAY}Ещё {total - shown} вакансий скрыто. Используй /list all чтобы увидеть все.{C.RESET}")

            # Сохраняем в JSON
            self.searcher.save_to_json(self.vacancies)
        else:
            print(f"{C.YELLOW}Вакансии не найдены. Попробуй другой запрос.{C.RESET}")

    def cmd_analyze(self, args: list[str]):
        """
        /analyze [N]
        Загружает описания и анализирует вакансии через LLM.
        N — количество вакансий (по умолчанию 10, максимум все найденные).
        """
        if not self.vacancies:
            print(f"{C.YELLOW}Сначала выполни /search{C.RESET}")
            return

        # Определяем сколько вакансий анализировать
        limit = 10
        if args:
            try:
                limit = int(args[0])
            except ValueError:
                print(f"{C.RED}Некорректное число: '{args[0]}'. Используем 10.{C.RESET}")
        limit = min(limit, len(self.vacancies))

        print(f"\n{C.CYAN}[1/2] Загружаю описания ({limit} вакансий)...{C.RESET}")
        self.vacancies = self.searcher.enrich_with_descriptions(self.vacancies[:limit])

        print(f"\n{C.CYAN}[2/2] Анализирую через LLM...{C.RESET}\n")

        try:
            self.analyses = self.analyzer.analyze_batch(self.vacancies)
            # Сбрасываем адаптированные резюме — нумерация изменилась
            self.adapted_resumes = {}

            if self.analyses:
                print(f"\n{C.GREEN}Прошли порог ({config.RELEVANCE_THRESHOLD}+): {len(self.analyses)} вакансий{C.RESET}")
                self._print_analyses_list(self.analyses)
                print(f"{C.YELLOW}Нумерация обновлена — используй /list чтобы увидеть актуальный список.{C.RESET}")
                self.analyzer.save_analysis(self.analyses)
                self._save_session()
            else:
                print(f"{C.YELLOW}Ни одна вакансия не прошла порог {config.RELEVANCE_THRESHOLD}.{C.RESET}")
                print(f"Попробуй снизить RELEVANCE_THRESHOLD в .env файле.")

        except RuntimeError as e:
            print(f"{C.RED}Ошибка: {e}{C.RESET}")

    def cmd_adapt(self, args: list[str]):
        """
        /adapt <N>
        Адаптирует резюме под вакансию с номером N из списка анализов.
        """
        idx = self._parse_index(args, self.analyses, "/adapt")
        if idx is None:
            return

        analysis = self.analyses[idx]
        print(f"\n{C.CYAN}Адаптирую резюме под: {analysis.vacancy_title} | {analysis.company}{C.RESET}")

        try:
            adapted = self.adapter.adapt(analysis)
            self.adapted_resumes[analysis.vacancy_id] = adapted
            self.adapter.save(adapted)

            print(f"\n{C.GREEN}Резюме адаптировано!{C.RESET}")
            print(f"Summary: {adapted.get('adapted_summary', '')[:150]}...")
            print(f"\nТоп навыки: {', '.join(adapted.get('top_skills', [])[:4])}")

        except RuntimeError as e:
            print(f"{C.RED}Ошибка: {e}{C.RESET}")

    def cmd_cover(self, args: list[str]):
        """
        /cover <N> [tone]
        Генерирует сопроводительное письмо для вакансии N.
        tone: professional (по умолчанию) / friendly / concise
        """
        # Первый аргумент — номер, второй (опционально) — тон
        tone = "professional"
        tone_options = {"professional", "friendly", "concise"}
        tone_args = [a for a in args if a in tone_options]
        num_args = [a for a in args if a not in tone_options]

        if tone_args:
            tone = tone_args[0]

        idx = self._parse_index(num_args, self.analyses, "/cover")
        if idx is None:
            return

        analysis = self.analyses[idx]
        adapted = self.adapted_resumes.get(analysis.vacancy_id)  # может быть None — это OK

        if not adapted:
            print(f"{C.YELLOW}Подсказка: сначала выполни /adapt {idx + 1} для лучшего результата{C.RESET}")

        print(f"\n{C.CYAN}Генерирую письмо для: {analysis.company} [{tone}]{C.RESET}")

        try:
            letter = self.cover_gen.generate(analysis, adapted_resume=adapted, tone=tone)
            path = self.cover_gen.save(letter, analysis)

            print(f"\n{C.GREEN}Письмо готово!{C.RESET}")
            print(f"\n{'-'*50}")
            print(letter[:500] + "..." if len(letter) > 500 else letter)
            print(f"{'-'*50}")
            print(f"\nСохранено: {path}")

        except RuntimeError as e:
            print(f"{C.RED}Ошибка: {e}{C.RESET}")

    def cmd_resume(self, args: list[str]):
        """
        /resume <N>
        Экспортирует резюме для вакансии N в MD и PDF форматы.
        """
        idx = self._parse_index(args, self.analyses, "/resume")
        if idx is None:
            return

        # Берём адаптированное резюме или создаём базовый вариант
        adapted = self.adapted_resumes.get(self.analyses[idx].vacancy_id)
        if not adapted:
            print(f"{C.YELLOW}Адаптированное резюме не найдено. Используем базовое.{C.RESET}")
            print(f"Для лучшего результата сначала выполни /adapt {idx + 1}")

            # Создаём минимальный адаптированный вариант из базового резюме
            import json
            with open(config.BASE_RESUME_PATH, encoding="utf-8") as f:
                base = json.load(f)

            analysis = self.analyses[idx]
            adapted = {
                "vacancy_title": analysis.vacancy_title,
                "company": analysis.company,
                "adapted_summary": base.get("summary", ""),
                "top_skills": [
                    s for skills in base.get("skills", {}).values()
                    for s in skills
                ][:8],
                "featured_projects": base.get("projects", [])[:3],
                "additional_skills": [],
                "personal": base.get("personal", {}),
                "education": base.get("education", {}),
                "generated_at": "",
            }

        print(f"\n{C.CYAN}Экспортирую резюме...{C.RESET}")
        md_path = self.exporter.export_resume_md(adapted)
        pdf_path = self.exporter.export_resume_pdf(adapted)

        print(f"\n{C.GREEN}Готово!{C.RESET}")
        print(f"  Markdown: {md_path}")
        if pdf_path:
            print(f"  PDF:      {pdf_path}")

    def cmd_list(self, args: list[str]):
        """
        /list [all | vacancies | apply | maybe | skip | top<N>]
        Показывает список вакансий с опциональной фильтрацией.
          /list           — анализы (если есть) или сырые вакансии
          /list all       — все найденные вакансии
          /list vacancies — сырые вакансии даже после /analyze
          /list apply     — только APPLY из анализов
          /list maybe     — только MAYBE из анализов
          /list skip      — только SKIP из анализов
          /list top5      — топ 5 по score
          /list <N>       — первые N вакансий
        """
        filter_arg = args[0].lower() if args else ""
        show_raw = filter_arg in ("vacancies", "all") and not self.analyses or filter_arg == "vacancies"

        # Фильтрация анализов
        if self.analyses and not show_raw:
            analyses = self.analyses

            if filter_arg == "apply":
                analyses = [a for a in analyses if a.recommendation == "APPLY"]
                label = "APPLY вакансии"
            elif filter_arg == "maybe":
                analyses = [a for a in analyses if a.recommendation == "MAYBE"]
                label = "MAYBE вакансии"
            elif filter_arg == "skip":
                analyses = [a for a in analyses if a.recommendation == "SKIP"]
                label = "SKIP вакансии"
            elif filter_arg.startswith("top") and filter_arg[3:].isdigit():
                n = int(filter_arg[3:])
                analyses = analyses[:n]
                label = f"Топ {n} по релевантности"
            else:
                try:
                    n = int(filter_arg)
                    analyses = analyses[:n]
                    label = f"Первые {n} вакансий"
                except (ValueError, TypeError):
                    label = "Проанализированные вакансии (по релевантности)"

            print(f"\n{C.BOLD}{label}:{C.RESET}")
            if analyses:
                self._print_analyses_list(analyses)
            else:
                print(f"{C.YELLOW}Нет вакансий с таким фильтром.{C.RESET}\n")

            if self.vacancies and filter_arg not in ("apply", "maybe", "skip") and not filter_arg.startswith("top"):
                print(f"{C.GRAY}Найдено всего: {len(self.vacancies)} вакансий. /list vacancies — сырой список.{C.RESET}")

        elif self.vacancies:
            vacancies = self.vacancies
            if filter_arg != "all":
                try:
                    n = int(filter_arg) if filter_arg else 10
                    vacancies = self.vacancies[:n]
                except ValueError:
                    vacancies = self.vacancies[:10]

            total = len(self.vacancies)
            shown = len(vacancies)
            print(f"\n{C.BOLD}Найденные вакансии:{C.RESET} ({shown} из {total})")
            self._print_vacancies_list(vacancies)
            if shown < total:
                print(f"{C.GRAY}Ещё {total - shown} скрыто. /list all — показать все.{C.RESET}")
        else:
            print(f"{C.YELLOW}Список пуст. Выполни /search{C.RESET}")

    def cmd_report(self, args: list[str]):
        """
        /report
        Создаёт Markdown-отчёт по всем проанализированным вакансиям.
        """
        if not self.analyses:
            print(f"{C.YELLOW}Нет данных для отчёта. Выполни /analyze{C.RESET}")
            return

        path = self.exporter.export_analysis_md(self.analyses)
        print(f"\n{C.GREEN}Отчёт создан: {path}{C.RESET}")

    def cmd_open(self, args: list[str]):
        """
        /open <N>
        Открывает вакансию №N в браузере.
        """
        # Работает как по анализам, так и по сырым вакансиям
        if self.analyses:
            idx = self._parse_index(args, self.analyses, "/open")
            if idx is None:
                return
            url = f"https://hh.ru/vacancy/{self.analyses[idx].vacancy_id}"
            title = self.analyses[idx].vacancy_title
        elif self.vacancies:
            idx = self._parse_index(args, self.vacancies, "/open")
            if idx is None:
                return
            url = self.vacancies[idx].url
            title = self.vacancies[idx].title
        else:
            print(f"{C.YELLOW}Список пуст. Выполни /search{C.RESET}")
            return

        print(f"{C.CYAN}Открываю в браузере: {title}{C.RESET}")
        webbrowser.open(url)

    def cmd_run(self, args: list[str]):
        """
        /run [запрос]
        Полный автоматический цикл: search → analyze → report.
        Без аргументов — поиск по всем запросам из config.
        Пример: /run prompt engineer
        """
        print(f"\n{C.CYAN}{C.BOLD}[AUTO] Запускаю полный цикл...{C.RESET}\n")

        # 1. Search — если аргумент не задан, ищем по всем запросам
        self.cmd_search(args)
        if not self.vacancies:
            return

        # 2. Analyze — берём до 20 вакансий (не 10)
        self.cmd_analyze(["20"])
        if not self.analyses:
            print(f"{C.YELLOW}Анализ не дал результатов. Попробуй другой запрос.{C.RESET}")
            return

        # 3. Report
        self.cmd_report([])
        print(f"\n{C.GREEN}{C.BOLD}[AUTO] Готово! Используй /adapt 1 и /cover 1 для лучшей вакансии.{C.RESET}")

    # ── Сохранение / загрузка сессии ──────────────────────────────────────────

    def _session_path(self) -> Path:
        return config.OUTPUT_DIR / "session.json"

    def _save_session(self):
        """Сохраняет analyses в файл сессии для восстановления после перезапуска."""
        try:
            data = {
                "analyses": [a.model_dump() for a in self.analyses],
            }
            with open(self._session_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"{C.GRAY}[Сессия сохранена]{C.RESET}")
        except Exception as e:
            print(f"{C.GRAY}[Сессия не сохранена: {e}]{C.RESET}")

    def _load_session(self):
        """Восстанавливает analyses из файла сессии если он есть."""
        path = self._session_path()
        if not path.exists():
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            from modules.analyzer import VacancyAnalysis
            self.analyses = [VacancyAnalysis(**a) for a in data.get("analyses", [])]
            if self.analyses:
                print(f"{C.GRAY}[Сессия восстановлена: {len(self.analyses)} вакансий из прошлого запуска]{C.RESET}")
                print(f"{C.GRAY} Используй /list чтобы увидеть список, или /search для нового поиска.{C.RESET}\n")
        except Exception as e:
            print(f"{C.GRAY}[Не удалось загрузить сессию: {e}]{C.RESET}")

    # ── Вспомогательные методы ────────────────────────────────────────────────

    def _print_vacancies_list(self, vacancies: list[Vacancy]):
        """Выводит список вакансий в терминал."""
        print()
        for i, v in enumerate(vacancies, 1):
            remote_mark = " [удалённо]" if v.remote else ""
            print(f"  {C.BOLD}{i:2}.{C.RESET} {v.title}")
            print(f"      {C.GRAY}{v.company} | {v.salary_str()}{remote_mark}{C.RESET}")
        print()

    def _print_analyses_list(self, analyses: list[VacancyAnalysis]):
        """Выводит список проанализированных вакансий с оценками."""
        rec_colors = {"APPLY": C.GREEN, "MAYBE": C.YELLOW, "SKIP": C.RED}
        print()
        for i, a in enumerate(analyses, 1):
            color = rec_colors.get(a.recommendation, C.RESET)
            print(f"  {C.BOLD}{i:2}.{C.RESET} {a.vacancy_title}")
            print(f"      {C.GRAY}{a.company}{C.RESET} | "
                  f"Score: {C.BOLD}{a.relevance_score}/100{C.RESET} | "
                  f"{color}{a.recommendation}{C.RESET}")
        print()

    def _parse_index(self, args: list[str], items: list, cmd: str) -> int | None:
        """
        Парсит номер элемента из аргументов команды.
        Возвращает 0-based индекс или None при ошибке.
        """
        if not items:
            print(f"{C.YELLOW}Список пуст. Сначала выполни /search и /analyze{C.RESET}")
            return None

        if not args:
            print(f"{C.YELLOW}Укажи номер вакансии. Пример: {cmd} 1{C.RESET}")
            self._print_analyses_list(items) if hasattr(items[0], 'recommendation') else self._print_vacancies_list(items)
            return None

        try:
            n = int(args[0])
            if not (1 <= n <= len(items)):
                print(f"{C.RED}Номер должен быть от 1 до {len(items)}{C.RESET}")
                return None
            return n - 1  # переводим в 0-based
        except ValueError:
            print(f"{C.RED}Некорректный номер: '{args[0]}'{C.RESET}")
            return None


# ─── Запуск агента ────────────────────────────────────────────────────────────

def main():
    """Основной цикл агента: читаем команды, выполняем."""
    print_header()
    print_help()

    agent = Agent()
    agent._load_session()

    # Словарь команд -> метод
    commands = {
        "/search":  agent.cmd_search,
        "/analyze": agent.cmd_analyze,
        "/adapt":   agent.cmd_adapt,
        "/cover":   agent.cmd_cover,
        "/resume":  agent.cmd_resume,
        "/list":    agent.cmd_list,
        "/report":  agent.cmd_report,
        "/open":    agent.cmd_open,
        "/run":     agent.cmd_run,
        "/help":    lambda _: print_help(),
    }

    print(f"{C.GRAY}Введи команду (или /help для справки):{C.RESET}\n")

    while True:
        try:
            raw = input(f"{C.CYAN}agent>{C.RESET} ").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{C.GRAY}Выход.{C.RESET}")
            break

        if not raw:
            continue

        if raw in ("/quit", "/exit", "quit", "exit", "q"):
            print(f"{C.GRAY}До свидания!{C.RESET}")
            break

        parts = raw.split()
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd in commands:
            try:
                commands[cmd](args)
            except Exception as e:
                print(f"{C.RED}Ошибка при выполнении {cmd}: {e}{C.RESET}")
        else:
            print(f"{C.YELLOW}Неизвестная команда: '{cmd}'. Введи /help{C.RESET}")


if __name__ == "__main__":
    main()
