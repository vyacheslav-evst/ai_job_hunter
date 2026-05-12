"""
autonomous_agent.py — автономный ReAct-агент на LangGraph.

Агент самостоятельно планирует и выполняет полный цикл поиска работы:
  1. Ищет вакансии (search_vacancies)
  2. Анализирует их через LLM (analyze_vacancies)
  3. Адаптирует резюме под лучшие (adapt_resume)
  4. Генерирует сопроводительные письма (generate_cover_letter)
  5. Создаёт итоговый отчёт (export_report)

Запуск через /auto в agent.py или напрямую:
  from modules.autonomous_agent import run_autonomous_agent
  run_autonomous_agent("prompt engineer")
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from modules.tools import ALL_TOOLS

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent


# ─── Системный промпт агента ──────────────────────────────────────────────────

SYSTEM_PROMPT = """Ты — автономный AI Job Hunter агент. Твоя задача — самостоятельно пройти полный цикл поиска работы.

## Инструменты
У тебя есть следующие инструменты (используй их именно в этом порядке):
1. search_vacancies — найти вакансии по запросу
2. analyze_vacancies — проанализировать найденные вакансии через LLM
3. adapt_resume — адаптировать резюме под конкретную вакансию
4. generate_cover_letter — написать сопроводительное письмо
5. export_report — создать итоговый отчёт (Markdown)
6. export_all_pdf — создать PDF-пакет (отчёт + резюме + письмо)
7. get_session_state — проверить текущий прогресс

## Стратегия работы
1. Начни с search_vacancies по заданному запросу (он автоматически расширит поиск до 3-5 запросов)
2. Проанализируй вакансии через analyze_vacancies (используй limit="50")
3. Для топ-1 вакансии с рекомендацией APPLY (или MAYBE если APPLY нет):
   - Выполни adapt_resume с номером этой вакансии
   - Выполни generate_cover_letter с тем же номером
4. Создай Markdown-отчёт через export_report
5. Создай PDF-пакет через export_all_pdf
6. Сообщи пользователю результаты: сколько вакансий найдено, проанализировано,
   топ-3 по релевантности с оценками, пути к PDF-файлам

## Правила
- Всегда используй get_session_state если не уверен в текущем состоянии
- Адаптируй резюме и письмо только для ЛУЧШЕЙ вакансии (наибольший score)
- Если вакансий не найдено — сообщи об этом и предложи другой запрос
- Отвечай на русском языке
"""


def run_autonomous_agent(query: str, verbose: bool = True) -> str:
    """
    Запускает автономного агента для полного цикла поиска работы.

    Args:
        query: Поисковый запрос (например, "prompt engineer" или "AI engineer")
        verbose: Выводить ли промежуточные шаги агента

    Returns:
        Финальный ответ агента с результатами
    """
    if not config.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY не задан в .env файле")

    # Создаём LLM с привязкой инструментов
    llm = ChatOpenAI(
        model=config.LLM_MODEL,
        api_key=config.OPENAI_API_KEY,
        temperature=0.1,
    )

    # Создаём ReAct-агент через LangGraph prebuilt
    agent = create_react_agent(
        model=llm,
        tools=ALL_TOOLS,
        prompt=SYSTEM_PROMPT,
    )

    # Формируем задачу для агента
    task = f"Найди и обработай вакансии по запросу: {query}"

    if verbose:
        print(f"\n[AUTO AGENT] Запускаю автономный поиск: '{query}'")
        print(f"[AUTO AGENT] Модель: {config.LLM_MODEL}")
        print(f"[AUTO AGENT] Инструменты: {[t.name for t in ALL_TOOLS]}\n")

    # Запускаем агента с потоковым выводом шагов
    final_response = ""

    for step in agent.stream(
        {"messages": [HumanMessage(content=task)]},
        stream_mode="values",
    ):
        messages = step.get("messages", [])
        if not messages:
            continue

        last_msg = messages[-1]

        # Выводим действия агента (вызовы инструментов)
        if verbose and hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            for tc in last_msg.tool_calls:
                print(f"  [TOOL] {tc['name']}({tc['args']})")

        # Выводим результаты инструментов
        if verbose and hasattr(last_msg, "name") and last_msg.name:
            preview = str(last_msg.content)[:120].replace("\n", " ")
            print(f"  [RESULT] {preview}...")

        # Финальный ответ — AIMessage без tool_calls
        if (
            hasattr(last_msg, "content")
            and last_msg.content
            and not getattr(last_msg, "tool_calls", None)
            and not getattr(last_msg, "name", None)
        ):
            final_response = last_msg.content

    return final_response
