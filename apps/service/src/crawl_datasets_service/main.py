"""FastAPI service skeleton (§1, §9.4).

Endpoints (theo spec §1):
  POST /jobs/crawl          {seeds[], depth, render, lang_allow[]}  -> job_id
  GET  /jobs/{id}           -> {stage, shards_done, in/out/dropped, eta}
  POST /datasets/build      {clean_path, format, schema_ver}        -> dataset_id
  POST /datasets/{id}/integrate {base_dataset, mix_ratios, dedup}  -> new_version
  GET  /datasets/{id}/profile -> stats + suggestions
  GET  /metrics             -> Prometheus exposition
  GET  /healthz

Agent intake (§14):
  POST /agent/sessions               {url, need}  -> {session_id, questions|plan}
  POST /agent/sessions/{id}/answers  {answers[]}  -> {questions|plan}
  POST /agent/sessions/{id}/execute  -> enqueue plan_job (JobAck)
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from crawl_datasets_agent.intake import IntakeSession, Step
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


# --- Agent intake (§14) -------------------------------------------------------
# Session in-memory per-process (P-A; multi-worker → chuyển Redis). Test inject:
# `app.state.agent_llm` (fake LLM), `app.state.agent_fetch`, `app.state.agent_dir`.


class AgentSessionRequest(BaseModel):
    url: str
    need: str


class AgentAnswersRequest(BaseModel):
    answers: list[str]


class AgentStepResponse(BaseModel):
    session_id: str
    done: bool
    questions: list[str] = Field(default_factory=list)
    plan: dict[str, Any] | None = None


def _sessions(request: Request) -> dict[str, IntakeSession]:
    if not hasattr(request.app.state, "agent_sessions"):
        request.app.state.agent_sessions = {}
    sessions: dict[str, IntakeSession] = request.app.state.agent_sessions
    return sessions


def _step_response(sid: str, step: Step) -> AgentStepResponse:
    return AgentStepResponse(
        session_id=sid,
        done=step.done,
        questions=step.questions,
        plan=step.plan.model_dump() if step.plan is not None else None,
    )


@app.post("/agent/sessions", response_model=AgentStepResponse)
def agent_start(req: AgentSessionRequest, request: Request) -> AgentStepResponse:
    """§14 — probe URL → agent phân tích nhu cầu → questions hoặc plan."""
    from crawl_datasets_probe.pipeline import run as probe_run

    settings = load_settings()
    sid = uuid.uuid4().hex[:12]
    out_dir = Path(
        getattr(request.app.state, "agent_dir", "data/agent")
    ) / sid / "s0"
    fetch = getattr(request.app.state, "agent_fetch", None)
    profile_s0 = probe_run(req.url, out_dir, settings, fetch=fetch)

    llm = getattr(request.app.state, "agent_llm", None)
    if llm is None:
        from crawl_datasets_agent.llm import ChatLLM

        try:
            llm = ChatLLM(settings.agent)
        except RuntimeError as exc:  # thiếu httpx backend — 503 tường minh
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    session = IntakeSession(
        req.url, req.need, profile_s0, llm, max_rounds=settings.agent.max_rounds
    )
    try:
        step = session.start()
    except RuntimeError as exc:  # LLM không trả plan hợp lệ (§14 fail-closed)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    _sessions(request)[sid] = session
    return _step_response(sid, step)


@app.post("/agent/sessions/{sid}/answers", response_model=AgentStepResponse)
def agent_answer(
    sid: str, req: AgentAnswersRequest, request: Request
) -> AgentStepResponse:
    session = _sessions(request).get(sid)
    if session is None:
        raise HTTPException(status_code=404, detail="session không tồn tại")
    try:
        step = session.answer(req.answers)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _step_response(sid, step)


@app.post("/agent/sessions/{sid}/execute", response_model=JobAck)
async def agent_execute(sid: str, request: Request) -> JobAck:
    """Enqueue plan đã chốt → worker `plan_job` chạy S1→S5."""
    session = _sessions(request).get(sid)
    if session is None:
        raise HTTPException(status_code=404, detail="session không tồn tại")
    # Plan nằm ở message assistant cuối đã validate — dựng lại từ session state.
    last_plan = getattr(session, "final_plan", None)
    if last_plan is None:
        raise HTTPException(status_code=409, detail="session chưa có plan chốt")
    out = str(
        Path(getattr(request.app.state, "agent_dir", "data/agent")) / sid
    )
    return await _enqueue(
        request, "plan_job", {"plan": last_plan.model_dump(), "out": out}
    )


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
