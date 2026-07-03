"""S1 crawl (§3) — frontier, link extraction, pipeline với fetch giả, fail-closed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from crawl_datasets_common.fetch import FetchResult
from crawl_datasets_common.settings import Settings
from crawl_datasets_crawler.frontier import Frontier, extract_links
from crawl_datasets_crawler.pipeline import run

ROOT = "https://site.example"


def test_frontier_dedup_and_depth() -> None:
    f = Frontier(max_depth=1)
    assert f.add(f"{ROOT}/a", 0) is True
    assert f.add(f"{ROOT}/a", 0) is False  # dup URL
    assert f.add(f"{ROOT}/b", 2) is False  # vượt max_depth
    assert len(f) == 1


def test_extract_links() -> None:
    html = (
        '<a href="/p1">1</a><a href="https://other.com/x">2</a>'
        '<a href="mailto:a@b">m</a>'
    )
    links = extract_links(html, "https://x.com/")
    assert "https://x.com/p1" in links
    assert "https://other.com/x" in links
    assert all("mailto" not in link for link in links)


def test_crawl_pipeline_stays_on_host(tmp_path: Path) -> None:
    m = {
        ROOT: FetchResult(
            ROOT,
            200,
            '<html><body><p>home</p><a href="/a">a</a>'
            '<a href="https://other.com/z">x</a></body></html>',
            {"content-type": "text/html"},
        ),
        f"{ROOT}/a": FetchResult(
            f"{ROOT}/a", 200, "<html><body><p>page a</p></body></html>"
        ),
    }
    stats = run([ROOT], tmp_path, Settings(), fetch=lambda u: m.get(u))
    assert stats.fetched == 2  # root + /a (other.com bị bỏ — khác host)
    recs = [
        json.loads(line)
        for line in (tmp_path / "raw" / "part-00000.jsonl").read_text().splitlines()
    ]
    assert len(recs) == 2
    assert all("html" in r and "crawl_ts" in r for r in recs)


def test_crawl_fail_closed_when_robots_disabled(tmp_path: Path) -> None:
    settings = Settings()
    settings.crawl.respect_robots = False
    with pytest.raises(SystemExit):
        run([ROOT], tmp_path, settings, fetch=lambda u: None)
