"""S0 — Source probe (§2). Fetch robots/page/sitemap → source_profile.json.

Logic thật ở `pipeline.py`. Quyết định điều khiển S1: render, crawl_delay, seed URLs,
license gate (§2 fail-closed: license:unknown chỉ giữ raw tier audit).
"""

from __future__ import annotations

from pathlib import Path

import click
from crawl_datasets_common.observability import configure_logging, get_logger
from crawl_datasets_common.settings import load_settings

from .pipeline import run

log = get_logger("probe")


@click.command()
@click.option("--url", required=True, help="Source URL to probe")
@click.option("--out", required=True, type=click.Path(path_type=Path))
def main(url: str, out: Path) -> None:
    """Probe a source and emit source_profile.json (§2)."""
    configure_logging()
    settings = load_settings()
    log.info("probe_start", url=url, pipeline_version=settings.global_.pipeline_version)

    profile = run(url, out, settings)

    log.info("probe_done", out=str(out), render=profile.render, license=profile.license)


if __name__ == "__main__":
    main()
