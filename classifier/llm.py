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
    """Tek chat çağrısı; geçici hatalarda üstel bekleme ile yeniden dener.

    Tekrarlanabilirlik için varsayılan temperature=0 ve (sağlayıcı destekliyorsa) sabit
    "seed" gönderilir — aynı girdiye aynı çıktı denetim/benchmark için önemlidir.
    """
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
    if config.LLM_SEED is not None:
        payload["seed"] = config.LLM_SEED
    # Sağlayıcı bu opsiyonel alanlardan birini desteklemiyorsa 400 döner; sırayla
    # çıkarıp aynı denemede tekrar dener (deneme bütçesini tüketmeden).
    optional_keys = [k for k in ("reasoning", "seed") if k in payload]

    last_err: Exception | None = None
    for attempt in range(config.LLM_MAX_RETRIES):
        try:
            resp = await _get_client().post("/chat/completions", json=payload)
            while resp.status_code == 400 and optional_keys:
                payload.pop(optional_keys.pop(0), None)
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
    """LLM çıktısındaki ilk geçerli JSON dizisini/nesnesini güvenli biçimde ayıklar.

    Metinde hangi açılış parantezi ('[' veya '{') önce geçiyorsa oradan başlar ve iç
    içe [] / {} yuvalamayı ORTAK bir yığınla (stack) izler. Not: eski sürüm önce tüm
    metinde '[' arayıp sonra '{' arıyordu; bu, "gerekçe metni + son satırda
    {"olasi_kategoriler": [...], ...}" biçimindeki hakem çıktılarında dış nesneden
    önce iç içteki [...] dizisini yanlışlıkla eşleştirip döndürüyordu.
    """
    text = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    pairs = {"[": "]", "{": "}"}
    closers = {"]", "}"}
    pos = 0
    while True:
        candidates = [i for ch in pairs if (i := text.find(ch, pos)) != -1]
        if not candidates:
            break
        start = min(candidates)
        stack: list[str] = []
        in_str = False
        escape = False
        end = None
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
            if ch in pairs:
                stack.append(pairs[ch])
            elif ch in closers:
                if not stack or stack[-1] != ch:
                    break  # dengesiz kapanış; bu aday geçersiz
                stack.pop()
                if not stack:
                    end = i
                    break
        if end is not None:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        pos = start + 1
    raise ValueError(f"LLM çıktısında geçerli JSON bulunamadı: {text[:300]}")
