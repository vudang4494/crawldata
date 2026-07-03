"""S6 — Integrate (§8). Schema alignment + cross-dedup + mix."""

from __future__ import annotations

from pathlib import Path

import click
from crawl_datasets_common.observability import (
    configure_logging,
    get_logger,
    stage_timer,
)
from crawl_datasets_common.settings import load_settings

log = get_logger("integrator")


@click.command()
@click.option("--base", required=True, type=click.Path(path_type=Path))
@click.option("--new", required=True, type=click.Path(path_type=Path))
@click.option("--out", required=True, type=click.Path(path_type=Path))
def main(base: Path, new: Path, out: Path) -> None:
    """Integrate new dataset với base (skeleton)."""
    configure_logging()
    settings = load_settings()
    log.info(
        "integrate_start",
        base=str(base),
        new=str(new),
        cross_dedup=settings.integrate.cross_dedup,
        source_priority=settings.integrate.source_priority,
    )

    with stage_timer("S6"):
        # TODO(P2):
        # 1. Schema alignment (§8.1) — map mọi nguồn về SFTRecord (§7.2).
        #    Thiếu field bắt buộc → fail-closed.
        # 2. Cross-dataset dedup (§8.2) theo Zyda-2 pattern:
        #    - MinHash+LSH toàn bộ → connected components.
        #    - Mỗi cluster giữ 1 doc theo source_priority ranking.
        # 3. Mixing (§8.3) — dedup TRƯỚC khi tính ratio.
        #    Ghi mix_manifest.json: nguồn → #token → ratio → seed.
        out.mkdir(parents=True, exist_ok=True)
        (out / "mix_manifest.json").write_text("{}")

    log.info("integrate_done", out=str(out))


if __name__ == "__main__":
    main()
