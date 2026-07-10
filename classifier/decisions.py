"""İnsan inceleme kararlarının kalıcı sözlüğü (karar sözlüğü).

Üç eylem:
  onayla — LLM sonucu insan tarafından doğrulandı; aynı imza bir daha LLM'e gitmez,
           onaylanan kategoriler sözlükten döner (kaynak="sozluk").
  duzelt — insan kategorileri düzeltti; düzeltilmiş hâli sözlükten döner.
  notr   — "incelendi ama etkisiz": yalnız denetim kaydı tutulur; sınıflandırmaya,
           sözlük aramasına ve dışa aktarılan kategorilere HİÇBİR etkisi yoktur.
           (Bilirkişi olmayan bir gözden geçiren, sonucu etkilemeden "gördüm"
           diyebilsin diye vardır.)

Anahtar bilinçli olarak (kolon adı, veri tipi) — tablo DEĞİL: bankada aynı kolon adı
yüzlerce tabloda tekrarlanır; sözlüğün kaldıracı bu genellemededir. Kararın hangi
şema/tabloda verildiği yine de kayıtta saklanır (denetim izi). Depolama düzeni
classification_cache.json ile aynı desendir: düz JSON, atomik yazma.
"""

import json
import os
import threading
from datetime import datetime, timezone

import config

from .categories import CATEGORIES
from .rules import split_tokens

VALID_ACTIONS = ("onayla", "duzelt", "notr")

_decisions: dict[str, dict] = {}
_loaded = False
_lock = threading.Lock()


def decision_key(row: dict) -> str:
    return "|".join(
        str(row.get(k, "")).strip().lower() for k in ("kolon", "veri_tipi")
    )


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    if os.path.exists(config.DECISIONS_FILE):
        try:
            with open(config.DECISIONS_FILE, encoding="utf-8") as f:
                _decisions.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass


def _save() -> None:
    tmp = config.DECISIONS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_decisions, f, ensure_ascii=False, indent=1)
    os.replace(tmp, config.DECISIONS_FILE)


def save_decision(
    row: dict,
    action: str,
    ana_kategori: int | None = None,
    kategoriler: list[int] | None = None,
    orijinal: dict | None = None,
) -> dict:
    """Bir inceleme kararını kaydeder ve saklanan kaydı döndürür.

    onayla/duzelt için ana_kategori + kategoriler zorunludur (onaylamada frontend
    LLM'in mevcut sonucunu gönderir). notr için kategori bilgisi saklanmaz — nötr
    kaydın tek amacı "incelendi" bilgisidir.
    """
    if action not in VALID_ACTIONS:
        raise ValueError(f"Geçersiz eylem: {action!r}; beklenen: {VALID_ACTIONS}")

    record: dict = {
        "action": action,
        "kolon": row.get("kolon", ""),
        "veri_tipi": row.get("veri_tipi", ""),
        "karar_baglami": {"sema": row.get("sema", ""), "tablo": row.get("tablo", "")},
        "tarih": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if action in ("onayla", "duzelt"):
        cats = sorted({int(c) for c in (kategoriler or []) if int(c) in CATEGORIES})
        if ana_kategori is None or int(ana_kategori) not in CATEGORIES:
            raise ValueError("onayla/duzelt için geçerli bir ana_kategori gerekir")
        ana = int(ana_kategori)
        if ana not in cats:
            cats = sorted(cats + [ana])
        record["ana_kategori"] = ana
        record["kategoriler"] = cats
        if orijinal is not None:
            record["orijinal"] = {
                "ana_kategori": orijinal.get("ana_kategori"),
                "kategoriler": orijinal.get("kategoriler"),
                "guven": orijinal.get("guven"),
            }

    with _lock:
        _load()
        _decisions[decision_key(row)] = record
        _save()
    return record


def lookup(row: dict) -> dict | None:
    """Sınıflandırmayı etkileyen (onayla/duzelt) kaydı döndürür; notr HİÇBİR ZAMAN
    dönmez — nötr kararın sınıflandırmaya etkisi yoktur."""
    _load()
    rec = _decisions.get(decision_key(row))
    if rec and rec["action"] in ("onayla", "duzelt"):
        return rec
    return None


def as_result(rec: dict, column_name: str) -> dict:
    """Sözlük kaydını, pipeline sonuç şemasıyla birebir aynı biçime çevirir."""
    cats = rec.get("kategoriler", [])
    ana = rec.get("ana_kategori")
    label = "onaylandı" if rec["action"] == "onayla" else "insan tarafından düzeltildi"
    return {
        "kolon": column_name,
        "acilim": "",
        "kategoriler": cats,
        "kategori_adlari": [CATEGORIES[c] for c in cats],
        "ana_kategori": ana,
        "ana_kategori_adi": CATEGORIES.get(ana, ""),
        "teknik": False,
        "guven": 1.0,
        "gerekce": f"Karar sözlüğü: bu kolon imzası {rec.get('tarih', '?')} tarihinde {label}.",
        "kaynak": "sozluk",
    }


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = a & b
    if not inter:
        return 0.0
    return len(inter) / len(a | b)


def similar_decisions(
    cols: list[dict], k: int | None = None, min_sim: float | None = None
) -> list[dict]:
    """Verilen kolon grubuna en benzer, sınıflandırmayı etkileyen (onayla/duzelt)
    kararları döndürür — few-shot örnek havuzu.

    Benzerlik: kolon adlarının token kümesi Jaccard'ı (örn. mhIbanNo={mh,iban,no} ile
    klaIbanNo={kla,iban,no} → 0.5) + veri tipi aynıysa küçük bonus. Skor, karardaki
    kolonun partideki HERHANGİ bir kolona en yüksek benzerliğidir; eşik altındakiler
    hiç dönmez (alakasız örnek modeli saptırır). Nötr kayıtlar havuzda yoktur.

    Prompt bütçesi garantisi: dönen liste her zaman ≤ k — havuz binlerce kayda
    büyüse de çağrı başına örnek maliyeti sabittir.
    """
    k = config.FEWSHOT_K if k is None else k
    threshold = config.FEWSHOT_MIN_SIM if min_sim is None else min_sim
    if k <= 0:
        return []
    _load()
    pool = [r for r in _decisions.values() if r["action"] in ("onayla", "duzelt")]
    if not pool:
        return []
    batch = [
        (set(split_tokens(c.get("kolon", ""))), str(c.get("veri_tipi", "")).strip().lower())
        for c in cols
    ]
    scored: list[tuple[float, dict]] = []
    for rec in pool:
        rec_tokens = set(split_tokens(rec.get("kolon", "")))
        rec_type = str(rec.get("veri_tipi", "")).strip().lower()
        best = 0.0
        for tokens, dtype in batch:
            s = _jaccard(rec_tokens, tokens)
            if s and rec_type and rec_type == dtype:
                s = min(1.0, s + 0.05)
            if s > best:
                best = s
        if best >= threshold:
            scored.append((best, rec))
    scored.sort(key=lambda t: -t[0])
    return [rec for _, rec in scored[:k]]


def stats() -> dict:
    _load()
    counts = {a: 0 for a in VALID_ACTIONS}
    for rec in _decisions.values():
        counts[rec["action"]] = counts.get(rec["action"], 0) + 1
    return {"toplam": len(_decisions), **counts}
