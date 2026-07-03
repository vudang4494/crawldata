"""S2 extract pipeline (§4). raw HTML/WARC/PDF → extracted JSONL (text + meta).

Tách khỏi crawl (§3.1): đọc raw tier (immutable) → rút text → extracted tier. Replay
được khi đổi extractor mà không crawl lại. Fail-closed: không rút được text → drop+log.

Raw input (linh hoạt):
- `*.jsonl`: mỗi dòng {source_url, html|content, crawl_ts?, license?, content_type?}
- `*.html`: file HTML, meta ở sibling `<name>.meta.json` (source_url/license…) nếu có.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crawl_datasets_common.licensing import detect_license
from crawl_datasets_common.observability import (
    get_logger,
    record_drop,
    records_total,
    stage_timer,
)
from crawl_datasets_common.schema import LICENSE_TAGS, stable_id
from crawl_datasets_common.settings import Settings
from crawl_datasets_common.storage import StorageLayout, mark_done

from .html_extract import extract_html
from .pdf_extract import extract_pdf

log = get_logger("extractor")
_STAGE = "S2"


@dataclass
class ExtractStats:
    seen: int = 0
    extracted: int = 0
    dropped: Counter[str] = field(default_factory=Counter)


def _iter_raw(in_dir: Path) -> Iterator[dict[str, Any]]:
    """Yield raw records từ *.jsonl và *.html (đọc lazy, không load-all)."""
    if not in_dir.exists():
        return
    for f in sorted(in_dir.rglob("*.jsonl")):
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)
    for f in sorted(in_dir.rglob("*.html")):
        meta_path = f.with_suffix(".meta.json")
        meta: dict[str, Any] = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta.setdefault("source_url", f.as_uri())
        meta["html"] = f.read_text(encoding="utf-8", errors="replace")
        yield meta


def _extract_one(
    raw: dict[str, Any], primary: str
) -> tuple[dict[str, Any] | None, str | None]:
    source_url = raw.get("source_url")
    if not isinstance(source_url, str) or not source_url:
        return None, "no_source_url"  # fail-closed: provenance cần source (§0)

    content_type = str(raw.get("content_type", "")).lower()
    html = raw.get("html") or raw.get("content")
    pdf_path = raw.get("pdf_path")

    # §2 — ghi license per-record từ S2: raw license nếu hợp lệ, else detect từ HTML.
    raw_license = raw.get("license")
    license_ = raw_license if raw_license in LICENSE_TAGS else None

    title: str | None = None
    if "pdf" in content_type or pdf_path:
        if not isinstance(pdf_path, str):
            return None, "pdf_no_path"
        res_pdf = extract_pdf(Path(pdf_path))
        if res_pdf is None:
            return None, "empty_extract_pdf"
        text, extractor = res_pdf
    elif isinstance(html, str) and html.strip():
        res_html = extract_html(html, primary)
        if res_html is None:
            return None, "empty_extract_html"
        text, extractor, title = res_html
        if license_ is None:
            license_ = detect_license(html)
    else:
        return None, "no_content"

    record = {
        "id": stable_id(source_url, extractor),
        "text": text,
        "source_url": source_url,
        "crawl_ts": raw.get("crawl_ts"),
        "license": license_ or "unknown",
        "extractor": extractor,
        "title": title or raw.get("title"),
    }
    return record, None


def run(in_dir: Path, out_dir: Path, settings: Settings) -> ExtractStats:
    """Stream raw → extracted shard + `_SUCCESS`/manifest (idempotent)."""
    extracted_tier = StorageLayout(root=out_dir).tier("extracted")
    stats = ExtractStats()
    out_path = extracted_tier / "part-00000.jsonl"

    def _inc(status: str) -> None:
        if records_total is not None:
            records_total.labels(stage=_STAGE, status=status).inc()

    with stage_timer(_STAGE), out_path.open("w", encoding="utf-8") as out_f:
        for raw in _iter_raw(in_dir):
            stats.seen += 1
            _inc("in")
            record, reason = _extract_one(raw, settings.extract.primary)
            if reason is not None:
                stats.dropped[reason] += 1
                record_drop(_STAGE, reason)
                _inc("dropped")
                continue
            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
            stats.extracted += 1
            _inc("out")

    mark_done(
        extracted_tier,
        n_records=stats.extracted,
        metadata={
            "seen": stats.seen,
            "extracted": stats.extracted,
            "dropped": dict(stats.dropped),
            "primary": settings.extract.primary,
        },
    )
    log.info(
        "extract_summary",
        seen=stats.seen,
        extracted=stats.extracted,
        dropped=dict(stats.dropped),
    )
    return stats
