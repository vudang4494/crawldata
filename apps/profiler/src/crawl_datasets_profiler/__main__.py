"""S4 — Profile + suggestions (§6)."""

from __future__ import annotations

from pathlib import Path

import click
from crawl_datasets_common.observability import (
    configure_logging,
    get_logger,
    stage_timer,
)

log = get_logger("profiler")


@click.command()
@click.option("--in", "in_", required=True, type=click.Path(path_type=Path))
@click.option("--out", required=True, type=click.Path(path_type=Path))
def main(in_: Path, out: Path) -> None:
    """Profile clean shards → profile_report.json + suggestions (skeleton)."""
    configure_logging()
    log.info("profile_start", in_path=str(in_), out=str(out))

    with stage_timer("S4"):
        # TODO(P1):
        # - Histogram: doc length, lang, quality, symbol ratio, domain, license, ppl.
        # - Outlier detection trên length/repetition/ppl.
        # - BGE-M3 embed (4090) → UMAP → HDBSCAN hoặc BERTopic.
        # - Dedup rate audit.
        # - Rule-based suggestion engine.
        out.mkdir(parents=True, exist_ok=True)
        (out / "profile_report.json").write_text("{}")

    log.info("profile_done", out=str(out))


if __name__ == "__main__":
    main()
