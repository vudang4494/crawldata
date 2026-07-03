"""Full pipeline S1→S2→S3→S4→S5→S6 (§3–§8) — 1 nguồn CC-BY chạy hết chuỗi."""

from __future__ import annotations

from pathlib import Path

from crawl_datasets_builder.pipeline import run as build_run
from crawl_datasets_cleaner.pipeline import run as clean_run
from crawl_datasets_common.fetch import FetchResult
from crawl_datasets_common.settings import Settings
from crawl_datasets_crawler.pipeline import run as crawl_run
from crawl_datasets_extractor.pipeline import run as extract_run
from crawl_datasets_integrator.pipeline import run as integrate_run
from crawl_datasets_profiler.pipeline import run as profile_run

ROOT = "https://news.example"
_ARTICLE = (
    "The city council approved a new budget after a long public debate on Tuesday "
    "evening. Local residents welcomed the decision because it funds schools, safer "
    "roads and greener public parks across the whole district for the coming year, "
    "while officials promised regular progress reports so that everyone can follow "
    "exactly how the money will be spent over time."
)
_HTML = (
    "<html><head><title>Budget</title></head><body><nav>Home</nav>"
    "<script>var x = 1;</script>"
    f"<article><p>{_ARTICLE}</p></article>"
    '<a href="https://creativecommons.org/licenses/by/4.0/">CC BY</a>'
    "<footer>(c) 2026</footer></body></html>"
)


def test_full_pipeline(tmp_path: Path) -> None:
    settings = Settings()
    fetch = {ROOT: FetchResult(ROOT, 200, _HTML, {"content-type": "text/html"})}

    # S1 crawl → raw
    c = crawl_run([ROOT], tmp_path / "s1", settings, fetch=lambda u: fetch.get(u))
    assert c.fetched == 1

    # S2 extract → extracted (license cc-by detect từ HTML, §2)
    e = extract_run(tmp_path / "s1" / "raw", tmp_path / "s2", settings)
    assert e.extracted == 1

    # S3 clean → clean
    cl = clean_run(tmp_path / "s2" / "extracted", tmp_path / "s3", settings)
    assert cl.kept == 1

    # S4 profile
    prof = profile_run(tmp_path / "s3" / "clean", tmp_path / "s4", settings)
    assert prof.n_docs == 1 and prof.license_dist.get("cc-by") == 1

    # S5 build (cc-by → publishable)
    b = build_run(tmp_path / "s3" / "clean", tmp_path / "s5", settings)
    assert b.built == 1

    # S6 integrate (base = new = dataset → cross-dedup loại 1)
    integ = integrate_run(
        tmp_path / "s5" / "dataset",
        tmp_path / "s5" / "dataset",
        tmp_path / "s6",
        settings,
    )
    assert integ.base == 1 and integ.new == 1 and integ.removed_dup == 1
    assert (tmp_path / "s6" / "part-00000.jsonl").exists()
