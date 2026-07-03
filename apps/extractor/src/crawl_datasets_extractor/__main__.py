"""S2 — Extract (§4). raw HTML/WARC/PDF → extracted JSONL.

Logic thật ở `pipeline.py`; file này chỉ wiring CLI. Extract tách khỏi crawl (§3.1)
→ replay được khi đổi extractor mà không crawl lại.
"""

from __future__ import annotations

from pathlib import Path

import click
from crawl_datasets_common.observability import configure_logging, get_logger
from crawl_datasets_common.settings import load_settings

from .pipeline import run

log = get_logger("extractor")


@click.command()
@click.option("--in", "in_", required=True, type=click.Path(path_type=Path))
@click.option("--out", required=True, type=click.Path(path_type=Path))
def main(in_: Path, out: Path) -> None:
    """Extract text from raw HTML/WARC/PDF → extracted JSONL shards (§4)."""
    configure_logging()
    settings = load_settings()
    log.info(
        "extract_start",
        primary=settings.extract.primary,
        fallback=settings.extract.fallback,
        in_path=str(in_),
        out=str(out),
    )

    stats = run(in_, out, settings)

    log.info("extract_done", out=str(out), seen=stats.seen, extracted=stats.extracted)


if __name__ == "__main__":
    main()
