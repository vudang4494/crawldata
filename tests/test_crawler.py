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


# --- §3.2 JS-render (P1) ------------------------------------------------------

_SPA_HTML = (
    '<html><body><div id="root"></div><script>window.app()</script></body></html>'
)
_FULL_HTML = "<html><body><p>" + "rendered content word " * 30 + "</p></body></html>"


def test_needs_render_heuristic() -> None:
    from crawl_datasets_crawler.render import needs_render

    assert needs_render(_SPA_HTML, 200) is True  # root SPA rỗng + text mỏng
    assert needs_render(_FULL_HTML, 200) is False


def test_auto_mode_escalates_to_renderer(tmp_path: Path) -> None:
    """§3.2 auto — HTTP trước; HTML mỏng → escalate browser (renderer inject)."""
    fetched = FetchResult(ROOT, 200, _SPA_HTML, {"content-type": "text/html"})
    rendered = FetchResult(ROOT, 200, _FULL_HTML, {"content-type": "text/html"})
    stats = run(
        [ROOT],
        tmp_path,
        Settings(),
        fetch=lambda u: fetched,
        renderer=lambda u: rendered,
    )
    assert stats.escalated == 1 and stats.fetched == 1
    rec = json.loads(
        (tmp_path / "raw" / "part-00000.jsonl").read_text().splitlines()[0]
    )
    assert "rendered content" in rec["html"]


def test_auto_mode_keeps_http_when_renderer_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import crawl_datasets_crawler.pipeline as crawler_pipeline

    monkeypatch.setattr(crawler_pipeline, "build_renderer", lambda: None)
    fetched = FetchResult(ROOT, 200, _SPA_HTML, {})
    stats = run([ROOT], tmp_path, Settings(), fetch=lambda u: fetched)
    assert stats.fetched == 1 and stats.escalated == 0  # http-only, không crash


def test_browser_mode_uses_renderer_for_all_fetches(tmp_path: Path) -> None:
    calls: list[str] = []

    def renderer(url: str) -> FetchResult:
        calls.append(url)
        return FetchResult(url, 200, _FULL_HTML, {})

    settings = Settings()
    settings.crawl.render = "browser"
    stats = run([ROOT], tmp_path, settings, fetch=lambda u: None, renderer=renderer)
    assert stats.fetched == 1 and calls == [ROOT]  # fetch http không được gọi


def test_browser_mode_without_playwright_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§3.2 — S0 gắn cờ JS-required mà không render được → refuse, không crawl mù."""
    import crawl_datasets_crawler.pipeline as crawler_pipeline

    monkeypatch.setattr(crawler_pipeline, "build_renderer", lambda: None)
    settings = Settings()
    settings.crawl.render = "browser"
    with pytest.raises(SystemExit):
        run([ROOT], tmp_path, settings, fetch=lambda u: None)
