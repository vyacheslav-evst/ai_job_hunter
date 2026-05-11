"""
llm_client.py вЂ” СѓРЅРёРІРµСЂСЃР°Р»СЊРЅС‹Р№ LLM РєР»РёРµРЅС‚
Р Р°Р±РѕС‚Р°РµС‚ С‡РµСЂРµР· OpenRouter (OpenAI-СЃРѕРІРјРµСЃС‚РёРјС‹Р№ API).
Р§С‚РѕР±С‹ РїРµСЂРµРєР»СЋС‡РёС‚СЊСЃСЏ РЅР° OpenAI вЂ” РјРµРЅСЏРµРј С‚РѕР»СЊРєРѕ base_url Рё api_key РІ .env.
"""

import json
import re
import time
import requests
import urllib3
from typing import Optional

import config

# РџСЂРёРјРµРЅСЏРµРј РїСЂРѕРєСЃРё (РЅСѓР¶РЅРѕ РґР»СЏ РґРѕСЃС‚СѓРїР° С‡РµСЂРµР· Happ VPN)
config.apply_proxy()

# Happ VPN РїРµСЂРµС…РІР°С‚С‹РІР°РµС‚ SSL вЂ” РѕС‚РєР»СЋС‡Р°РµРј РїСЂРµРґСѓРїСЂРµР¶РґРµРЅРёСЏ Рѕ verify=False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)



# РЎРїРёСЃРѕРє Р±РµСЃРїР»Р°С‚РЅС‹С… РјРѕРґРµР»РµР№-С„РѕР»Р»Р±СЌРєРѕРІ (РІ РїРѕСЂСЏРґРєРµ РїСЂРµРґРїРѕС‡С‚РµРЅРёСЏ).
# Р•СЃР»Рё РѕСЃРЅРѕРІРЅР°СЏ РјРѕРґРµР»СЊ РЅРµРґРѕСЃС‚СѓРїРЅР° вЂ” РїСЂРѕР±СѓРµРј СЃР»РµРґСѓСЋС‰СѓСЋ.
FALLBACK_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "openai/gpt-oss-120b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-31b-it:free",
]

# РњРѕРґРµР»Рё РєРѕС‚РѕСЂС‹Рµ РЅРµ РїРѕРґРґРµСЂР¶РёРІР°СЋС‚ system role
GEMMA_MODELS = {"google/gemma-4-31b-it:free"}

# Р—Р°РґРµСЂР¶РєРё РґР»СЏ exponential backoff РїСЂРё 429 (СЃРµРєСѓРЅРґС‹)
BACKOFF_DELAYS = [10, 20, 40]


