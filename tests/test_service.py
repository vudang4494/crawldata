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
    assert names == {"crawl_job", "build_job", "integrate_job"}
