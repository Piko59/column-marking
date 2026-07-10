"""Benchmark koşularını arka planda çalıştıran, bellek-içi iş (job) takibi.

Tek süreçli/tek worker'lı bir uvicorn dağıtımı varsayılır — proje zaten dosya tabanlı,
tek-worker bir mimariye sahip (classification_cache.json ile aynı varsayım). Bir koşu
112 satır × birden çok mod içerdiği için (çok sayıda LLM çağrısı) dakikalar sürebilir;
bu yüzden istek-yanıt döngüsünü bloklamadan arka planda çalıştırıp ilerlemeyi
UI'ın periyodik olarak sorgulayabileceği bir sözlükte tutuyoruz.
"""

import asyncio
import time
from datetime import datetime, timezone

import config

from . import scorer, store

_jobs: dict[str, dict] = {}


async def _run(job_id: str, modes: list[str], use_judge: bool) -> None:
    async def on_progress(step: int, total: int, mode: str) -> None:
        _jobs[job_id]["progress"] = {"step": step, "total": total, "mode": mode}

    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        result = await scorer.run_benchmark(modes=modes, use_judge=use_judge, progress_cb=on_progress)
        elapsed = round(time.monotonic() - started, 1)
        run_id = store.new_run_id()
        meta = {
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": elapsed,
            "modes": modes,
            "use_judge": use_judge,
            "model": config.QWEN_MODEL,
        }
        store.save_run(run_id, meta, result)
        _jobs[job_id] = {**_jobs[job_id], "status": "done", "run_id": run_id}
    except Exception as e:
        _jobs[job_id] = {**_jobs[job_id], "status": "error", "error": str(e)}


def start_job(modes: list[str], use_judge: bool) -> str:
    job_id = store.new_run_id()
    _jobs[job_id] = {
        "status": "running",
        "progress": {"step": 0, "total": len(modes), "mode": None},
        "run_id": None,
        "error": None,
    }
    asyncio.create_task(_run(job_id, modes, use_judge))
    return job_id


def get_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)