class LLMClient:
    """
    РўРѕРЅРєР°СЏ РѕР±С‘СЂС‚РєР° РЅР°Рґ OpenRouter/OpenAI Chat Completions API.
    РСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ РІСЃРµРјРё РјРѕРґСѓР»СЏРјРё РІРјРµСЃС‚Рѕ google-genai.
    РџСЂРё 429 (rate limit) РґРµР»Р°РµС‚ exponential backoff РЅР° С‚РµРєСѓС‰РµР№ РјРѕРґРµР»Рё,
    Р·Р°С‚РµРј РїРµСЂРµРєР»СЋС‡Р°РµС‚СЃСЏ РЅР° СЃР»РµРґСѓСЋС‰СѓСЋ РёР· FALLBACK_MODELS.
    """

    def __init__(self) -> None:
        self.api_key = config.OPENROUTER_API_KEY
        self.base_url = config.OPENROUTER_BASE_URL
        # РћСЃРЅРѕРІРЅР°СЏ РјРѕРґРµР»СЊ РёР· .env, РѕСЃС‚Р°Р»СЊРЅС‹Рµ вЂ” СЂРµР·РµСЂРІРЅС‹Рµ
        self.model = config.LLM_MODEL
        self._models = [self.model] + [m for m in FALLBACK_MODELS if m != self.model]
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # OpenRouter СЂРµРєРѕРјРµРЅРґСѓРµС‚ РїРµСЂРµРґР°РІР°С‚СЊ СЌС‚Рё Р·Р°РіРѕР»РѕРІРєРё РґР»СЏ СЃС‚Р°С‚РёСЃС‚РёРєРё
            "HTTP-Referer": "https://github.com/ai-job-hunter",
            "X-Title": "AI Job Hunter Agent",
        }
        print(f"[LLM] РРЅРёС†РёР°Р»РёР·РёСЂРѕРІР°РЅ. РњРѕРґРµР»СЊ: {self.model}")

    def _call_model(self, model: str, payload: dict, system: str) -> Optional[str]:
        """
        Р”РµР»Р°РµС‚ РѕРґРёРЅ Р·Р°РїСЂРѕСЃ Рє РјРѕРґРµР»Рё СЃ exponential backoff РїСЂРё 429.
        Р’РѕР·РІСЂР°С‰Р°РµС‚ С‚РµРєСЃС‚ РѕС‚РІРµС‚Р° РёР»Рё None РµСЃР»Рё РјРѕРґРµР»СЊ РЅРµРґРѕСЃС‚СѓРїРЅР°.
        """
        # Р”Р»СЏ Gemma СѓР±РёСЂР°РµРј system role вЂ” РІСЃС‚СЂР°РёРІР°РµРј РІ user-СЃРѕРѕР±С‰РµРЅРёРµ
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
                print(f"[LLM] 429 РЅР° {model}, Р¶РґСѓ {delay}СЃ (РїРѕРїС‹С‚РєР° {attempt+1}/{len(BACKOFF_DELAYS)+1})...")
                time.sleep(delay)
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=self.headers,
                    json=payload,
                    timeout=60,
                    verify=False,  # Happ VPN РїРµСЂРµС…РІР°С‚С‹РІР°РµС‚ SSL, РѕС‚РєР»СЋС‡Р°РµРј РїСЂРѕРІРµСЂРєСѓ
                )
                if response.status_code == 429:
                    if attempt < len(BACKOFF_DELAYS):
                        continue  # РїРѕРІС‚РѕСЂСЏРµРј СЃ Р·Р°РґРµСЂР¶РєРѕР№
                    print(f"[LLM] {model} РёСЃС‡РµСЂРїР°Р» РїРѕРїС‹С‚РєРё (429), РїРµСЂРµРєР»СЋС‡Р°СЋСЃСЊ...")
                    return None
                response.raise_for_status()
                data = response.json()
                choices = data.get("choices", [])
                if not choices or not choices[0].get("message", {}).get("content"):
                    print(f"[LLM] РџСѓСЃС‚РѕР№ РѕС‚РІРµС‚ РѕС‚ {model}")
                    return None
                content = choices[0]["message"]["content"].strip()
                content = self._strip_reasoning(content)
                return content

            except requests.exceptions.Timeout:
                print(f"[LLM] РўР°Р№РјР°СѓС‚ (60СЃ) РЅР° {model}")
                return None
            except requests.exceptions.HTTPError as e:
                print(f"[LLM] HTTP {response.status_code} РЅР° {model}: {response.text[:120]}")
                return None
            except Exception as e:
                print(f"[LLM] РћС€РёР±РєР° РЅР° {model}: {e}")
                return None

        return None

    def chat(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 2000,
        system: str = "РўС‹ вЂ” РїРѕР»РµР·РЅС‹Р№ AI-Р°СЃСЃРёСЃС‚РµРЅС‚. РћС‚РІРµС‡Р°Р№ РЅР° СЂСѓСЃСЃРєРѕРј СЏР·С‹РєРµ.",
    ) -> Optional[str]:
        """
        РћС‚РїСЂР°РІР»СЏРµС‚ СЃРѕРѕР±С‰РµРЅРёРµ Рё РІРѕР·РІСЂР°С‰Р°РµС‚ С‚РµРєСЃС‚ РѕС‚РІРµС‚Р°.
        РџСЂРё РЅРµСѓРґР°С‡Рµ РїРµСЂРµР±РёСЂР°РµС‚ РІСЃРµ РјРѕРґРµР»Рё РёР· FALLBACK_MODELS.

        Args:
            prompt: РўРµРєСЃС‚ Р·Р°РїСЂРѕСЃР°
            temperature: 0.0вЂ“1.0 (РІС‹С€Рµ = РєСЂРµР°С‚РёРІРЅРµРµ)
            max_tokens: РњР°РєСЃРёРјР°Р»СЊРЅР°СЏ РґР»РёРЅР° РѕС‚РІРµС‚Р°
            system: РЎРёСЃС‚РµРјРЅС‹Р№ РїСЂРѕРјРїС‚

        Returns:
            РўРµРєСЃС‚ РѕС‚РІРµС‚Р° РёР»Рё None РїСЂРё РѕС€РёР±РєРµ
        """
        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        for model in self._models:
            if model != self.model:
                print(f"[LLM] РџРµСЂРµРєР»СЋС‡Р°СЋСЃСЊ РЅР°: {model}")
            result = self._call_model(model, payload, system)
            if result is not None:
                return result

        print("[LLM] Р’СЃРµ РјРѕРґРµР»Рё РЅРµРґРѕСЃС‚СѓРїРЅС‹.")
        return None

    def chat_json(
        self,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 2000,
    ) -> Optional[dict]:
        """
        РћС‚РїСЂР°РІР»СЏРµС‚ Р·Р°РїСЂРѕСЃ Рё РїР°СЂСЃРёС‚ РѕС‚РІРµС‚ РєР°Рє JSON.
        РЈРґРѕР±РЅРѕ РґР»СЏ СЃС‚СЂСѓРєС‚СѓСЂРёСЂРѕРІР°РЅРЅС‹С… Р·Р°РґР°С‡ (Р°РЅР°Р»РёР·, Р°РґР°РїС‚Р°С†РёСЏ).

        Returns:
            РЎР»РѕРІР°СЂСЊ РёР· JSON РёР»Рё None РїСЂРё РѕС€РёР±РєРµ РїР°СЂСЃРёРЅРіР°
        """
        text = self.chat(
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            system="РўС‹ вЂ” РїРѕР»РµР·РЅС‹Р№ AI-Р°СЃСЃРёСЃС‚РµРЅС‚. РћС‚РІРµС‡Р°Р№ РўРћР›Р¬РљРћ РІР°Р»РёРґРЅС‹Рј JSON Р±РµР· ```json РѕР±С‘СЂС‚РѕРє.",
        )

        if not text:
            return None

        return self._parse_json(text)

    def _strip_reasoning(self, text: str) -> str:
        """
        РЈР±РёСЂР°РµС‚ thinking-Р±Р»РѕРє reasoning-РјРѕРґРµР»РµР№ (Nemotron Рё РґСЂ.).
        РћРЅРё РїРёС€СѓС‚ РїР»Р°РЅ РЅР° Р°РЅРіР»РёР№СЃРєРѕРј, РїРѕС‚РѕРј РІС‹РґР°СЋС‚ РѕС‚РІРµС‚ РЅР° СЂСѓСЃСЃРєРѕРј.
        Р‘РµСЂС‘Рј РїРѕСЃР»РµРґРЅРёР№ СЃРІСЏР·РЅС‹Р№ Р±Р»РѕРє С‚РµРєСЃС‚Р° РїРѕСЃР»Рµ РїСѓСЃС‚С‹С… СЃС‚СЂРѕРє.
        """
        # Р•СЃР»Рё РµСЃС‚СЊ С‚РµРі <think>...</think> вЂ” СѓР±РёСЂР°РµРј РµРіРѕ
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

        # Р Р°Р·Р±РёРІР°РµРј РЅР° РїР°СЂР°РіСЂР°С„С‹ Рё Р±РµСЂС‘Рј РїРѕСЃР»РµРґРЅРёР№ Р±РѕР»СЊС€РѕР№ Р±Р»РѕРє РЅР° РєРёСЂРёР»Р»РёС†Рµ
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        cyrillic_blocks = [p for p in paragraphs if re.search(r"[Р°-СЏРђ-РЇС‘РЃ]{10,}", p)]

        if cyrillic_blocks:
            return "\n\n".join(cyrillic_blocks)

        return text

    def _parse_json(self, text: str) -> Optional[dict]:
        """РР·РІР»РµРєР°РµС‚ JSON РёР· С‚РµРєСЃС‚Р°, СѓР±РёСЂР°СЏ markdown-Р±Р»РѕРєРё Рё reasoning РµСЃР»Рё РµСЃС‚СЊ."""
        # РЈР±РёСЂР°РµРј <think>...</think> Р±Р»РѕРє РµСЃР»Рё РµСЃС‚СЊ
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        # РЈР±РёСЂР°РµРј markdown-РѕР±С‘СЂС‚РєРё
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text).strip()

        # РС‰РµРј РїРµСЂРІС‹Р№ JSON-РѕР±СЉРµРєС‚ (РґР»СЏ reasoning-РјРѕРґРµР»РµР№ РєРѕС‚РѕСЂС‹Рµ РїРёС€СѓС‚ С‚РµРєСЃС‚ РґРѕ/РїРѕСЃР»Рµ)
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            print(f"[LLM] РќРµ СѓРґР°Р»РѕСЃСЊ СЂР°СЃРїР°СЂСЃРёС‚СЊ JSON: {text[:80]}...")
            return None


