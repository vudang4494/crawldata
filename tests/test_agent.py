"""Agent intake (§14) — IntakeSession, DatasetPlan validation, execute_plan e2e.

LLM inject được (callable) → không cần server; fetch inject → không network.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from crawl_datasets_agent.intake import IntakeSession
from crawl_datasets_agent.plan import DatasetPlan, apply_plan
from crawl_datasets_agent.run_plan import execute_plan
from crawl_datasets_common.fetch import FetchResult
from crawl_datasets_common.settings import Settings

PROFILE = {
    "url": "https://news.example/",
    "render": "http",
    "crawl_delay": None,
    "license": "cc-by",
    "content_type": "text/html",
    "seed_urls": [],
    "feeds": [],
    "disallow": [],
    "fetched": True,
}

PLAN_OBJ: dict[str, Any] = {
    "type": "plan",
    "plan": {
        "goal": "SFT tin tức",
        "criteria": ["bài báo đầy đủ", "loại trang chuyên mục"],
        "seeds": ["https://news.example/"],
        "max_depth": 1,
        "max_pages": 20,
        "render": "http",
        "lang_allow": ["en"],
        "build_format": "chatml",
        "quality_min_score": None,
        "notes": "",
    },
}


def _llm(*responses: str) -> Any:
    it: Iterator[str] = iter(responses)

    def call(messages: list[dict[str, str]]) -> str:
        return next(it)

    return call


def test_intake_plan_first_shot() -> None:
    s = IntakeSession(
        "https://news.example/", "SFT", PROFILE, _llm(json.dumps(PLAN_OBJ))
    )
    step = s.start()
    assert step.done and step.plan is not None
    assert step.plan.seeds == ["https://news.example/"]
    assert s.final_plan is step.plan


def test_intake_clarify_loop_then_plan() -> None:
    qs = '{"type":"questions","questions":["Chuyên mục nào?","Cần bao nhiêu doc?"]}'
    s = IntakeSession(
        "https://news.example/", "SFT", PROFILE, _llm(qs, json.dumps(PLAN_OBJ))
    )
    step = s.start()
    assert not step.done and len(step.questions) == 2
    step2 = s.answer(["Công nghệ", "1000"])
    assert step2.done
    # câu trả lời của user phải nằm trong hội thoại gửi cho LLM
    assert any("Công nghệ" in m["content"] for m in s.messages)


def test_intake_retries_bad_json_then_succeeds() -> None:
    s = IntakeSession(
        "https://news.example/", "SFT", PROFILE,
        _llm("xin chào, không phải JSON", json.dumps(PLAN_OBJ)),
    )
    assert s.start().done


def test_intake_fails_closed_after_max_retries() -> None:
    s = IntakeSession(
        "https://news.example/", "SFT", PROFILE,
        _llm("rác", "rác", "rác"), max_retries=3,
    )
    with pytest.raises(RuntimeError, match="fail-closed"):
        s.start()


def test_intake_forces_plan_when_rounds_exhausted() -> None:
    qs = '{"type":"questions","questions":["Hỏi nữa?"]}'
    s = IntakeSession(
        "https://news.example/", "SFT", PROFILE,
        _llm(qs, qs, json.dumps(PLAN_OBJ)), max_rounds=1,
    )
    assert not s.start().done  # vòng hỏi 1 — hợp lệ
    step = s.answer(["trả lời"])  # LLM lại hỏi → ép chốt plan → plan
    assert step.done


def test_plan_rejects_non_http_seed_and_bad_depth() -> None:
    with pytest.raises(ValueError):
        DatasetPlan(goal="g", seeds=["ftp://x"])
    with pytest.raises(ValueError):
        DatasetPlan(goal="g", seeds=["https://x.vn"], max_depth=99)


def test_apply_plan_touches_only_safe_keys() -> None:
    base = Settings()
    plan = DatasetPlan(**PLAN_OBJ["plan"])
    merged = apply_plan(base, plan)
    assert merged.crawl.max_depth == 1 and merged.clean.lang_allow == ["en"]
    # gate bất khả xâm phạm: robots vẫn true, dedup scope giữ nguyên
    assert merged.crawl.respect_robots is True
    assert merged.clean.minhash.scope == "per_source"
    # base không bị mutate (copy)
    assert base.crawl.max_depth != 1 or Settings().crawl.max_depth == 1


_ARTICLE = (
    "The city council approved a new budget after a long public debate on Tuesday "
    "evening. Local residents welcomed the decision because it funds schools, safer "
    "roads and greener public parks across the whole district for the coming year, "
    "while officials promised regular progress reports so that everyone can follow "
    "exactly how the money will be spent over time."
)
_HTML = (
    "<html><head><title>Budget</title></head><body>"
    f"<article><p>{_ARTICLE}</p></article>"
    '<a href="https://creativecommons.org/licenses/by/4.0/">CC BY</a>'
    "</body></html>"
)


def test_execute_plan_runs_s1_to_s5(tmp_path: Path) -> None:
    plan = DatasetPlan(**PLAN_OBJ["plan"])
    fetch = {
        "https://news.example/": FetchResult(
            "https://news.example/", 200, _HTML, {"content-type": "text/html"}
        )
    }
    summary = execute_plan(
        plan, Settings(), tmp_path / "run", fetch=lambda u: fetch.get(u)
    )
    assert summary["fetched"] == 1 and summary["built"] == 1
    assert (tmp_path / "run" / "dataset_plan.json").exists()
    assert Path(summary["dataset"]).exists()
    assert Path(summary["profile_report"]).exists()
