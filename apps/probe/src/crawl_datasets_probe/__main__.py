"""S0 — Source probe (§2).

Output: `source_profile.json` quyết định cách crawl.
Kiểm tra: robots.txt, sitemap.xml, JS-render, API, content-type, license, rate.
"""

from __future__ import annotations

import json
from pathlib import Path

import click
from crawl_datasets_common.observability import (
    configure_logging,
    get_logger,
    stage_timer,
)
from crawl_datasets_common.schema import UNKNOWN_LICENSE, LicenseTag
from crawl_datasets_common.settings import load_settings

log = get_logger("probe")


@click.command()
@click.option("--url", required=True, help="Source URL to probe")
@click.option("--out", required=True, type=click.Path(path_type=Path))
def main(url: str, out: Path) -> None:
    """Probe a source and emit source_profile.json (skeleton)."""
    configure_logging()
    settings = load_settings()
    log.info("probe_start", url=url, pipeline_version=settings.global_.pipeline_version)

    with stage_timer("S0"):
        # TODO(P0): implement robots/sitemap/JS-detect/license probe.
        # Honor `crawl.respect_robots` (§2 fail-closed).
        # Detect license; nếu không xác định được → UNKNOWN_LICENSE (§2).
        # NOTE: license unknown chỉ giữ ở raw tier audit, KHÔNG vào release.
        out.mkdir(parents=True, exist_ok=True)
        # Chưa xác định license ở skeleton → UNKNOWN_LICENSE (§2: raw tier audit,
        # KHÔNG vào release). `LicenseTag` là Literal nên gán trực tiếp giá trị str.
        detected: LicenseTag = UNKNOWN_LICENSE
        profile = {"url": url, "render": settings.crawl.render, "license": detected}
        (out / "source_profile.json").write_text(json.dumps(profile, indent=2))

    log.info("probe_done", out=str(out))


if __name__ == "__main__":
    main()
