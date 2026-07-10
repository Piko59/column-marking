"""Sınıflandırma hattı (pipeline).

Akış (LangGraph benzeri, sade Python):
  1. Kural katmanı: önek çözümü + sözlük ipuçları — LLM'e yalnızca İPUCU olarak gider,
     asıl açılım çıkarımını LLM kendisi yapar (çıktıdaki "acilim" alanı)
  2. Aşama 1 — Toplu sınıflandırma: tablo bazlı gruplar, tek prompt'ta 7 kategori, çok etiketli
  3. Aşama 2 — Hakem: güveni JUDGE_THRESHOLD altındaki kolonlar tek tek yeniden değerlendirilir
  (Önbellek varsayılan olarak KAPALI — her sorgu yeniden değerlendirilir; USE_CACHE=1 ile açılır)
"""

import asyncio
import hashlib
import json
import os
import threading

import config

from . import llm, prompts, rules
from .categories import CATEGORIES, CATEGORY_PRIORITY

# classify_rows(mode=...) — bkz. fonksiyon docstring'i.
VALID_MODES = ("name_only", "content_only", "name_content")


def _anonymize(kind: str, value: str) -> str:
    """content_only modunda isim sinyalini tamamen yok eder: deterministik ama
    anlamsız bir token üretir (aynı girdi her zaman aynı tokene düşer, ama tokenden
    orijinal ada geri gidilemez)."""
    if not value:
        return value
    digest = hashlib.sha256(f"{kind}:{value}".encode("utf-8")).hexdigest()[:8]
    return f"{kind}_{digest}"

# --- Önbellek ----------------------------------------------------------------

_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()
_cache_loaded = False


def _cache_key(row: dict) -> str:
    # Model adı + prompt hash'i anahtarın parçası: model veya prompt değişince eski
    # kararlar otomatik geçersizleşir (aksi hâlde önbellek sessizce bayat kalırdı).
    base = "|".join(
        str(row.get(k, "")).strip().lower()
        for k in ("sema", "tablo", "kolon", "veri_tipi")
    )
    return f"{config.QWEN_MODEL}|{prompts.PROMPT_VERSION}|{base}"


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
        # LLM ana kategori vermediyse/geçersizse, prompt'ta tanımlı öncelik sırasına göre düş
        # (cats[0] her zaman en küçük id'ye düşerdi; bu, "en sıkı kategori kazanır" kuralını çiğniyordu)
        ana = next((c for c in CATEGORY_PRIORITY if c in cats), cats[0])
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


async def _classify_multi_group(table_groups: list[tuple[str, str, list[dict]]]) -> list[dict]:
    """Aşama 1 (çoklu tablo): birden fazla KÜÇÜK tabloyu tek çağrıda sınıflandırır.

    Gecikme büyük ölçüde çağrı başına sabit bir yükten (modelin "düşünme" süresi)
    geliyor, kolon sayısından değil; küçük tabloları BATCH_SIZE'a kadar birleştirmek
    çağrı sayısını azaltıp toplam süreyi düşürür. Her tablo kendi ŞEMA/TABLO
    bölümünde ayrı verildiği için doğruluk etkilenmez (bkz. prompts.build_multi_table_prompt).
    """
    all_cols = [c for _, _, cols in table_groups for c in cols]
    user_prompt = prompts.build_multi_table_prompt(table_groups)
    try:
        raw = await llm.chat(prompts.SYSTEM_PROMPT, user_prompt)
        parsed = llm.extract_json(raw)
        if isinstance(parsed, dict):
            parsed = [parsed]
        if not isinstance(parsed, list):
            raise ValueError("JSON dizisi bekleniyordu")
    except Exception as e:
        return [_error_result(c["kolon"], str(e)) for c in all_cols]

    # Öncelik: (tablo, kolon) eşleşmesi (model "tablo" alanını doldurduysa — isim
    # çakışmalarını bile doğru ayırır) → yalnız kolon adı (kullanılmamış ilk aday) → sıra.
    by_table_name: dict[tuple[str, str], dict] = {}
    by_name: dict[str, list[dict]] = {}
    for p in parsed:
        if not isinstance(p, dict):
            continue
        name_key = str(p.get("kolon", "")).strip().lower()
        by_name.setdefault(name_key, []).append(p)
        tbl_key = str(p.get("tablo", "")).strip().lower()
        if tbl_key:
            by_table_name.setdefault((tbl_key, name_key), p)

    used: set[int] = set()
    results = []
    i = 0
    for schema, table, cols in table_groups:
        tbl_key = (table or "").strip().lower()
        for c in cols:
            name_key = c["kolon"].strip().lower()
            p = by_table_name.get((tbl_key, name_key))
            if p is None:
                p = next((cand for cand in by_name.get(name_key, []) if id(cand) not in used), None)
            if p is None and i < len(parsed) and isinstance(parsed[i], dict):
                p = parsed[i]
            if p is None:
                results.append(_error_result(c["kolon"], "LLM bu kolon için sonuç döndürmedi"))
            else:
                used.add(id(p))
                results.append(_sanitize(p, c["kolon"], "llm"))
            i += 1
    return results


