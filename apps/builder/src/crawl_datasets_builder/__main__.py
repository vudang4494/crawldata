"""S5 — Build dataset (§7). clean → SFTRecord → JSONL/Parquet.

Logic ở `pipeline.py`. license:unknown loại khỏi release (§2); provenance + stable id.
"""

from __future__ import annotations

from pathlib import Path

import click
from crawl_datasets_common.observability import configure_logging, get_logger
from crawl_datasets_common.settings import load_settings

from .pipeline import run

log = get_logger("builder")


@click.command()
@click.option("--in", "in_", required=True, type=click.Path(path_type=Path))
@click.option("--out", required=True, type=click.Path(path_type=Path))
def main(in_: Path, out: Path) -> None:
    """Build SFT dataset from clean shards (§7)."""
    configure_logging()
    settings = load_settings()
    log.info(
        "build_start",
        format=settings.build.format,
        pipeline_version=settings.global_.pipeline_version,
        in_path=str(in_),
    )

    stats = run(in_, out, settings)

    log.info("build_done", out=str(out), built=stats.built)


if __name__ == "__main__":
    main()
