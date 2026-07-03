"""S4 profile pipeline (§6) — clean records → profile_report.json + suggestions."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from crawl_datasets_common.observability import get_logger, stage_timer
from crawl_datasets_common.settings import Settings

from .profile import Profile, build_profile

log = get_logger("profiler")


def _iter_records(in_dir: Path) -> Iterator[dict[str, Any]]:
    if not in_dir.exists():
        return
    for f in sorted(in_dir.rglob("*.jsonl")):
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)


def run(in_dir: Path, out_dir: Path, settings: Settings) -> Profile:
    """Profile clean shards → profile_report.json (§6). Trước build → quyết mix (§8)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with stage_timer("S4"):
        profile = build_profile(_iter_records(in_dir))
        (out_dir / "profile_report.json").write_text(
            json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    log.info(
        "profile_summary",
        n_docs=profile.n_docs,
        langs=profile.lang_dist,
        n_suggestions=len(profile.suggestions),
    )
    return profile