# в”Ђв”Ђв”Ђ РўРµСЃС‚ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

if __name__ == "__main__":
    client = LLMClient()
    result = client.chat("РћС‚РІРµС‚СЊ РѕРґРЅРёРј СЃР»РѕРІРѕРј: Р РђР‘РћРўРђР•Рў")
    print("РћС‚РІРµС‚:", result)

    """
    РўРѕРЅРєР°СЏ РѕР±С‘СЂС‚РєР° РЅР°Рґ OpenRouter/OpenAI Chat Completions API.
    РСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ РІСЃРµРјРё РјРѕРґСѓР»СЏРјРё РІРјРµСЃС‚Рѕ google-genai.
    РџСЂРё 429 (rate limit) Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё РїРµСЂРµРєР»СЋС‡Р°РµС‚СЃСЏ РЅР° СЃР»РµРґСѓСЋС‰СѓСЋ РјРѕРґРµР»СЊ РёР· FALLBACK_MODELS.
    """

    def __init__(self) -> None:
        self.api_key = config.OPENROUTER_API_KEY
        self.base_url = config.OPENROUTER_BASE_URL
        # РћСЃРЅРѕРІРЅР°СЏ РјРѕРґРµР»СЊ РёР· .env, РѕСЃС‚Р°Р»СЊРЅС‹Рµ вЂ” СЂРµР·РµСЂРІРЅС‹Рµ
        self.model = config.LLM_MODEL
        self._models = [self.model] + [m for m in FALLBACK_MODELS if m != self.model]
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # OpenRouter СЂРµРєРѕРјРµРЅРґСѓРµС‚ РїРµСЂРµРґР°РІР°С‚СЊ СЌС‚Рё Р·Р°РіРѕР»РѕРІРєРё РґР»СЏ СЃС‚Р°С‚РёСЃС‚РёРєРё
            "HTTP-Referer": "https://github.com/ai-job-hunter",
            "X-Title": "AI Job Hunter Agent",
        }
        print(f"[LLM] РРЅРёС†РёР°Р»РёР·РёСЂРѕРІР°РЅ. РњРѕРґРµР»СЊ: {self.model}")

    def chat(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 2000,
        system: str = "РўС‹ вЂ” РїРѕР»РµР·РЅС‹Р№ AI-Р°СЃСЃРёСЃС‚РµРЅС‚. РћС‚РІРµС‡Р°Р№ РЅР° СЂСѓСЃСЃРєРѕРј СЏР·С‹РєРµ.",
    ) -> Optional[str]:
        """
        РћС‚РїСЂР°РІР»СЏРµС‚ СЃРѕРѕР±С‰РµРЅРёРµ Рё РІРѕР·РІСЂР°С‰Р°РµС‚ С‚РµРєСЃС‚ РѕС‚РІРµС‚Р°.

        Args:
            prompt: РўРµРєСЃС‚ Р·Р°РїСЂРѕСЃР°
            temperature: 0.0вЂ“1.0 (РІС‹С€Рµ = РєСЂРµР°С‚РёРІРЅРµРµ)
            max_tokens: РњР°РєСЃРёРјР°Р»СЊРЅР°СЏ РґР»РёРЅР° РѕС‚РІРµС‚Р°
            system: РЎРёСЃС‚РµРјРЅС‹Р№ РїСЂРѕРјРїС‚

        Returns:
            РўРµРєСЃС‚ РѕС‚РІРµС‚Р° РёР»Рё None РїСЂРё РѕС€РёР±РєРµ
        """
        # РњРѕРґРµР»Рё Gemma РЅРµ РїРѕРґРґРµСЂР¶РёРІР°СЋС‚ system role вЂ” РІСЃС‚СЂР°РёРІР°РµРј РІ user-СЃРѕРѕР±С‰РµРЅРёРµ
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

        # РџСЂРѕР±СѓРµРј РјРѕРґРµР»Рё РїРѕ РѕС‡РµСЂРµРґРё РїСЂРё rate limit (429)
        for model in self._models:
            payload["model"] = model
            # Р”Р»СЏ Gemma СѓР±РёСЂР°РµРј system role
            payload["messages"] = base_messages_no_system if model in GEMMA_MODELS else base_messages_with_system
            if model != self.model:
                print(f"[LLM] РџРµСЂРµРєР»СЋС‡Р°СЋСЃСЊ РЅР° СЂРµР·РµСЂРІРЅСѓСЋ РјРѕРґРµР»СЊ: {model}")
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=self.headers,
                    json=payload,
                    timeout=120,  # Р±РѕР»СЊС€РёРµ РјРѕРґРµР»Рё РјРѕРіСѓС‚ РѕС‚РІРµС‡Р°С‚СЊ РґРѕ 2 РјРёРЅСѓС‚
                )
                if response.status_code == 429:
                    print(f"[LLM] 429 Rate limit РЅР° {model}, РїСЂРѕР±СѓСЋ СЃР»РµРґСѓСЋС‰СѓСЋ...")
                    continue
                response.raise_for_status()
                data = response.json()
                choices = data.get("choices", [])
                if not choices or not choices[0].get("message", {}).get("content"):
                    print(f"[LLM] РџСѓСЃС‚РѕР№ choices РЅР° {model}, РїСЂРѕР±СѓСЋ СЃР»РµРґСѓСЋС‰СѓСЋ...")
                    continue
                content = choices[0]["message"]["content"].strip()
                # Nemotron Рё РґСЂСѓРіРёРµ reasoning-РјРѕРґРµР»Рё РґРѕР±Р°РІР»СЏСЋС‚ Р±Р»РѕРє СЂР°Р·РјС‹С€Р»РµРЅРёР№ РїРµСЂРµРґ РѕС‚РІРµС‚РѕРј.
                # РћС‚СЂРµР·Р°РµРј РІСЃС‘ РґРѕ РїРѕСЃР»РµРґРЅРµРіРѕ Р°Р±Р·Р°С†Р° РїРѕСЃР»Рµ РїСѓСЃС‚РѕР№ СЃС‚СЂРѕРєРё СЃ РєРёСЂРёР»Р»РёС†РµР№.
                content = self._strip_reasoning(content)
                return content

            except requests.exceptions.Timeout:
                print(f"[LLM] РўР°Р№РјР°СѓС‚ РЅР° {model}, РїСЂРѕР±СѓСЋ СЃР»РµРґСѓСЋС‰СѓСЋ...")
                continue
            except requests.exceptions.HTTPError as e:
                print(f"[LLM] РћРЁРР‘РљРђ HTTP {response.status_code} РЅР° {model}: {response.text[:150]}")
                continue
            except Exception as e:
                print(f"[LLM] РћРЁРР‘РљРђ РЅР° {model}: {e}")
                continue

        print("[LLM] Р’СЃРµ РјРѕРґРµР»Рё РЅРµРґРѕСЃС‚СѓРїРЅС‹.")
        return None

    def chat_json(
        self,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 2000,
    ) -> Optional[dict]:
        """
        РћС‚РїСЂР°РІР»СЏРµС‚ Р·Р°РїСЂРѕСЃ Рё РїР°СЂСЃРёС‚ РѕС‚РІРµС‚ РєР°Рє JSON.
        РЈРґРѕР±РЅРѕ РґР»СЏ СЃС‚СЂСѓРєС‚СѓСЂРёСЂРѕРІР°РЅРЅС‹С… Р·Р°РґР°С‡ (Р°РЅР°Р»РёР·, Р°РґР°РїС‚Р°С†РёСЏ).

        Returns:
            РЎР»РѕРІР°СЂСЊ РёР· JSON РёР»Рё None РїСЂРё РѕС€РёР±РєРµ РїР°СЂСЃРёРЅРіР°
        """
        text = self.chat(
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            system="РўС‹ вЂ” РїРѕР»РµР·РЅС‹Р№ AI-Р°СЃСЃРёСЃС‚РµРЅС‚. РћС‚РІРµС‡Р°Р№ РўРћР›Р¬РљРћ РІР°Р»РёРґРЅС‹Рј JSON Р±РµР· ```json РѕР±С‘СЂС‚РѕРє.",
        )

        if not text:
            return None

        return self._parse_json(text)

    def _strip_reasoning(self, text: str) -> str:
        """
        РЈР±РёСЂР°РµС‚ thinking-Р±Р»РѕРє reasoning-РјРѕРґРµР»РµР№ (Nemotron Рё РґСЂ.).
        РћРЅРё РїРёС€СѓС‚ РїР»Р°РЅ РЅР° Р°РЅРіР»РёР№СЃРєРѕРј, РїРѕС‚РѕРј РІС‹РґР°СЋС‚ РѕС‚РІРµС‚ РЅР° СЂСѓСЃСЃРєРѕРј.
        Р‘РµСЂС‘Рј РїРѕСЃР»РµРґРЅРёР№ СЃРІСЏР·РЅС‹Р№ Р±Р»РѕРє С‚РµРєСЃС‚Р° РїРѕСЃР»Рµ РїСѓСЃС‚С‹С… СЃС‚СЂРѕРє.
        """
        import re
        # Р•СЃР»Рё РµСЃС‚СЊ С‚РµРі <think>...</think> вЂ” СѓР±РёСЂР°РµРј РµРіРѕ
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

        # Р Р°Р·Р±РёРІР°РµРј РЅР° РїР°СЂР°РіСЂР°С„С‹ Рё Р±РµСЂС‘Рј РїРѕСЃР»РµРґРЅРёР№ Р±РѕР»СЊС€РѕР№ Р±Р»РѕРє РЅР° РєРёСЂРёР»Р»РёС†Рµ
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        cyrillic_blocks = [p for p in paragraphs if re.search(r"[Р°-СЏРђ-РЇС‘РЃ]{10,}", p)]

        if cyrillic_blocks:
            # Р’РѕР·РІСЂР°С‰Р°РµРј РІСЃРµ РєРёСЂРёР»Р»РёС‡РµСЃРєРёРµ РїР°СЂР°РіСЂР°С„С‹ РїРѕРґСЂСЏРґ
            return "\n\n".join(cyrillic_blocks)

        return text

    def _parse_json(self, text: str) -> Optional[dict]:
        """РР·РІР»РµРєР°РµС‚ JSON РёР· С‚РµРєСЃС‚Р°, СѓР±РёСЂР°СЏ markdown-Р±Р»РѕРєРё Рё reasoning РµСЃР»Рё РµСЃС‚СЊ."""
        import re
        # РЈР±РёСЂР°РµРј <think>...</think> Р±Р»РѕРє РµСЃР»Рё РµСЃС‚СЊ
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        # РЈР±РёСЂР°РµРј markdown-РѕР±С‘СЂС‚РєРё
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text).strip()

        # РС‰РµРј РїРµСЂРІС‹Р№ JSON-РѕР±СЉРµРєС‚ (РґР»СЏ reasoning-РјРѕРґРµР»РµР№ РєРѕС‚РѕСЂС‹Рµ РїРёС€СѓС‚ С‚РµРєСЃС‚ РґРѕ/РїРѕСЃР»Рµ)
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            print(f"[LLM] РќРµ СѓРґР°Р»РѕСЃСЊ СЂР°СЃРїР°СЂСЃРёС‚СЊ JSON: {text[:80]}...")
            return None


# в”Ђв”Ђв”Ђ РўРµСЃС‚ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

if __name__ == "__main__":
    client = LLMClient()
    result = client.chat("РћС‚РІРµС‚СЊ РѕРґРЅРёРј СЃР»РѕРІРѕРј: Р РђР‘РћРўРђР•Рў")
    print("РћС‚РІРµС‚:", result)
