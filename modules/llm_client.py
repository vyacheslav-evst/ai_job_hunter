"""
llm_client.py — универсальный LLM клиент
Работает через OpenRouter (OpenAI-совместимый API).
Чтобы переключиться на OpenAI — меняем только base_url и api_key в .env.
"""

import json
import re
import time
import requests
import urllib3
from typing import Optional

import config

# Применяем прокси (нужно для доступа через Happ VPN)
config.apply_proxy()

# Happ VPN перехватывает SSL — отключаем предупреждения о verify=False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)



# Список бесплатных моделей-фоллбэков (в порядке предпочтения).
# Если основная модель недоступна — пробуем следующую.
FALLBACK_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "openai/gpt-oss-120b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-31b-it:free",
]

# Модели которые не поддерживают system role
GEMMA_MODELS = {"google/gemma-4-31b-it:free"}

# Задержки для exponential backoff при 429 (секунды)
BACKOFF_DELAYS = [10, 20, 40]


class LLMClient:
    """
    Тонкая обёртка над OpenRouter/OpenAI Chat Completions API.
    Используется всеми модулями вместо google-genai.
    При 429 (rate limit) делает exponential backoff на текущей модели,
    затем переключается на следующую из FALLBACK_MODELS.
    """

    def __init__(self):
        self.api_key = config.OPENROUTER_API_KEY
        self.base_url = config.OPENROUTER_BASE_URL
        # Основная модель из .env, остальные — резервные
        self.model = config.LLM_MODEL
        self._models = [self.model] + [m for m in FALLBACK_MODELS if m != self.model]
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # OpenRouter рекомендует передавать эти заголовки для статистики
            "HTTP-Referer": "https://github.com/ai-job-hunter",
            "X-Title": "AI Job Hunter Agent",
        }
        print(f"[LLM] Инициализирован. Модель: {self.model}")

    def _call_model(self, model: str, payload: dict, system: str) -> Optional[str]:
        """
        Делает один запрос к модели с exponential backoff при 429.
        Возвращает текст ответа или None если модель недоступна.
        """
        # Для Gemma убираем system role — встраиваем в user-сообщение
        if model in GEMMA_MODELS:
            user_content = payload["messages"][-1]["content"]
            payload = {**payload, "messages": [{"role": "user", "content": f"{system}\n\n{user_content}"}]}
        else:
            msgs = [{"role": "system", "content": system}] + [
                m for m in payload["messages"] if m["role"] != "system"
            ]
            payload = {**payload, "messages": msgs}

        payload = {**payload, "model": model}

        for attempt, delay in enumerate([0] + BACKOFF_DELAYS):
            if delay:
                print(f"[LLM] 429 на {model}, жду {delay}с (попытка {attempt+1}/{len(BACKOFF_DELAYS)+1})...")
                time.sleep(delay)
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=self.headers,
                    json=payload,
                    timeout=60,
                    verify=False,  # Happ VPN перехватывает SSL, отключаем проверку
                )
                if response.status_code == 429:
                    if attempt < len(BACKOFF_DELAYS):
                        continue  # повторяем с задержкой
                    print(f"[LLM] {model} исчерпал попытки (429), переключаюсь...")
                    return None
                response.raise_for_status()
                data = response.json()
                choices = data.get("choices", [])
                if not choices or not choices[0].get("message", {}).get("content"):
                    print(f"[LLM] Пустой ответ от {model}")
                    return None
                content = choices[0]["message"]["content"].strip()
                content = self._strip_reasoning(content)
                return content

            except requests.exceptions.Timeout:
                print(f"[LLM] Таймаут (60с) на {model}")
                return None
            except requests.exceptions.HTTPError as e:
                print(f"[LLM] HTTP {response.status_code} на {model}: {response.text[:120]}")
                return None
            except Exception as e:
                print(f"[LLM] Ошибка на {model}: {e}")
                return None

        return None

    def chat(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 2000,
        system: str = "Ты — полезный AI-ассистент. Отвечай на русском языке.",
    ) -> Optional[str]:
        """
        Отправляет сообщение и возвращает текст ответа.
        При неудаче перебирает все модели из FALLBACK_MODELS.

        Args:
            prompt: Текст запроса
            temperature: 0.0–1.0 (выше = креативнее)
            max_tokens: Максимальная длина ответа
            system: Системный промпт

        Returns:
            Текст ответа или None при ошибке
        """
        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        for model in self._models:
            if model != self.model:
                print(f"[LLM] Переключаюсь на: {model}")
            result = self._call_model(model, payload, system)
            if result is not None:
                return result

        print("[LLM] Все модели недоступны.")
        return None

    def chat_json(
        self,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 2000,
    ) -> Optional[dict]:
        """
        Отправляет запрос и парсит ответ как JSON.
        Удобно для структурированных задач (анализ, адаптация).

        Returns:
            Словарь из JSON или None при ошибке парсинга
        """
        text = self.chat(
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            system="Ты — полезный AI-ассистент. Отвечай ТОЛЬКО валидным JSON без ```json обёрток.",
        )

        if not text:
            return None

        return self._parse_json(text)

    def _strip_reasoning(self, text: str) -> str:
        """
        Убирает thinking-блок reasoning-моделей (Nemotron и др.).
        Они пишут план на английском, потом выдают ответ на русском.
        Берём последний связный блок текста после пустых строк.
        """
        # Если есть тег <think>...</think> — убираем его
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

        # Разбиваем на параграфы и берём последний большой блок на кириллице
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        cyrillic_blocks = [p for p in paragraphs if re.search(r"[а-яА-ЯёЁ]{10,}", p)]

        if cyrillic_blocks:
            return "\n\n".join(cyrillic_blocks)

        return text

    def _parse_json(self, text: str) -> Optional[dict]:
        """Извлекает JSON из текста, убирая markdown-блоки и reasoning если есть."""
        # Убираем <think>...</think> блок если есть
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        # Убираем markdown-обёртки
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text).strip()

        # Ищем первый JSON-объект (для reasoning-моделей которые пишут текст до/после)
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            print(f"[LLM] Не удалось распарсить JSON: {text[:80]}...")
            return None


