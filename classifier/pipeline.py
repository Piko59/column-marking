"""Sınıflandırma hattı (pipeline).

Akış (LangGraph benzeri, sade Python):
  1. Kural katmanı: önek çözümü + sözlük ipuçları — LLM'e yalnızca İPUCU olarak gider,
     asıl açılım çıkarımını LLM kendisi yapar (çıktıdaki "acilim" alanı)
  2. Aşama 1 — Toplu sınıflandırma: tablo bazlı gruplar, tek prompt'ta 7 kategori, çok etiketli
  3. Aşama 2 — Hakem: güveni JUDGE_THRESHOLD altındaki kolonlar tek tek yeniden değerlendirilir
  (Önbellek varsayılan olarak KAPALI — her sorgu yeniden değerlendirilir; USE_CACHE=1 ile açılır)
"""

import asyncio
import json
import os
import threading

import config

from . import llm, prompts, rules
from .categories import CATEGORIES

# --- Önbellek ----------------------------------------------------------------

_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()
_cache_loaded = False


def _cache_key(row: dict) -> str:
    return "|".join(
        str(row.get(k, "")).strip().lower()
        for k in ("sema", "tablo", "kolon", "veri_tipi")
    )


def _load_cache() -> None:
    global _cache_loaded
    if _cache_loaded:
        return
    _cache_loaded = True
    if os.path.exists(config.CACHE_FILE):
        try:
            with open(config.CACHE_FILE, encoding="utf-8") as f:
                _cache.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass


def _save_cache() -> None:
    with _cache_lock:
        tmp = config.CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_cache, f, ensure_ascii=False)
        os.replace(tmp, config.CACHE_FILE)


# --- Sonuç doğrulama ---------------------------------------------------------

def _sanitize(result: dict, column_name: str, source: str) -> dict:
    cats = result.get("olasi_kategoriler") or result.get("kategoriler") or []
    if not isinstance(cats, list):
        cats = []
    cats = sorted({int(c) for c in cats if str(c).isdigit() and int(c) in CATEGORIES})
    # Kategori 2 her zaman 1'i de içerir
    if 2 in cats and 1 not in cats:
        cats.insert(0, 1)
    # Tek ana kategori; geçersizse olası listeden ilkine düş
    ana = result.get("ana_kategori")
    ana = int(ana) if str(ana).isdigit() and int(ana) in CATEGORIES else None
    if ana is None and cats:
        ana = cats[0]
    if ana is not None and ana not in cats:
        cats = sorted(cats + [ana])
    try:
        conf = max(0.0, min(1.0, float(result.get("guven", 0))))
    except (TypeError, ValueError):
        conf = 0.0
    acilim = result.get("acilim")
    if acilim in (None, "null", "None"):
        acilim = ""
    return {
        "kolon": column_name,
        "acilim": str(acilim)[:200],
        "kategoriler": cats,
        "kategori_adlari": [CATEGORIES[c] for c in cats],
        "ana_kategori": ana,
        "ana_kategori_adi": CATEGORIES.get(ana, ""),
        "teknik": bool(result.get("teknik")),
        "guven": round(conf, 2),
        "gerekce": str(result.get("gerekce") or "")[:500],
        "kaynak": source,  # "llm" | "llm+hakem" | "cache" | "hata"
    }


def _error_result(column_name: str, msg: str) -> dict:
    return {
        "kolon": column_name, "acilim": "", "kategoriler": [], "kategori_adlari": [],
        "ana_kategori": None, "ana_kategori_adi": "", "teknik": False,
        "guven": 0.0, "gerekce": f"Hata: {msg}", "kaynak": "hata",
    }


# --- Aşamalar ----------------------------------------------------------------

async def _classify_group(schema: str, table: str, cols: list[dict]) -> list[dict]:
    """Aşama 1: bir tablonun kolon grubunu tek çağrıda sınıflandırır."""
    user_prompt = prompts.build_batch_prompt(schema, table, cols)
    try:
        raw = await llm.chat(prompts.SYSTEM_PROMPT, user_prompt)
        parsed = llm.extract_json(raw)
        if isinstance(parsed, dict):
            parsed = [parsed]
        if not isinstance(parsed, list):
            raise ValueError("JSON dizisi bekleniyordu")
    except Exception as e:
        return [_error_result(c["kolon"], str(e)) for c in cols]

    # Ada göre eşle; ad eşleşmezse sıraya güven
    by_name = {
        str(p.get("kolon", "")).strip().lower(): p
        for p in parsed if isinstance(p, dict)
    }
    results = []
    for i, c in enumerate(cols):
        p = by_name.get(c["kolon"].strip().lower())
        if p is None and i < len(parsed) and isinstance(parsed[i], dict):
            p = parsed[i]
        if p is None:
            results.append(_error_result(c["kolon"], "LLM bu kolon için sonuç döndürmedi"))
        else:
            results.append(_sanitize(p, c["kolon"], "llm"))
    return results


