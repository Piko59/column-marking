"""OpenAI uyumlu chat-completions istemcisi (OpenRouter / vLLM / Ollama ile çalışır).

Local modele geçiş: sadece QWEN_BASE_URL ve QWEN_MODEL ortam değişkenlerini değiştirin;
vLLM ve Ollama aynı /chat/completions arayüzünü sunar.
"""

import asyncio
import json
import re

import httpx

import config

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=config.QWEN_BASE_URL,
            headers={
                "Authorization": f"Bearer {config.QWEN_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=config.LLM_TIMEOUT,
        )
    return _client


async def chat(system: str, user: str, temperature: float | None = None) -> str:
    """Tek chat çağrısı; geçici hatalarda üstel bekleme ile yeniden dener."""
    payload = {
        "model": config.QWEN_MODEL,
        "temperature": config.LLM_TEMPERATURE if temperature is None else temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if config.REASONING_EFFORT in ("low", "medium", "high"):
        payload["reasoning"] = {"effort": config.REASONING_EFFORT}
    last_err: Exception | None = None
    for attempt in range(config.LLM_MAX_RETRIES):
        try:
            resp = await _get_client().post("/chat/completions", json=payload)
            if resp.status_code == 400 and "reasoning" in payload:
                # Sağlayıcı reasoning parametresini desteklemiyor; parametresiz dene
                payload.pop("reasoning")
                resp = await _get_client().post("/chat/completions", json=payload)
            if resp.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError("retryable", request=resp.request, response=resp)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"] or ""
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as e:
            last_err = e
            if attempt < config.LLM_MAX_RETRIES - 1:
                await asyncio.sleep(2 ** attempt)
    raise RuntimeError(f"LLM çağrısı {config.LLM_MAX_RETRIES} denemede başarısız: {last_err}")


def extract_json(text: str):
    """LLM çıktısındaki ilk JSON dizisini/nesnesini güvenli biçimde ayıklar."""
    text = re.sub(r"```(?:json)?", "", text).strip()
    # Önce doğrudan dene
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Dengeli ilk [ ... ] veya { ... } bloğunu bul (son satırdan geriye doğru nesne ara)
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        start = text.find(open_ch)
        while start != -1:
            depth = 0
            in_str = False
            escape = False
            for i in range(start, len(text)):
                ch = text[i]
                if escape:
                    escape = False
                    continue
                if ch == "\\":
                    escape = in_str
                    continue
                if ch == '"':
                    in_str = not in_str
                    continue
                if in_str:
                    continue
                if ch == open_ch:
                    depth += 1
                elif ch == close_ch:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start : i + 1])
                        except json.JSONDecodeError:
                            break
            start = text.find(open_ch, start + 1)
    raise ValueError(f"LLM çıktısında geçerli JSON bulunamadı: {text[:300]}")
