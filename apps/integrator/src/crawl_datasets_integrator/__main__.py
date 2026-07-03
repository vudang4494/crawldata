"""S6 — Integrate (§8). Schema align + cross-dedup (Zyda-2) + mix.

Logic thật ở `pipeline.py`. Cross-dedup GLOBAL có ranking (§8.2) — khác S3 per-source.
"""

from __future__ import annotations

from pathlib import Path

import click
from crawl_datasets_common.observability import configure_logging, get_logger
from crawl_datasets_common.settings import load_settings

from .pipeline import run

log = get_logger("integrator")


@click.command()
@click.option("--base", required=True, type=click.Path(path_type=Path))
@click.option("--new", required=True, type=click.Path(path_type=Path))
@click.option("--out", required=True, type=click.Path(path_type=Path))
def main(base: Path, new: Path, out: Path) -> None:
    """Integrate new dataset với base (§8)."""
    configure_logging()
    settings = load_settings()
    log.info(
        "integrate_start",
        base=str(base),
        new=str(new),
        cross_dedup=settings.integrate.cross_dedup,
        source_priority=settings.integrate.source_priority,
    )

    stats = run(base, new, out, settings)

    log.info(
        "integrate_done",
        out=str(out),
        final=stats.final,
        removed_dup=stats.removed_dup,
    )


if __name__ == "__main__":
    main()
