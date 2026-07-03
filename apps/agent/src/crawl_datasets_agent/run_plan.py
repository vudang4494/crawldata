"""Thực thi DatasetPlan (§14) — chạy chuỗi S1→S5 dưới một out_root.

S0 đã chạy lúc intake. Agent chỉ cấp config qua `apply_plan`; mọi stage giữ
nguyên gate/checkpoint/idempotency của nó (tier layout chuẩn: raw/ → extracted/
→ clean/ → dataset/ + profile/). Fetch inject được (test không network).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from crawl_datasets_builder.pipeline import run as build_run
from crawl_datasets_cleaner.pipeline import run as clean_run
from crawl_datasets_common.fetch import FetchResult
from crawl_datasets_common.settings import Settings
from crawl_datasets_crawler.pipeline import run as crawl_run
from crawl_datasets_extractor.pipeline import run as extract_run
from crawl_datasets_profiler.pipeline import run as profile_run

from .plan import DatasetPlan, apply_plan

Fetcher = Callable[[str], FetchResult | None]


def execute_plan(
    plan: DatasetPlan,
    base_settings: Settings,
    out_root: Path,
    fetch: Fetcher | None = None,
) -> dict[str, Any]:
    """Chạy S1→S5 theo plan → summary per-stage + đường dẫn output."""
    settings = apply_plan(base_settings, plan)
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "dataset_plan.json").write_text(
        plan.model_dump_json(indent=2), encoding="utf-8"
    )

    c = crawl_run(plan.seeds, out_root, settings, fetch, max_pages=plan.max_pages)
    e = extract_run(out_root / "raw", out_root, settings)
    cl = clean_run(out_root / "extracted", out_root, settings)
    prof = profile_run(out_root / "clean", out_root / "profile", settings)
    b = build_run(out_root / "clean", out_root, settings)

    return {
        "fetched": c.fetched,
        "extracted": e.extracted,
        "kept": cl.kept,
        "profiled": prof.n_docs,
        "built": b.built,
        "dropped": {
            "crawl": dict(c.dropped),
            "extract": dict(e.dropped),
            "clean": dict(cl.dropped),
            "build": dict(b.dropped),
        },
        "dataset": str(out_root / "dataset" / "part-00000.jsonl"),
        "profile_report": str(out_root / "profile" / "profile_report.json"),
    }
