"""Benchmark skor motoru.

golden_dataset'i (bkz. benchmark/dataset.py) üç sinyal koşulunda (mode) sınıflandırıcıdan
geçirir ve tahminleri ground truth ile karşılaştırıp çok boyutlu (mode × grup × kategori)
metrikler üretir. Ayrıca "isim bağımlılığı" analizini yapar: aynı içerik, isim
kaldırıldığında (random grup) hâlâ doğru sınıflandırılıyor mu, yoksa yalnızca isimden mi
doğru tahmin ediliyordu?
"""

import asyncio
import math
from collections.abc import Awaitable, Callable

from classifier.pipeline import classify_rows

from . import dataset as ds

DEFAULT_MODES = ["name_only", "content_only", "name_content"]

ProgressCB = Callable[[int, int, str], Awaitable[None]] | None

# Kalibrasyon (ECE) kovaları: modelin bildirdiği güven bu aralıklara bölünür ve her
# kovada "ortalama güven - gerçek doğruluk" farkı ağırlıklı toplanır.
_ECE_BINS = [(0.0, 0.7), (0.7, 0.85), (0.85, 0.93), (0.93, 1.001)]


def _wilson_ci(k: int, n: int, z: float = 1.96) -> list[float] | None:
    """Binom oranı için Wilson %95 güven aralığı — küçük örneklemde nokta tahminin
    (örn. 6/6 = "%100") yanıltıcılığını raporda görünür kılar."""
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round((center - half) / denom, 4), round((center + half) / denom, 4)]


def _calibration(metrics: list[dict]) -> dict:
    """ECE + doğru/yanlış kararlarda ortalama güven. Güvenin hatayı AYIRT EDİP
    edemediğini gösterir: iki ortalama birbirine yakınsa güven eşiğiyle insan
    incelemesi önceliklendirilemez (hakem eşiği dahil)."""
    scored = [(m["confidence"], m["ana_match"]) for m in metrics if not m["error"]]
    if not scored:
        return {"ece": None, "avg_conf_correct": None, "avg_conf_wrong": None}
    ece = 0.0
    for lo, hi in _ECE_BINS:
        grp = [(c, ok) for c, ok in scored if lo <= c < hi]
        if grp:
            acc = sum(ok for _, ok in grp) / len(grp)
            mean_conf = sum(c for c, _ in grp) / len(grp)
            ece += len(grp) / len(scored) * abs(acc - mean_conf)
    correct = [c for c, ok in scored if ok]
    wrong = [c for c, ok in scored if not ok]
    return {
        "ece": round(ece, 4),
        "avg_conf_correct": round(sum(correct) / len(correct), 4) if correct else None,
        "avg_conf_wrong": round(sum(wrong) / len(wrong), 4) if wrong else None,
    }


def _row_metrics(truth: dict, pred: dict) -> dict:
    ana_true = truth["ana_kategori"]
    ana_pred = pred.get("ana_kategori")
    set_true = set(truth["kategoriler"])
    set_pred = set(pred.get("kategoriler") or [])
    tp = len(set_true & set_pred)
    precision = (tp / len(set_pred)) if set_pred else (1.0 if not set_true else 0.0)
    recall = (tp / len(set_true)) if set_true else (1.0 if not set_pred else 0.0)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "ana_match": ana_pred == ana_true,
        "set_precision": precision,
        "set_recall": recall,
        "set_f1": f1,
        "teknik_match": bool(pred.get("teknik")) == bool(truth["teknik"]),
        "confidence": float(pred.get("guven") or 0.0),
        "kaynak": pred.get("kaynak"),
        "error": pred.get("kaynak") == "hata",
    }


def _aggregate(metrics: list[dict]) -> dict:
    n = len(metrics)
    if n == 0:
        return {
            "n": 0, "ana_accuracy": None, "ana_accuracy_ci95": None, "set_precision": None,
            "set_recall": None, "set_f1": None, "teknik_accuracy": None,
            "avg_confidence": None, "error_rate": None, "judge_rate": None,
            "ece": None, "avg_conf_correct": None, "avg_conf_wrong": None,
        }
    ana_correct = sum(m["ana_match"] for m in metrics)
    return {
        "n": n,
        "ana_accuracy": round(ana_correct / n, 4),
        "ana_accuracy_ci95": _wilson_ci(ana_correct, n),
        "set_precision": round(sum(m["set_precision"] for m in metrics) / n, 4),
        "set_recall": round(sum(m["set_recall"] for m in metrics) / n, 4),
        "set_f1": round(sum(m["set_f1"] for m in metrics) / n, 4),
        "teknik_accuracy": round(sum(m["teknik_match"] for m in metrics) / n, 4),
        "avg_confidence": round(sum(m["confidence"] for m in metrics) / n, 4),
        "error_rate": round(sum(m["error"] for m in metrics) / n, 4),
        # startswith: hem kabul edilen ("llm+hakem") hem reddedilen ("llm+hakem_ret")
        # hakem denemeleri sayılır — metrik "hakeme giden kolon oranı"dır, kabul oranı değil.
        "judge_rate": round(sum(1 for m in metrics if str(m["kaynak"]).startswith("llm+hakem")) / n, 4),
        **_calibration(metrics),
    }