# ─── Тест ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    client = LLMClient()
    result = client.chat("Ответь одним словом: РАБОТАЕТ")
    print("Ответ:", result)

    """
    Тонкая обёртка над OpenRouter/OpenAI Chat Completions API.
    Используется всеми модулями вместо google-genai.
    При 429 (rate limit) автоматически переключается на следующую модель из FALLBACK_MODELS.
    """

    def __init__(self):
        self.api_key = config.OPENROUTER_API_KEY
        self.base_url = config.OPENROUTER_BASE_URL
        # Основная модель из .env, остальные — резервные
        self.model = config.LLM_MODEL
        self._models = [self.model] + [m for m in FALLBACK_MODELS if m != self.model]
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # OpenRouter рекомендует передавать эти заголовки для статистики
            "HTTP-Referer": "https://github.com/ai-job-hunter",
            "X-Title": "AI Job Hunter Agent",
        }
        print(f"[LLM] Инициализирован. Модель: {self.model}")

    def chat(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 2000,
        system: str = "Ты — полезный AI-ассистент. Отвечай на русском языке.",
    ) -> Optional[str]:
        """
        Отправляет сообщение и возвращает текст ответа.

        Args:
            prompt: Текст запроса
            temperature: 0.0–1.0 (выше = креативнее)
            max_tokens: Максимальная длина ответа
            system: Системный промпт

        Returns:
            Текст ответа или None при ошибке
        """
        # Модели Gemma не поддерживают system role — встраиваем в user-сообщение
        GEMMA_MODELS = {"google/gemma-3-27b-it:free", "google/gemma-3-12b-it:free"}

        base_messages_with_system = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        base_messages_no_system = [
            {"role": "user", "content": f"{system}\n\n{prompt}"},
        ]

        payload = {
            "model": self.model,
            "messages": base_messages_with_system,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # Пробуем модели по очереди при rate limit (429)
        for model in self._models:
            payload["model"] = model
            # Для Gemma убираем system role
            payload["messages"] = base_messages_no_system if model in GEMMA_MODELS else base_messages_with_system
            if model != self.model:
                print(f"[LLM] Переключаюсь на резервную модель: {model}")
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=self.headers,
                    json=payload,
                    timeout=120,  # большие модели могут отвечать до 2 минут
                )
                if response.status_code == 429:
                    print(f"[LLM] 429 Rate limit на {model}, пробую следующую...")
                    continue
                response.raise_for_status()
                data = response.json()
                choices = data.get("choices", [])
                if not choices or not choices[0].get("message", {}).get("content"):
                    print(f"[LLM] Пустой choices на {model}, пробую следующую...")
                    continue
                content = choices[0]["message"]["content"].strip()
                # Nemotron и другие reasoning-модели добавляют блок размышлений перед ответом.
                # Отрезаем всё до последнего абзаца после пустой строки с кириллицей.
                content = self._strip_reasoning(content)
                return content

            except requests.exceptions.Timeout:
                print(f"[LLM] Таймаут на {model}, пробую следующую...")
                continue
            except requests.exceptions.HTTPError as e:
                print(f"[LLM] ОШИБКА HTTP {response.status_code} на {model}: {response.text[:150]}")
                continue
            except Exception as e:
                print(f"[LLM] ОШИБКА на {model}: {e}")
                continue

        print("[LLM] Все модели недоступны.")
        return None

    def chat_json(
        self,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 2000,
    ) -> Optional[dict]:
        """
        Отправляет запрос и парсит ответ как JSON.
        Удобно для структурированных задач (анализ, адаптация).

        Returns:
            Словарь из JSON или None при ошибке парсинга
        """
        text = self.chat(
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            system="Ты — полезный AI-ассистент. Отвечай ТОЛЬКО валидным JSON без ```json обёрток.",
        )

        if not text:
            return None

        return self._parse_json(text)

    def _strip_reasoning(self, text: str) -> str:
        """
        Убирает thinking-блок reasoning-моделей (Nemotron и др.).
        Они пишут план на английском, потом выдают ответ на русском.
        Берём последний связный блок текста после пустых строк.
        """
        import re
        # Если есть тег <think>...</think> — убираем его
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

        # Разбиваем на параграфы и берём последний большой блок на кириллице
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        cyrillic_blocks = [p for p in paragraphs if re.search(r"[а-яА-ЯёЁ]{10,}", p)]

        if cyrillic_blocks:
            # Возвращаем все кириллические параграфы подряд
            return "\n\n".join(cyrillic_blocks)

        return text

    def _parse_json(self, text: str) -> Optional[dict]:
        """Извлекает JSON из текста, убирая markdown-блоки и reasoning если есть."""
        import re
        # Убираем <think>...</think> блок если есть
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        # Убираем markdown-обёртки
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text).strip()

        # Ищем первый JSON-объект (для reasoning-моделей которые пишут текст до/после)
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            print(f"[LLM] Не удалось распарсить JSON: {text[:80]}...")
            return None


# ─── Тест ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    client = LLMClient()
    result = client.chat("Ответь одним словом: РАБОТАЕТ")
    print("Ответ:", result)
