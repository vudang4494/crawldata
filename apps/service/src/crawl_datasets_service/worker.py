"""arq worker (§1, P1) — jobs crawl/build/integrate chạy pipeline stage.

Task nhận payload JSON từ FastAPI enqueue (main.py). Pipeline sync →
`asyncio.to_thread` để không block event-loop worker. Redis từ config §9.3
`service.redis_url` — thiếu config → fail loudly khi worker start (fail-closed).

Chạy worker: `arq crawl_datasets_service.worker.WorkerSettings`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from arq.connections import RedisSettings
from crawl_datasets_common.settings import load_settings


def _run_crawl(payload: dict[str, Any]) -> dict[str, Any]:
    from crawl_datasets_crawler.pipeline import run

    stats = run(
        list(payload["seeds"]), Path(payload.get("out", "data")), load_settings()
    )
    return {
        "seen": stats.seen,
        "fetched": stats.fetched,
        "escalated": stats.escalated,
        "dropped": dict(stats.dropped),
    }


def _run_build(payload: dict[str, Any]) -> dict[str, Any]:
    from crawl_datasets_builder.pipeline import run

    stats = run(
        Path(payload["clean_path"]), Path(payload.get("out", "data")), load_settings()
    )
    return {"seen": stats.seen, "built": stats.built, "dropped": dict(stats.dropped)}


def _run_integrate(payload: dict[str, Any]) -> dict[str, Any]:
    from crawl_datasets_integrator.pipeline import run

    stats = run(
        Path(payload["base_dataset"]),
        Path(payload["new_dataset"]),
        Path(payload.get("out", "data")),
        load_settings(),
    )
    return {
        "base": stats.base,
        "new": stats.new,
        "removed_dup": stats.removed_dup,
        "final": stats.final,
    }


async def crawl_job(ctx: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(_run_crawl, payload)


async def build_job(ctx: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(_run_build, payload)


async def integrate_job(ctx: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(_run_integrate, payload)


def _run_plan(payload: dict[str, Any]) -> dict[str, Any]:
    from crawl_datasets_agent.plan import DatasetPlan
    from crawl_datasets_agent.run_plan import execute_plan

    plan = DatasetPlan(**payload["plan"])
    return execute_plan(plan, load_settings(), Path(payload.get("out", "data/agent")))


async def plan_job(ctx: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """§14 — chạy DatasetPlan đã duyệt: S1→S5 dưới out_root."""
    return await asyncio.to_thread(_run_plan, payload)


_service = load_settings().service


class WorkerSettings:
    """arq entrypoint — tên function phải khớp chuỗi enqueue_job() ở main.py."""

    functions = [crawl_job, build_job, integrate_job, plan_job]
    redis_settings = RedisSettings.from_dsn(_service.redis_url)
    max_jobs = _service.max_jobs
