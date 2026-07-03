"""S4 — Profile + suggestions (§6). clean → profile_report.json.

Logic thật ở `pipeline.py`. Profiling TRƯỚC build → quyết mix ratio dựa dữ liệu (§8).
"""

from __future__ import annotations

from pathlib import Path

import click
from crawl_datasets_common.observability import configure_logging, get_logger
from crawl_datasets_common.settings import load_settings

from .pipeline import run

log = get_logger("profiler")


@click.command()
@click.option("--in", "in_", required=True, type=click.Path(path_type=Path))
@click.option("--out", required=True, type=click.Path(path_type=Path))
def main(in_: Path, out: Path) -> None:
    """Profile clean shards → profile_report.json + suggestions (§6)."""
    configure_logging()
    settings = load_settings()
    log.info("profile_start", in_path=str(in_), out=str(out))

    profile = run(in_, out, settings)

    log.info("profile_done", out=str(out), n_docs=profile.n_docs)


if __name__ == "__main__":
    main()
