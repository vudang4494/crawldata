"""S1 — Crawl (§3)."""

from __future__ import annotations

from pathlib import Path

import click
from crawl_datasets_common.observability import (
    configure_logging,
    get_logger,
    stage_timer,
)
from crawl_datasets_common.settings import load_settings
from crawl_datasets_common.storage import StorageLayout

log = get_logger("crawler")


@click.command()
@click.option("--seeds", required=True, help="Comma-separated seed URLs")
@click.option("--depth", type=int, default=None)
@click.option("--out", required=True, type=click.Path(path_type=Path))
def main(seeds: str, depth: int | None, out: Path) -> None:
    """Crawl seeds → raw HTML/WARC shards (skeleton)."""
    configure_logging()
    settings = load_settings()
    max_depth = depth if depth is not None else settings.crawl.max_depth

    log.info(
        "crawl_start",
        seeds=seeds,
        depth=max_depth,
        render=settings.crawl.render,
        respect_robots=settings.crawl.respect_robots,
    )

    layout = StorageLayout(root=out)
    raw_tier = layout.tier("raw")

    with stage_timer("S1"):
        # TODO(P0): httpx+selectolax static / Scrapy orchestration.
        # TODO(P1): Playwright pool khi settings.crawl.render == "browser".
        # Per-domain Crawl-delay, Bloom filter URL dedup (§3.3).
        # Scrapy JOBDIR hoặc Redis frontier cho resumability.
        raw_tier.mkdir(parents=True, exist_ok=True)
        if not settings.crawl.respect_robots:
            # §2 fail-closed — service refuse to start when this is False.
            msg = "respect_robots must be true (§2 legal gate fail-closed)"
            raise SystemExit(msg)

    log.info("crawl_done", out=str(out))


if __name__ == "__main__":
    main()
