"""S0 probe (§2) — robots/sitemap/render/license + pipeline với fetch giả."""

from __future__ import annotations

import json
from pathlib import Path

from crawl_datasets_common.fetch import FetchResult
from crawl_datasets_common.licensing import detect_license
from crawl_datasets_common.settings import Settings
from crawl_datasets_probe.pipeline import run
from crawl_datasets_probe.probe import detect_render, parse_robots, parse_sitemap

ROOT = "https://site.example"


def _fetcher(m: dict[str, FetchResult]):
    def fetch(url: str) -> FetchResult | None:
        return m.get(url)

    return fetch


def test_parse_robots() -> None:
    info = parse_robots(
        "User-agent: *\nCrawl-delay: 2\nDisallow: /private\nSitemap: https://x/sm.xml"
    )
    assert info.crawl_delay == 2.0
    assert "/private" in info.disallow
    assert "https://x/sm.xml" in info.sitemaps


def test_parse_sitemap() -> None:
    assert parse_sitemap("<urlset><url><loc>https://x/a</loc></url></urlset>") == [
        "https://x/a"
    ]


def test_detect_render() -> None:
    spa = (
        '<html><body><div id="root"></div>'
        "<script></script><script></script><script></script></body></html>"
    )
    assert detect_render(spa) == "browser"
    static = "<html><body><p>" + "word " * 200 + "</p></body></html>"
    assert detect_render(static) == "http"


def test_detect_license() -> None:
    assert (
        detect_license('<a href="https://creativecommons.org/licenses/by/4.0/">')
        == "cc-by"
    )
    # by-sa phải TRƯỚC by trong pattern — URL by-sa chứa prefix "licenses/by"
    # (pilot vi.wikipedia: từng bị tag nhầm cc-by → sai nghĩa vụ share-alike).
    assert (
        detect_license('<a href="https://creativecommons.org/licenses/by-sa/4.0/">')
        == "cc-by-sa"
    )
    assert detect_license("<p>All rights reserved.</p>") == "unknown"


def test_probe_pipeline(tmp_path: Path) -> None:
    page = (
        '<html><head><link rel="alternate" type="application/rss+xml" href="/feed">'
        "</head><body><p>hello world</p>"
        '<a href="https://creativecommons.org/licenses/by/4.0/">cc</a></body></html>'
    )
    m = {
        f"{ROOT}/robots.txt": FetchResult(
            f"{ROOT}/robots.txt", 200, f"Crawl-delay: 1\nSitemap: {ROOT}/sm.xml"
        ),
        f"{ROOT}/sm.xml": FetchResult(
            f"{ROOT}/sm.xml", 200, f"<urlset><url><loc>{ROOT}/a</loc></url></urlset>"
        ),
        ROOT: FetchResult(ROOT, 200, page, {"content-type": "text/html"}),
    }
    profile = run(ROOT, tmp_path, Settings(), fetch=_fetcher(m))
    assert profile.crawl_delay == 1.0
    assert profile.seed_urls == [f"{ROOT}/a"]
    assert profile.license == "cc-by"
    assert profile.render == "http" and profile.feeds == ["/feed"]
    assert (
        json.loads((tmp_path / "source_profile.json").read_text())["license"] == "cc-by"
    )
