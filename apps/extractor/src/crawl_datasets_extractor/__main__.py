"""S2 — Extract (§4)."""

from __future__ import annotations

from pathlib import Path

import click
from crawl_datasets_common.observability import (
    configure_logging,
    get_logger,
    stage_timer,
)
from crawl_datasets_common.settings import load_settings
from crawl_datasets_common.storage import StorageLayout, mark_done

log = get_logger("extractor")


@click.command()
@click.option("--in", "in_", required=True, type=click.Path(path_type=Path))
@click.option("--out", required=True, type=click.Path(path_type=Path))
def main(in_: Path, out: Path) -> None:
    """Extract text from raw HTML/WARC → JSONL shards (skeleton)."""
    configure_logging()
    settings = load_settings()
    log.info(
        "extract_start",
        primary=settings.extract.primary,
        fallback=settings.extract.fallback,
        in_path=str(in_),
        out=str(out),
    )

    layout = StorageLayout(root=out)
    extracted_tier = layout.tier("extracted")

    with stage_timer("S2"):
        # TODO(P0): trafilatura (default) → rs-trafilatura scale lớn.
        # TODO(P1): pymupdf cho PDF, MinerU cho paper/PDF-like HTML.
        # Extract tách khỏi crawl (§3.1) — replay được khi đổi extractor.
        extracted_tier.mkdir(parents=True, exist_ok=True)
        mark_done(
            extracted_tier, n_records=0, metadata={"primary": settings.extract.primary}
        )

    log.info("extract_done", out=str(out))


if __name__ == "__main__":
    main()
