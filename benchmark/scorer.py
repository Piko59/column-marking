"""Benchmark skor motoru.

golden_dataset'i (bkz. benchmark/dataset.py) üç sinyal koşulunda (mode) sınıflandırıcıdan
geçirir ve tahminleri ground truth ile karşılaştırıp çok boyutlu (mode × grup × kategori)
metrikler üretir. Ayrıca "isim bağımlılığı" analizini yapar: aynı içerik, isim
kaldırıldığında (random grup) hâlâ doğru sınıflandırılıyor mu, yoksa yalnızca isimden mi
doğru tahmin ediliyordu?
"""

from collections.abc import Awaitable, Callable

from classifier.pipeline import classify_rows

from . import dataset as ds

DEFAULT_MODES = ["name_only", "content_only", "name_content"]

ProgressCB = Callable[[int, int, str], Awaitable[None]] | None


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
            "n": 0, "ana_accuracy": None, "set_precision": None, "set_recall": None,
            "set_f1": None, "teknik_accuracy": None, "avg_confidence": None,
            "error_rate": None, "judge_rate": None,
        }
    return {
        "n": n,
        "ana_accuracy": round(sum(m["ana_match"] for m in metrics) / n, 4),
        "set_precision": round(sum(m["set_precision"] for m in metrics) / n, 4),
        "set_recall": round(sum(m["set_recall"] for m in metrics) / n, 4),
        "set_f1": round(sum(m["set_f1"] for m in metrics) / n, 4),
        "teknik_accuracy": round(sum(m["teknik_match"] for m in metrics) / n, 4),
        "avg_confidence": round(sum(m["confidence"] for m in metrics) / n, 4),
        "error_rate": round(sum(m["error"] for m in metrics) / n, 4),
        "judge_rate": round(sum(1 for m in metrics if m["kaynak"] == "llm+hakem") / n, 4),
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
    """Tam benchmark koşusunu yürütür ve UI'ın gösterebileceği yapılandırılmış sonucu döndürür."""
    modes = modes or DEFAULT_MODES
    items = ds.iter_dataset_items()
    rows = [it["row"] for it in items]

    per_mode: dict[str, dict] = {}
    detail_rows: list[dict] = []

    for step, mode in enumerate(modes, 1):
        results = await classify_rows(rows, use_judge=use_judge, mode=mode)
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
        if progress_cb:
            await progress_cb(step, len(modes), mode)

    return {
        "modes": modes,
        "dataset": ds.dataset_summary(),
        "per_mode": per_mode,
        "pairing": _pairing_analysis(detail_rows),
        "detail": detail_rows,
    }