def _pack_into_superbatches(
    pending: dict[tuple[str, str], list[tuple[int, dict]]], batch_size: int
) -> list[list[tuple[tuple[str, str], list[tuple[int, dict]]]]]:
    """Küçük tablo gruplarını, toplam kolon sayısı batch_size'ı aşmayacak şekilde tek
    "süper-batch"ta birleştirir (çağrı sayısını azaltmak için). Tek başına batch_size'ı
    aşan bir grup, eski davranışla aynı şekilde kendi içinde ayrıca parçalanır — her
    parça kendi süper-batch'i olur (tek tablo, birleştirme yok)."""
    superbatches: list[list[tuple[tuple[str, str], list[tuple[int, dict]]]]] = []
    current: list[tuple[tuple[str, str], list[tuple[int, dict]]]] = []
    current_size = 0
    for group_key, items in pending.items():
        if len(items) > batch_size:
            if current:
                superbatches.append(current)
                current, current_size = [], 0
            for start in range(0, len(items), batch_size):
                superbatches.append([(group_key, items[start : start + batch_size])])
            continue
        if current_size + len(items) > batch_size:
            superbatches.append(current)
            current, current_size = [], 0
        current.append((group_key, items))
        current_size += len(items)
    if current:
        superbatches.append(current)
    return superbatches


