"""OpenAI uyumlu chat-completions istemcisi (vLLM / Ollama / kurum içi gateway).

Uç değişikliği: yalnızca LLM_BASE_URL, LLM_MODEL ve LLM_API_KEY ortam değişkenlerini
değiştirin; OpenAI-uyumlu her sağlayıcı aynı /chat/completions arayüzünü sunar.
"""

import asyncio
import json
import re

import httpx

import config

_client: httpx.AsyncClient | None = None
_concurrency_sem: asyncio.Semaphore | None = None
_bound_loop: asyncio.AbstractEventLoop | None = None


def _ensure_loop_bound() -> None:
    """İstemci ve semafor, oluşturuldukları event loop'a bağlıdır. Sunucu tek loop
    kullanır ama bir script art arda asyncio.run() çağırırsa (her biri yeni loop)
    eski nesneler "attached to a different loop" ile patlar — loop değiştiyse ikisini
    de sıfırla ki ilk kullanımda yeni loop'ta yeniden kurulsunlar."""
    global _client, _concurrency_sem, _bound_loop
    loop = asyncio.get_running_loop()
    if _bound_loop is not loop:
        _client = None
        _concurrency_sem = None
        _bound_loop = loop


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=config.LLM_BASE_URL,
            headers={
                "Authorization": f"Bearer {config.LLM_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=config.LLM_TIMEOUT,
            # Kurum içi uçların sertifikası (kurum CA'sı / self-signed) varsayılan güven
            # deposunda yoktur; LLM_VERIFY_SSL=0 doğrulamayı kapatır (izole kurum ağı).
            verify=config.LLM_VERIFY_SSL,
        )
    return _client


def _get_semaphore() -> asyncio.Semaphore:
    """Süreç genelinde TEK, merkezi eşzamanlılık sınırı (config.LLM_CONCURRENCY).

    Çağıran taraf (pipeline.classify_rows) tablo grupları arasında, çağıranın çağıranı
    (benchmark.scorer) da modlar arasında paralellik uyguluyor; bu iki eksen çarpınca
    dağınık yerel semaforlar toplam eşzamanlı istek sayısını kontrolsüz büyütür. Tek
    doğruluk kaynağı burası olsun diye lazy oluşturuluyor (ilk kullanımda çalışan event
    loop'a bağlanır; loop değişirse _ensure_loop_bound yeniden kurar).
    """
    global _concurrency_sem
    if _concurrency_sem is None:
        _concurrency_sem = asyncio.Semaphore(config.LLM_CONCURRENCY)
    return _concurrency_sem


async def chat(
    system: str, user: str, temperature: float | None = None,
    reasoning_effort: str | None = None,
) -> str:
    """Tek chat çağrısı; geçici hatalarda üstel bekleme ile yeniden dener.

    Tekrarlanabilirlik için varsayılan temperature=0 ve (sağlayıcı destekliyorsa) sabit
    "seed" gönderilir — aynı girdiye aynı çıktı denetim/benchmark için önemlidir.
    reasoning_effort verilirse config.REASONING_EFFORT'u bu çağrı için ezer (tekil
    sorgunun derin analiz modu bunu "high" ile çağırır; toplu koşu varsayılanda kalır).
    """
    _ensure_loop_bound()
    payload = {
        "model": config.LLM_MODEL,
        "temperature": config.LLM_TEMPERATURE if temperature is None else temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    effort = reasoning_effort or config.REASONING_EFFORT
    if effort in ("low", "medium", "high"):
        payload["reasoning"] = {"effort": effort}
    if config.LLM_SEED is not None:
        payload["seed"] = config.LLM_SEED
    # Sağlayıcı bu opsiyonel alanlardan birini desteklemiyorsa 400 döner; sırayla
    # çıkarıp aynı denemede tekrar dener (deneme bütçesini tüketmeden).
    optional_keys = [k for k in ("reasoning", "seed") if k in payload]

    last_err: Exception | None = None
    for attempt in range(config.LLM_MAX_RETRIES):
        try:
            # Semafor yalnız gerçek istek(ler) sırasında tutulur; üstel bekleme
            # (aşağıdaki sleep) sırasında bırakılır ki bekleyen başka çağrılar ilerleyebilsin.
            async with _get_semaphore():
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
