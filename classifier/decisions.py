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


def stats() -> dict:
    _load()
    counts = {a: 0 for a in VALID_ACTIONS}
    for rec in _decisions.values():
        counts[rec["action"]] = counts.get(rec["action"], 0) + 1
    return {"toplam": len(_decisions), **counts}
