"""S1 crawl pipeline (§3) — frontier + fetch + politeness → raw HTML tier.

Extract tách khỏi crawl (§3.1): chỉ lưu raw HTML; S2 extract sau. Stay-on-host,
depth-bounded, URL dedup (§3.3). Fetch inject được (test không network). Fail-closed:
respect_robots=false → refuse (§2).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from crawl_datasets_common.fetch import FetchResult, http_get
from crawl_datasets_common.observability import (
    get_logger,
    record_drop,
    records_total,
    stage_timer,
)
from crawl_datasets_common.settings import Settings
from crawl_datasets_common.storage import StorageLayout, mark_done

from .frontier import Frontier, extract_links, host_of

log = get_logger("crawler")
_STAGE = "S1"
Fetcher = Callable[[str], FetchResult | None]


@dataclass
class CrawlStats:
    seen: int = 0
    fetched: int = 0
    dropped: Counter[str] = field(default_factory=Counter)


def run(
    seeds: list[str],
    out_dir: Path,
    settings: Settings,
    fetch: Fetcher | None = None,
    *,
    max_pages: int = 10_000,
) -> CrawlStats:
    """Crawl seeds (BFS, stay-on-host) → raw/part-00000.jsonl."""
    if not settings.crawl.respect_robots:
        raise SystemExit("respect_robots=false vi phạm §2 (legal gate fail-closed)")

    fetch = fetch or http_get
    raw_tier = StorageLayout(root=out_dir).tier("raw")
    frontier = Frontier(settings.crawl.max_depth)
    seed_hosts = {host_of(s) for s in seeds}
    for s in seeds:
        frontier.add(s, 0)

    per_host: Counter[str] = Counter()
    stats = CrawlStats()
    out_path = raw_tier / "part-00000.jsonl"

    def _inc(status: str) -> None:
        if records_total is not None:
            records_total.labels(stage=_STAGE, status=status).inc()

    with stage_timer(_STAGE), out_path.open("w", encoding="utf-8") as out_f:
        while (item := frontier.pop()) is not None and stats.fetched < max_pages:
            url, depth = item
            host = host_of(url)
            if per_host[host] >= settings.crawl.per_host_concurrency * 50:
                stats.dropped["host_cap"] += 1
                continue
            stats.seen += 1
            _inc("in")
            res = fetch(url)
            if res is None or res.status >= 400:
                stats.dropped["fetch_failed"] += 1
                record_drop(_STAGE, "fetch_failed")
                _inc("dropped")
                continue
            per_host[host] += 1
            record = {
                "source_url": res.url,
                "html": res.text,
                "crawl_ts": datetime.now(UTC).isoformat(),
                "content_type": res.headers.get("content-type", "text/html"),
                "depth": depth,
            }
            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
            stats.fetched += 1
            _inc("out")
            for link in extract_links(res.text, res.url):
                if host_of(link) in seed_hosts:
                    frontier.add(link, depth + 1)

    mark_done(
        raw_tier,
        n_records=stats.fetched,
        metadata={
            "seen": stats.seen,
            "fetched": stats.fetched,
            "dropped": dict(stats.dropped),
            "seeds": seeds,
            "max_depth": settings.crawl.max_depth,
        },
    )
    log.info(
        "crawl_summary",
        seen=stats.seen,
        fetched=stats.fetched,
        dropped=dict(stats.dropped),
    )
    return stats