async def _judge(schema: str, table: str, col: dict, first_pass: dict) -> dict:
    """Aşama 2: düşük güvenli kolon için hakem geçişi."""
    try:
        # temperature verilmez: config.LLM_TEMPERATURE'a düşer (varsayılan 0 —
        # tekrarlanabilirlik için birincil sınıflandırma ile aynı deterministik ayar)
        raw = await llm.chat(
            prompts.JUDGE_SYSTEM_PROMPT,
            prompts.build_judge_prompt(schema, table, col, first_pass),
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

async def classify_rows(
    rows: list[dict], use_judge: bool = True, mode: str = "name_content"
) -> list[dict]:
    """Satır listesini sınıflandırır; giriş sırasıyla aynı sırada sonuç döndürür.

    rows: [{sema, tablo, kolon, veri_tipi, uzunluk, nullable, pk, ornek_degerler?}, ...]
    mode: "name_content" (varsayılan/üretim) — isim + varsa (maskeli) örnek değerler.
          "name_only"    — yalnız isim/tip/PK; örnek değerler verilse bile gönderilmez.
          "content_only" — kolon/tablo/şema adı anonimleştirilir (isim sinyali sıfırlanır);
                            yalnız örnek değerler + tip/uzunluk/PK üzerinden sınıflandırma
                            zorlanır. Bu üç mod, "isimden mi anlıyoruz, içerikten mi, yoksa
                            ikisi birden mi" sorusunu ölçmek için var (bkz. benchmark).
    """
    if mode not in VALID_MODES:
        raise ValueError(f"Geçersiz mode: {mode!r}; beklenen: {VALID_MODES}")
    # Önbellek yalnız üretim modunda (name_content) kullanılır: benchmark modları
    # kasıtlı olarak isim/içerik sinyalini kısıtlar, bu yüzden her zaman taze koşar.
    if config.USE_CACHE and mode == "name_content":
        _load_cache()
    results: list[dict | None] = [None] * len(rows)

    # 1-2: kural analizi + önbellek
    pending: dict[tuple[str, str], list[tuple[int, dict]]] = {}
    for idx, row in enumerate(rows):
        if config.USE_CACHE and mode == "name_content":
            cached = _cache.get(_cache_key(row))
            if cached:
                results[idx] = {**cached, "kaynak": "cache"}
                continue
        kolon_name = row.get("kolon", "")
        tablo_name = row.get("tablo", "")
        sema_name = row.get("sema", "")
        samples = row.get("ornek_degerler") or []
        if mode == "content_only":
            kolon_name = _anonymize("col", kolon_name)
            tablo_name = _anonymize("tbl", tablo_name)
            sema_name = _anonymize("sch", sema_name)
        elif mode == "name_only":
            samples = []
        analysis = rules.analyze_column(kolon_name, tablo_name)
        col = {
            **row, "kolon": kolon_name, "tablo": tablo_name, "sema": sema_name,
            "ornek_degerler": samples, "note": analysis["note"], "hints": analysis["hints"],
        }
        group_key = (str(sema_name), str(tablo_name))
        pending.setdefault(group_key, []).append((idx, col))

    # 3: tablo bazlı toplu sınıflandırma. Küçük tabloları BATCH_SIZE sınırına kadar TEK
    # çağrıda birleştiriyoruz (süper-batch) — gecikme büyük ölçüde çağrı başına sabit bir
    # "düşünme" yükünden geliyor, kolon sayısından değil; çağrı sayısını azaltmak en büyük
    # kazanç. Gerçek eşzamanlılık sınırı artık burada değil, llm._get_semaphore()'da
    # (config.LLM_CONCURRENCY) — merkezi olması gerekiyor çünkü scorer.py modları da
    # paralel çalıştırıyor; dağınık yerel semaforlar toplamda kontrolsüz büyürdü.
    superbatches = _pack_into_superbatches(pending, config.BATCH_SIZE)

    async def process_superbatch(sb: list[tuple[tuple[str, str], list[tuple[int, dict]]]]):
        if len(sb) == 1:
            (schema, table), chunk = sb[0]
            cols = [c for _, c in chunk]
            group_results = await _classify_group(schema, table, cols)
        else:
            table_groups = [(gk[0], gk[1], [c for _, c in chunk]) for gk, chunk in sb]
            group_results = await _classify_multi_group(table_groups)
            chunk = [pair for _, items in sb for pair in items]

        # 4: hakem geçişi — yalnızca gerçekten kararsız kolonlar; modelin bilinçli olarak
        # "teknik" işaretledikleri hakeme gitmez (hız için kritik)
        if use_judge:
            judge_tasks = []
            for j, res in enumerate(group_results):
                if (res["kaynak"] == "llm" and res["guven"] < config.JUDGE_THRESHOLD
                        and not res["teknik"]):
                    _, col = chunk[j]
                    judge_tasks.append((j, _judge(str(col.get("sema", "")), str(col.get("tablo", "")), col, res)))
            if judge_tasks:
                judged = await asyncio.gather(*(t for _, t in judge_tasks))
                for (j, _), new_res in zip(judge_tasks, judged):
                    group_results[j] = new_res

        for (idx, col), res in zip(chunk, group_results):
            results[idx] = res
            if config.USE_CACHE and mode == "name_content" and res["kaynak"] != "hata":
                with _cache_lock:
                    _cache[_cache_key(rows[idx])] = {
                        k: v for k, v in res.items() if k != "kaynak"
                    } | {"kaynak_orj": res["kaynak"]}

    await asyncio.gather(*(process_superbatch(sb) for sb in superbatches))
    if config.USE_CACHE and mode == "name_content" and pending:
        _save_cache()

    return [r or _error_result(rows[i].get("kolon", "?"), "işlenemedi") for i, r in enumerate(results)]
