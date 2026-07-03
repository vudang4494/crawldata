"""S5 — Build dataset (§7). Format → schema → Parquet."""

from __future__ import annotations

from pathlib import Path

import click
from crawl_datasets_common.observability import (
    configure_logging,
    get_logger,
    stage_timer,
)
from crawl_datasets_common.schema import LicenseTag, SFTRecord
from crawl_datasets_common.settings import load_settings
from crawl_datasets_common.storage import StorageLayout, mark_done

log = get_logger("builder")


@click.command()
@click.option("--in", "in_", required=True, type=click.Path(path_type=Path))
@click.option("--out", required=True, type=click.Path(path_type=Path))
def main(in_: Path, out: Path) -> None:
    """Build SFT dataset from clean shards (skeleton)."""
    configure_logging()
    settings = load_settings()
    log.info(
        "build_start",
        format=settings.build.format,
        pipeline_version=settings.global_.pipeline_version,
        in_path=str(in_),
    )

    layout = StorageLayout(root=out)
    dataset_tier = layout.tier("dataset")

    with stage_timer("S5"):
        # TODO(P0):
        # 1. JSONL (1 record/dòng, stream được) theo format §7.1.
        # 2. Convert Parquet/Arrow cho HF datasets (§7.1).
        # 3. Mỗi record mang provenance đầy đủ + stable ID (§7.2).
        # 4. License:unknown → loại khỏi dataset publish (§2 fail-closed).
        dataset_tier.mkdir(parents=True, exist_ok=True)
        mark_done(
            dataset_tier,
            n_records=0,
            metadata={"format": settings.build.format},
        )

    # Compile-time check: schema import works (fail-closed guard).
    _ = SFTRecord.model_fields
    _ = LicenseTag  # type narrowing placeholder

    log.info("build_done", out=str(out))


if __name__ == "__main__":
    main()
