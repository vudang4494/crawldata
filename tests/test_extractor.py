"""S2 extractor (§4) — HTML→text fallback, pipeline, và handoff S2→S3 end-to-end."""

from __future__ import annotations

import json
from pathlib import Path

from crawl_datasets_cleaner.pipeline import run as clean_run
from crawl_datasets_common.provenance import verify_provenance
from crawl_datasets_common.settings import Settings
from crawl_datasets_extractor.html_extract import extract_html
from crawl_datasets_extractor.pipeline import run as extract_run

_ARTICLE = (
    "The city council approved a new plan to expand public transport across the "
    "entire region this year. Officials said that the project would create many "
    "jobs and reduce traffic during peak hours, while residents welcomed the "
    "decision because it funds buses, safer roads and greener parks for families "
    "throughout every neighbourhood in the coming decade."
)
_HTML = (
    "<html><head><title>Transport plan</title></head><body>"
    "<nav>Home About Contact</nav>"
    "<script>var x = 1;</script>"
    f"<article><p>{_ARTICLE}</p></article>"
    "<footer>© 2026 Example News</footer></body></html>"
)


def test_extract_html_fallback_strips_boilerplate() -> None:
    res = extract_html(_HTML, primary="trafilatura")
    assert res is not None
    text, extractor, title = res
    assert "council approved" in text
    assert "var x = 1" not in text  # script bỏ
    assert "Home About Contact" not in text  # nav bỏ
    # trafilatura chưa cài trong test env → fallback
    assert extractor == "htmlparser-fallback"
    assert title == "Transport plan"


def test_extract_pipeline_drops_bad_records(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "part-0.jsonl").write_text(
        "\n".join(
            json.dumps(d)
            for d in [
                {"source_url": "https://a.com/1", "html": _HTML, "license": "cc-by"},
                {"html": "<p>no url.</p>"},  # thiếu source_url → drop
                {"source_url": "https://a.com/3"},  # no content → drop
            ]
        ),
        encoding="utf-8",
    )
    stats = extract_run(raw, tmp_path / "out", Settings())
    assert stats.seen == 3
    assert stats.extracted == 1
    assert "no_source_url" in stats.dropped and "no_content" in stats.dropped

    rec = json.loads((tmp_path / "out" / "extracted" / "part-00000.jsonl").read_text())
    assert rec["source_url"] == "https://a.com/1"
    assert rec["extractor"] and "council approved" in rec["text"]


def test_extract_reads_html_files_with_sidecar(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "page.html").write_text(_HTML, encoding="utf-8")
    (raw / "page.meta.json").write_text(
        json.dumps({"source_url": "https://src.example/x", "license": "cc0"}),
        encoding="utf-8",
    )
    stats = extract_run(raw, tmp_path / "out", Settings())
    assert stats.extracted == 1
    rec = json.loads((tmp_path / "out" / "extracted" / "part-00000.jsonl").read_text())
    assert rec["source_url"] == "https://src.example/x" and rec["license"] == "cc0"


def test_s2_to_s3_end_to_end(tmp_path: Path) -> None:
    """§3.1/§4/§5 — raw HTML → extract (S2) → clean (S3), provenance đầy đủ."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "part-0.jsonl").write_text(
        json.dumps(
            {"source_url": "https://news.vn/1", "html": _HTML, "license": "cc-by"}
        ),
        encoding="utf-8",
    )
    settings = Settings()
    extracted_dir = tmp_path / "s2"
    extract_run(raw, extracted_dir, settings)

    clean_stats = clean_run(extracted_dir / "extracted", tmp_path / "s3", settings)
    assert clean_stats.kept == 1

    rec = json.loads((tmp_path / "s3" / "clean" / "part-00000.jsonl").read_text())
    verify_provenance(rec["prov"])  # §0 — không raise
    assert rec["prov"]["license"] == "cc-by"
    assert rec["prov"]["extractor"] == "htmlparser-fallback"  # truyền từ S2
    assert rec["lang"] == "en"