async def _judge(schema: str, table: str, col: dict, first_pass: dict) -> dict:
    """Aşama 2: düşük güvenli kolon için hakem geçişi."""
    try:
        raw = await llm.chat(
            prompts.JUDGE_SYSTEM_PROMPT,
            prompts.build_judge_prompt(schema, table, col, first_pass),
            temperature=0.2,
        )
        parsed = llm.extract_json(raw)
        if isinstance(parsed, list):
            parsed = parsed[-1] if parsed else {}
        result = _sanitize(parsed, col["kolon"], "llm+hakem")
        result["ilk_deneme"] = {
            "kategoriler": first_pass["kategoriler"], "guven": first_pass["guven"],
        }
        return result
    except Exception:
        return first_pass  # hakem başarısızsa ilk sonucu koru


# --- Ana giriş noktası -------------------------------------------------------

async def classify_rows(rows: list[dict], use_judge: bool = True) -> list[dict]:
    """Satır listesini sınıflandırır; giriş sırasıyla aynı sırada sonuç döndürür.

    rows: [{sema, tablo, kolon, veri_tipi, uzunluk, nullable, pk}, ...]
    """
    if config.USE_CACHE:
        _load_cache()
    results: list[dict | None] = [None] * len(rows)

    # 1-2: kural analizi + önbellek (önbellek varsayılan olarak KAPALI; config.USE_CACHE)
    pending: dict[tuple[str, str], list[tuple[int, dict]]] = {}
    for idx, row in enumerate(rows):
        if config.USE_CACHE:
            cached = _cache.get(_cache_key(row))
            if cached:
                results[idx] = {**cached, "kaynak": "cache"}
                continue
        analysis = rules.analyze_column(row.get("kolon", ""), row.get("tablo", ""))
        col = {**row, "note": analysis["note"], "hints": analysis["hints"]}
        group_key = (str(row.get("sema", "")), str(row.get("tablo", "")))
        pending.setdefault(group_key, []).append((idx, col))

    # 3: tablo bazlı toplu sınıflandırma (gruplar paralel, grup içi tek çağrı)
    async def process_group(group_key: tuple[str, str], items: list[tuple[int, dict]]):
        schema, table = group_key
        for start in range(0, len(items), config.BATCH_SIZE):
            chunk = items[start : start + config.BATCH_SIZE]
            cols = [c for _, c in chunk]
            group_results = await _classify_group(schema, table, cols)
            # 4: hakem geçişi — yalnızca gerçekten kararsız kolonlar; modelin bilinçli
            # olarak "teknik" işaretledikleri hakeme gitmez (hız için kritik)
            if use_judge:
                judge_tasks = []
                for j, res in enumerate(group_results):
                    if (res["kaynak"] == "llm" and res["guven"] < config.JUDGE_THRESHOLD
                            and not res["teknik"]):
                        judge_tasks.append((j, _judge(schema, table, cols[j], res)))
                if judge_tasks:
                    judged = await asyncio.gather(*(t for _, t in judge_tasks))
                    for (j, _), new_res in zip(judge_tasks, judged):
                        group_results[j] = new_res
            for (idx, col), res in zip(chunk, group_results):
                results[idx] = res
                if config.USE_CACHE and res["kaynak"] != "hata":
                    with _cache_lock:
                        _cache[_cache_key(rows[idx])] = {
                            k: v for k, v in res.items() if k != "kaynak"
                        } | {"kaynak_orj": res["kaynak"]}

    sem = asyncio.Semaphore(4)  # aynı anda en fazla 4 grup

    async def bounded(gk, items):
        async with sem:
            await process_group(gk, items)

    await asyncio.gather(*(bounded(gk, items) for gk, items in pending.items()))
    if config.USE_CACHE and pending:
        _save_cache()

    return [r or _error_result(rows[i].get("kolon", "?"), "işlenemedi") for i, r in enumerate(results)]
