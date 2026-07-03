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
from fastapi import FastAPI, HTTPException, Response
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


# --- Job endpoints (arq workers — stubbed) ----------------------------------


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
def enqueue_crawl(req: CrawlJobRequest) -> JobAck:
    """Enqueue crawl job vào arq (Redis). Skeleton — không có worker thật."""
    # TODO(P3): arq.enqueue("crawl", req.model_dump())
    raise HTTPException(status_code=501, detail="crawl worker not implemented (P3)")


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    # TODO(P3): Redis HGET job:{id} → stage, shards_done, counters.
    return {"job_id": job_id, "stage": "queued"}


@app.post("/datasets/build", response_model=JobAck)
def enqueue_build(req: BuildDatasetRequest) -> JobAck:
    raise HTTPException(status_code=501, detail="build worker not implemented (P3)")


@app.post("/datasets/{dataset_id}/integrate", response_model=JobAck)
def enqueue_integrate(dataset_id: str, req: IntegrateRequest) -> JobAck:
    raise HTTPException(status_code=501, detail="integrate worker not implemented (P3)")


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
