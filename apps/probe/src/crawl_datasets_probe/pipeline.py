"""S0 probe pipeline (§2) — fetch robots/page/sitemap → source_profile.json.

Fetch inject được (test không net). Không fetch → profile 'unknown' + render mặc định.
Quyết định điều khiển S1: render, crawl_delay, seed URLs (sitemap), license gate.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urljoin

from crawl_datasets_common.fetch import FetchResult, http_get
from crawl_datasets_common.licensing import detect_license
from crawl_datasets_common.observability import get_logger, stage_timer
from crawl_datasets_common.schema import UNKNOWN_LICENSE
from crawl_datasets_common.settings import Settings

from .probe import detect_feeds, detect_render, parse_robots, parse_sitemap

log = get_logger("probe")
Fetcher = Callable[[str], FetchResult | None]


@dataclass
class SourceProfile:
    url: str
    render: str = "http"
    crawl_delay: float | None = None
    license: str = UNKNOWN_LICENSE
    content_type: str = ""
    seed_urls: list[str] = field(default_factory=list)
    feeds: list[str] = field(default_factory=list)
    disallow: list[str] = field(default_factory=list)
    fetched: bool = False


def build_profile(url: str, fetch: Fetcher, *, respect_robots: bool) -> SourceProfile:
    """Chạy mọi detection §2 trên nội dung fetch được."""
    profile = SourceProfile(url=url)

    robots = fetch(urljoin(url, "/robots.txt"))
    if robots is not None and robots.status < 400:
        info = parse_robots(robots.text)
        profile.crawl_delay = info.crawl_delay
        profile.disallow = info.disallow
        for sm_url in info.sitemaps:
            sm = fetch(sm_url)
            if sm is not None and sm.status < 400:
                profile.seed_urls.extend(parse_sitemap(sm.text))

    page = fetch(url)
    if page is not None:
        profile.fetched = True
        profile.content_type = page.headers.get("content-type", "")
        profile.render = detect_render(page.text)
        profile.feeds = detect_feeds(page.text)
        profile.license = detect_license(page.text, page.headers)

    if respect_robots and profile.disallow:
        log.info("probe_robots_disallow", url=url, n=len(profile.disallow))
    return profile


def run(
    url: str, out_dir: Path, settings: Settings, fetch: Fetcher | None = None
) -> SourceProfile:
    """Probe url → source_profile.json trong out_dir."""
    fetch = fetch or http_get
    out_dir.mkdir(parents=True, exist_ok=True)
    with stage_timer("S0"):
        profile = build_profile(
            url, fetch, respect_robots=settings.crawl.respect_robots
        )
        (out_dir / "source_profile.json").write_text(
            json.dumps(asdict(profile), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    log.info(
        "probe_summary",
        url=url,
        render=profile.render,
        license=profile.license,
        seeds=len(profile.seed_urls),
        fetched=profile.fetched,
    )
    return profile
