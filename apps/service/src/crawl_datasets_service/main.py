"""FastAPI service skeleton (§1, §9.4).

Endpoints (theo spec §1):
  POST /jobs/crawl          {seeds[], depth, render, lang_allow[]}  -> job_id
  GET  /jobs/{id}           -> {stage, shards_done, in/out/dropped, eta}
  POST /datasets/build      {clean_path, format, schema_ver}        -> dataset_id
  POST /datasets/{id}/integrate {base_dataset, mix_ratios, dedup}  -> new_version
  GET  /datasets/{id}/profile -> stats + suggestions
  GET  /metrics             -> Prometheus exposition
  GET  /healthz
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from crawl_datasets_common.observability import configure_logging
from crawl_datasets_common.settings import load_settings
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field


@asynccontextmanager
async def _lifespan(app: FastAPI) -> Any:
    """Lifespan ctx — thay @app.on_event đã deprecated (FastAPI 0.111+, §9.4)."""
    configure_logging()
    yield


app = FastAPI(
    title="crawl-datasets-service",
    version="1.3.0",
    lifespan=_lifespan,
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


# --- Job endpoints (arq workers, §1) -----------------------------------------
# Pool tạo lazy per-process; test inject fake qua `app.state.arq_pool`.
# Redis không chạy → 503 tường minh (fail-closed, không nuốt lỗi).


async def _get_pool(request: Request) -> Any:
    pool = getattr(request.app.state, "arq_pool", None)
    if pool is not None:
        return pool
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(
            RedisSettings.from_dsn(load_settings().service.redis_url)
        )
    except (OSError, ImportError) as exc:
        raise HTTPException(
            status_code=503, detail=f"queue unavailable (Redis/arq): {exc}"
        ) from exc
    request.app.state.arq_pool = pool
    return pool


async def _enqueue(request: Request, func: str, payload: dict[str, Any]) -> JobAck:
    pool = await _get_pool(request)
    job = await pool.enqueue_job(func, payload)
    if job is None:  # arq: job_id trùng đang chạy
        raise HTTPException(status_code=409, detail="duplicate job")
    return JobAck(job_id=job.job_id)


class CrawlJobRequest(BaseModel):
    seeds: list[str]
    depth: int = 3
    render: str = Field(default="auto", pattern="^(auto|http|browser)$")
    lang_allow: list[str] = Field(default_factory=lambda: ["vi", "en"])


class BuildDatasetRequest(BaseModel):
    clean_path: str
    format: str = Field(default="chatml", pattern="^(chatml|sharegpt|alpaca)$")
    schema_ver: str = "1.3.0"


class IntegrateRequest(BaseModel):
    base_dataset: str
    mix_ratios: dict[str, float]
    dedup: str = Field(default="cross", pattern="^(cross|none)$")


class JobAck(BaseModel):
    job_id: str


@app.post("/jobs/crawl", response_model=JobAck)
async def enqueue_crawl(req: CrawlJobRequest, request: Request) -> JobAck:
    """Enqueue crawl job vào arq — worker: `crawl_job` (worker.py)."""
    return await _enqueue(request, "crawl_job", req.model_dump())


@app.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request) -> dict[str, Any]:
    from arq.jobs import Job

    pool = await _get_pool(request)
    status = await Job(job_id, pool).status()
    return {"job_id": job_id, "status": getattr(status, "value", str(status))}


@app.post("/datasets/build", response_model=JobAck)
async def enqueue_build(req: BuildDatasetRequest, request: Request) -> JobAck:
    return await _enqueue(request, "build_job", req.model_dump())


@app.post("/datasets/{dataset_id}/integrate", response_model=JobAck)
async def enqueue_integrate(
    dataset_id: str, req: IntegrateRequest, request: Request
) -> JobAck:
    payload = {"new_dataset": dataset_id, **req.model_dump()}
    return await _enqueue(request, "integrate_job", payload)


@app.get("/datasets/{dataset_id}/profile")
def profile(dataset_id: str) -> dict[str, Any]:
    # TODO(P3): đọc profile_report.json từ dataset/{id}/profile_report.json
    return {"dataset_id": dataset_id, "stats": {}, "suggestions": []}


@app.get("/metrics")
def metrics() -> Response:
    """Prometheus exposition (counter stage_records_total, drop_reason_total, ...)."""
    try:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
    except ImportError as exc:
        raise HTTPException(
            status_code=503, detail="prometheus_client not installed"
        ) from exc
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
