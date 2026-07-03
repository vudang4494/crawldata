"""S1 — Crawl (§3). frontier + fetch + politeness → raw HTML tier.

Logic thật ở `pipeline.py`. Extract tách khỏi crawl (§3.1) — S2 extract từ raw.
"""

from __future__ import annotations

from pathlib import Path

import click
from crawl_datasets_common.observability import configure_logging, get_logger
from crawl_datasets_common.settings import load_settings

from .pipeline import run

log = get_logger("crawler")


@click.command()
@click.option("--seeds", required=True, help="Comma-separated seed URLs")
@click.option("--depth", type=int, default=None)
@click.option("--out", required=True, type=click.Path(path_type=Path))
def main(seeds: str, depth: int | None, out: Path) -> None:
    """Crawl seeds → raw HTML/WARC shards (§3)."""
    configure_logging()
    settings = load_settings()
    if depth is not None:
        settings.crawl.max_depth = depth

    seed_list = [s.strip() for s in seeds.split(",") if s.strip()]
    log.info(
        "crawl_start",
        seeds=seed_list,
        depth=settings.crawl.max_depth,
        render=settings.crawl.render,
        respect_robots=settings.crawl.respect_robots,
    )

    stats = run(seed_list, out, settings)

    log.info("crawl_done", out=str(out), fetched=stats.fetched)


if __name__ == "__main__":
    main()
