"""S3 — Clean + filter (§5). Core pipeline.

Order (FineWeb ablation, §5):
  NFC → ftfy → GlotLID → Gopher quality → C4 → FineWeb custom
  → MinHash dedup (per-source/per-crawl) → PII → Decontamination

VN overrides (§5.3, §11): use_vi_stopwords, disable_word_len_rule.
"""

from __future__ import annotations

from pathlib import Path

import click
from crawl_datasets_common.observability import (
    configure_logging,
    get_logger,
    stage_timer,
)
from crawl_datasets_common.settings import load_settings
from crawl_datasets_common.storage import StorageLayout, mark_done

log = get_logger("cleaner")


@click.command()
@click.option("--in", "in_", required=True, type=click.Path(path_type=Path))
@click.option("--out", required=True, type=click.Path(path_type=Path))
def main(in_: Path, out: Path) -> None:
    """Run clean + filter pipeline on extracted shards (skeleton)."""
    configure_logging()
    settings = load_settings()
    log.info(
        "clean_start",
        lang_id=settings.clean.lang_id,
        lang_allow=settings.clean.lang_allow,
        minhash_scope=settings.clean.minhash.scope,
        vi_overrides=settings.clean.vi_overrides.model_dump(),
    )

    layout = StorageLayout(root=out)
    clean_tier = layout.tier("clean")

    # Fail-closed guards (§13)
    if settings.clean.minhash.scope == "global":
        msg = (
            "minhash.scope == 'global' violates §5.4 — must be per_source or per_crawl"
        )
        raise SystemExit(msg)

    with stage_timer("S3"):
        # TODO(P0): datatrove backbone.
        # 1. NFC normalize (§5.1) — bắt buộc trước mọi hash/dedup.
        # 2. ftfy.fix_text().
        # 3. GlotLID-M v3 LID (§5.2) — drop nếu lang_score < lang_score_min[lang].
        # 4. Gopher quality (§5.3) — áp dụng VI overrides cho lang="vi".
        # 5. C4 filters (subset) + FineWeb custom.
        # 6. MinHash dedup per_source (FineWeb ablation).
        # 7. Presidio PII + VN regex (CCCD/CMND/SĐT +84) (§11).
        # 8. Decontamination vs benchmarks list (§5.6).
        clean_tier.mkdir(parents=True, exist_ok=True)
        mark_done(
            clean_tier,
            n_records=0,
            metadata={
                "lang_id": settings.clean.lang_id,
                "minhash_scope": settings.clean.minhash.scope,
            },
        )

    log.info("clean_done", out=str(out))


if __name__ == "__main__":
    main()
