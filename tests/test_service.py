"""Service (§1, P1) — enqueue endpoints ↔ arq worker wiring.

Fake pool inject qua `app.state.arq_pool` → không cần Redis. Skip khi env
không có fastapi/arq/httpx (fast dev loop cách ly).
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("arq")
pytest.importorskip("httpx")

from crawl_datasets_service.main import app  # noqa: E402
from crawl_datasets_service.worker import WorkerSettings  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class _FakeJob:
    job_id = "job-123"


class _FakePool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def enqueue_job(self, func: str, payload: dict[str, Any]) -> _FakeJob:
        self.calls.append((func, payload))
        return _FakeJob()


def _client() -> tuple[TestClient, _FakePool]:
    pool = _FakePool()
    app.state.arq_pool = pool
    return TestClient(app), pool


def test_healthz() -> None:
    client, _ = _client()
    assert client.get("/healthz").json() == {"status": "ok"}


def test_enqueue_crawl_routes_to_worker_function() -> None:
    client, pool = _client()
    res = client.post(
        "/jobs/crawl", json={"seeds": ["https://x.vn"], "depth": 2, "render": "auto"}
    )
    assert res.status_code == 200 and res.json()["job_id"] == "job-123"
    func, payload = pool.calls[0]
    assert func == "crawl_job" and payload["seeds"] == ["https://x.vn"]


def test_enqueue_build_and_integrate_route_to_workers() -> None:
    client, pool = _client()
    res = client.post("/datasets/build", json={"clean_path": "data/clean"})
    assert res.status_code == 200
    res2 = client.post(
        "/datasets/ds1/integrate",
        json={"base_dataset": "data/base", "mix_ratios": {"vi": 0.5, "en": 0.5}},
    )
    assert res2.status_code == 200
    funcs = [c[0] for c in pool.calls]
    assert funcs == ["build_job", "integrate_job"]
    assert pool.calls[1][1]["new_dataset"] == "ds1"  # dataset_id → payload


def test_worker_functions_match_enqueued_names() -> None:
    """Wiring consistency — chuỗi enqueue_job() phải trỏ đúng function arq."""
    names = {f.__name__ for f in WorkerSettings.functions}
    assert names == {"crawl_job", "build_job", "integrate_job", "plan_job"}


# --- Agent intake endpoints (§14) ---------------------------------------------

_PLAN_RESPONSE = (
    '{"type":"plan","plan":{"goal":"g","criteria":["c"],'
    '"seeds":["https://x.vn/"],"max_depth":1,"max_pages":10,"render":"http",'
    '"lang_allow":["vi"],"build_format":"chatml","quality_min_score":null,'
    '"notes":""}}'
)
_QUESTIONS_RESPONSE = '{"type":"questions","questions":["Lấy chuyên mục nào?"]}'


def _fake_fetch(url: str) -> Any:
    from crawl_datasets_common.fetch import FetchResult

    return FetchResult(url, 200, "<html><body>trang</body></html>", {})


def _agent_client(tmp_path: Any, responses: list[str]) -> tuple[TestClient, _FakePool]:
    it = iter(responses)
    pool = _FakePool()
    app.state.arq_pool = pool
    app.state.agent_llm = lambda messages: next(it)
    app.state.agent_fetch = _fake_fetch
    app.state.agent_dir = str(tmp_path)
    return TestClient(app), pool


def test_agent_session_plan_first_shot(tmp_path: Any) -> None:
    client, pool = _agent_client(tmp_path, [_PLAN_RESPONSE])
    res = client.post("/agent/sessions", json={"url": "https://x.vn/", "need": "SFT"})
    assert res.status_code == 200
    body = res.json()
    assert body["done"] is True and body["plan"]["seeds"] == ["https://x.vn/"]

    # execute → enqueue plan_job với plan đã chốt
    res2 = client.post(f"/agent/sessions/{body['session_id']}/execute")
    assert res2.status_code == 200
    func, payload = pool.calls[0]
    assert func == "plan_job" and payload["plan"]["goal"] == "g"


def test_agent_session_clarify_then_plan(tmp_path: Any) -> None:
    client, _ = _agent_client(tmp_path, [_QUESTIONS_RESPONSE, _PLAN_RESPONSE])
    res = client.post("/agent/sessions", json={"url": "https://x.vn/", "need": "SFT"})
    body = res.json()
    assert body["done"] is False and body["questions"] == ["Lấy chuyên mục nào?"]

    res2 = client.post(
        f"/agent/sessions/{body['session_id']}/answers",
        json={"answers": ["Chuyên mục công nghệ"]},
    )
    assert res2.status_code == 200 and res2.json()["done"] is True


def test_agent_execute_without_plan_conflicts(tmp_path: Any) -> None:
    client, _ = _agent_client(tmp_path, [_QUESTIONS_RESPONSE])
    res = client.post("/agent/sessions", json={"url": "https://x.vn/", "need": "SFT"})
    sid = res.json()["session_id"]
    assert client.post(f"/agent/sessions/{sid}/execute").status_code == 409
    assert client.post("/agent/sessions/unknown/execute").status_code == 404
