"""Benchmark koşu geçmişinin kalıcı kaydı.

Düz JSON dosyası deseni: veritabanı bağımlılığı eklemeden basit ve denetlenebilir.

Düzen:
  benchmark_runs/index.json   — hafif özet listesi (liste ekranı hızlı yüklensin diye)
  benchmark_runs/{run_id}.json — bir koşunun tam sonucu (detay satırları dahil)
"""

import json
import os
import threading
import uuid
from datetime import datetime, timezone

RUNS_DIR = "benchmark_runs"
INDEX_FILE = os.path.join(RUNS_DIR, "index.json")

_lock = threading.Lock()


def _ensure_dir() -> None:
    os.makedirs(RUNS_DIR, exist_ok=True)


def _read_index() -> list[dict]:
    if not os.path.exists(INDEX_FILE):
        return []
    try:
        with open(INDEX_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _write_index(entries: list[dict]) -> None:
    _ensure_dir()
    tmp = INDEX_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    os.replace(tmp, INDEX_FILE)


def new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:6]}"


def save_run(run_id: str, meta: dict, result: dict) -> None:
    """Tam sonucu {run_id}.json'a, özetini index.json'a yazar."""
    _ensure_dir()
    full = {**meta, "result": result}
    with open(os.path.join(RUNS_DIR, f"{run_id}.json"), "w", encoding="utf-8") as f:
        json.dump(full, f, ensure_ascii=False, indent=2)

    summary_per_mode = {
        mode: data["overall"] for mode, data in result.get("per_mode", {}).items()
    }
    entry = {
        **meta,
        "summary": {"per_mode": summary_per_mode, "pairing": result.get("pairing", {})},
    }
    with _lock:
        entries = [e for e in _read_index() if e.get("run_id") != run_id]
        entries.append(entry)
        entries.sort(key=lambda e: e.get("started_at", ""), reverse=True)
        _write_index(entries)


def list_runs(limit: int = 50) -> list[dict]:
    return _read_index()[:limit]


def get_run(run_id: str) -> dict | None:
    path = os.path.join(RUNS_DIR, f"{run_id}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def delete_run(run_id: str) -> bool:
    path = os.path.join(RUNS_DIR, f"{run_id}.json")
    existed = os.path.exists(path)
    if existed:
        os.remove(path)
    with _lock:
        entries = [e for e in _read_index() if e.get("run_id") != run_id]
        _write_index(entries)
    return existed