def _pairing_analysis(detail_rows: list[dict]) -> dict:
    """Her mode için: aynı kavramın 'named' ve 'random' sürümü aynı ana kategoriyi mi
    buldu? 'name_dependency_rate' — yalnız isim verildiğinde doğru, isim anlamsız
    olduğunda yanlış olan kavramların oranı: modelin gerçek anlayıştan çok isim
    kalıbına dayandığının bir göstergesidir."""
    by_mode: dict[str, dict[str, dict[str, bool]]] = {}
    for d in detail_rows:
        by_mode.setdefault(d["mode"], {}).setdefault(d["concept"], {})[d["group"]] = d["metrics"]["ana_match"]

    result = {}
    for mode, concepts in by_mode.items():
        n = len(concepts)
        both = only_named = only_random = neither = 0
        for g in concepts.values():
            named_ok, random_ok = g.get("named", False), g.get("random", False)
            if named_ok and random_ok:
                both += 1
            elif named_ok and not random_ok:
                only_named += 1
            elif random_ok and not named_ok:
                only_random += 1
            else:
                neither += 1
        result[mode] = {
            "n_concepts": n,
            "both_correct": both,
            "only_named_correct": only_named,
            "only_random_correct": only_random,
            "neither_correct": neither,
            "name_dependency_rate": round(only_named / n, 4) if n else None,
        }
    return result


async def run_benchmark(
    modes: list[str] | None = None,
    use_judge: bool = True,
    progress_cb: ProgressCB = None,
) -> dict:
    """Tam benchmark koşusunu yürütür ve UI'ın gösterebileceği yapılandırılmış sonucu döndürür.

    Modlar birbirinden bağımsız olduğu için (her biri kendi classify_rows çağrısı) paralel
    çalıştırılır — sırayla koşmak toplam süreyi 3 katına çıkarırdı. Gerçek eşzamanlı istek
    sınırı llm._get_semaphore()'da (config.LLM_CONCURRENCY) merkezi olarak uygulanıyor;
    burada ek bir sınır yok, aksi hâlde iki ayrı paralellik ekseni çakışırdı.
    """
    modes = modes or DEFAULT_MODES
    items = ds.iter_dataset_items()
    rows = [it["row"] for it in items]

    completed = 0
    progress_lock = asyncio.Lock()

    async def run_mode(mode: str) -> tuple[str, list[dict]]:
        nonlocal completed
        # use_decisions=False: karar sözlüğü golden veri setiyle örtüşebilir; açık
        # bırakılsa benchmark modelin ham yeteneğini değil, insanın önceden verdiği
        # cevapların sızıntısını ölçerdi (bkz. classify_rows docstring).
        results = await classify_rows(
            rows, use_judge=use_judge, mode=mode, use_decisions=False
        )
        if progress_cb:
            async with progress_lock:
                completed += 1
                await progress_cb(completed, len(modes), mode)
        return mode, results

    mode_results = dict(await asyncio.gather(*(run_mode(m) for m in modes)))

    per_mode: dict[str, dict] = {}
    detail_rows: list[dict] = []
    for mode in modes:
        results = mode_results[mode]
        mode_metrics = []
        for item, pred in zip(items, results):
            m = _row_metrics(item["truth"], pred)
            mode_metrics.append(m)
            detail_rows.append({
                "mode": mode, "id": item["id"], "concept": item["concept"],
                "bucket": item["bucket"], "group": item["group"],
                "truth": item["truth"], "pred": pred, "metrics": m,
            })
        by_group = {
            g: _aggregate([m for it, m in zip(items, mode_metrics) if it["group"] == g])
            for g in ("named", "random")
        }
        by_bucket = {
            b: _aggregate([m for it, m in zip(items, mode_metrics) if it["bucket"] == b])
            for b in ds.BUCKETS
        }
        per_mode[mode] = {
            "overall": _aggregate(mode_metrics),
            "by_group": by_group,
            "by_bucket": by_bucket,
        }

    return {
        "modes": modes,
        "dataset": ds.dataset_summary(),
        "per_mode": per_mode,
        "pairing": _pairing_analysis(detail_rows),
        "detail": detail_rows,
    }
