"""S1 crawl pipeline (§3) — frontier + fetch + politeness → raw HTML tier.

Extract tách khỏi crawl (§3.1): chỉ lưu raw HTML; S2 extract sau. Stay-on-host,
depth-bounded, URL dedup (§3.3). Fetch inject được (test không network). Fail-closed:
respect_robots=false → refuse (§2).
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib import robotparser
from urllib.parse import urljoin

from crawl_datasets_common.fetch import USER_AGENT, FetchResult, http_get
from crawl_datasets_common.observability import (
    get_logger,
    record_drop,
    records_total,
    stage_timer,
)
from crawl_datasets_common.settings import Settings
from crawl_datasets_common.storage import StorageLayout, mark_done

from .frontier import Frontier, extract_links, host_of
from .render import build_renderer, needs_render

log = get_logger("crawler")
_STAGE = "S1"
_MAX_CRAWL_DELAY = 30.0  # robots Crawl-delay cực đoan không được treo pipeline
Fetcher = Callable[[str], FetchResult | None]
Renderer = Callable[[str], FetchResult | None]
Sleeper = Callable[[float], None]


def _fetch_robots(
    seeds: list[str], fetch: Fetcher
) -> dict[str, robotparser.RobotFileParser | None]:
    """§2 — tải robots.txt per-host để enforce Disallow per-URL + Crawl-delay.

    Không có / không tải được → None = allow-all (chuẩn robots: absent = allowed).
    """
    robots: dict[str, robotparser.RobotFileParser | None] = {}
    for seed in seeds:
        host = host_of(seed)
        if host in robots:
            continue
        res = fetch(urljoin(seed, "/robots.txt"))
        rp: robotparser.RobotFileParser | None = None
        if res is not None and res.status < 400:
            rp = robotparser.RobotFileParser()
            rp.parse(res.text.splitlines())
        robots[host] = rp
        log.info("robots_loaded", host=host, present=rp is not None)
    return robots


@dataclass
class CrawlStats:
    seen: int = 0
    fetched: int = 0
    escalated: int = 0  # §3.2 auto — số URL đã escalate http→browser
    dropped: Counter[str] = field(default_factory=Counter)


def run(
    seeds: list[str],
    out_dir: Path,
    settings: Settings,
    fetch: Fetcher | None = None,
    *,
    renderer: Renderer | None = None,
    max_pages: int = 10_000,
    sleeper: Sleeper = time.sleep,
) -> CrawlStats:
    """Crawl seeds (BFS, stay-on-host) → raw/part-00000.jsonl."""
    if not settings.crawl.respect_robots:
        raise SystemExit("respect_robots=false vi phạm §2 (legal gate fail-closed)")

    # §3.2 — render mode. browser: bắt buộc có renderer (fail-closed, S0 đã gắn cờ
    # JS-required). auto: build lazy khi URL đầu tiên cần escalate (chromium đắt).
    mode = settings.crawl.render
    if mode == "browser" and renderer is None:
        browser = build_renderer()
        if browser is None:
            raise SystemExit("render=browser nhưng Playwright không sẵn sàng (§3.2)")
        renderer = browser.render
    _lazy: dict[str, Renderer | None] = {}

    def _auto_renderer() -> Renderer | None:
        if renderer is not None:
            return renderer
        if "r" not in _lazy:
            browser = build_renderer()
            _lazy["r"] = browser.render if browser is not None else None
            if browser is None:
                log.warning("render_escalate_unavailable")  # auto chạy tiếp http-only
        return _lazy["r"]

    fetch = fetch or http_get
    raw_tier = StorageLayout(root=out_dir).tier("raw")
    frontier = Frontier(settings.crawl.max_depth)
    seed_hosts = {host_of(s) for s in seeds}
    for s in seeds:
        frontier.add(s, 0)

    # §2 robots per-URL + §3 politeness + §3.3 url_exclude (pilot findings).
    robots = _fetch_robots(seeds, fetch)
    exclude_res = [re.compile(p) for p in settings.crawl.url_exclude]
    last_fetch: dict[str, float] = {}

    def _delay_for(host: str) -> float:
        delay = settings.crawl.politeness_delay
        rp = robots.get(host)
        if rp is not None:
            crawl_delay = rp.crawl_delay(USER_AGENT)
            if crawl_delay:
                delay = max(delay, float(crawl_delay))
        return min(delay, _MAX_CRAWL_DELAY)

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
            rp = robots.get(host)
            if rp is not None and not rp.can_fetch(USER_AGENT, url):
                stats.dropped["robots_disallow"] += 1  # §2 — enforce per-URL
                record_drop(_STAGE, "robots_disallow")
                _inc("dropped")
                continue
            stats.seen += 1
            _inc("in")
            prev = last_fetch.get(host)
            if prev is not None:  # §3 politeness — chờ đủ delay giữa 2 request
                wait = _delay_for(host) - (time.monotonic() - prev)
                if wait > 0:
                    sleeper(wait)
            last_fetch[host] = time.monotonic()
            res = renderer(url) if mode == "browser" and renderer else fetch(url)
            if res is None or res.status >= 400:
                stats.dropped["fetch_failed"] += 1
                record_drop(_STAGE, "fetch_failed")
                _inc("dropped")
                continue
            if mode == "auto" and needs_render(
                res.text, settings.crawl.render_min_text_len
            ):  # §3.2 — HTTP trước, escalate browser khi text mỏng/root rỗng
                r = _auto_renderer()
                rendered = r(url) if r is not None else None
                if rendered is not None and rendered.status < 400:
                    res = rendered
                    stats.escalated += 1
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
                if host_of(link) not in seed_hosts:
                    continue
                if any(rx.search(link) for rx in exclude_res):
                    stats.dropped["url_excluded"] += 1  # §3.3 — non-article
                    continue
                frontier.add(link, depth + 1)

    mark_done(
        raw_tier,
        n_records=stats.fetched,
        metadata={
            "seen": stats.seen,
            "fetched": stats.fetched,
            "escalated": stats.escalated,
            "dropped": dict(stats.dropped),
            "seeds": seeds,
            "max_depth": settings.crawl.max_depth,
            "render": mode,
        },
    )
    log.info(
        "crawl_summary",
        seen=stats.seen,
        fetched=stats.fetched,
        escalated=stats.escalated,
        dropped=dict(stats.dropped),
    )
    return stats
