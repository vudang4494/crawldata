"""S3 — Clean + filter (§5). Core pipeline entrypoint.

Order (FineWeb ablation, §5): NFC → ftfy → LID → Gopher rep → Gopher quality → C4
→ FineWeb custom → exact + MinHash dedup (per-source) → PII → Decontamination.
VN overrides (§5.3, §11): use_vi_stopwords, disable_word_len_rule.

Logic thật ở `pipeline.py`; file này chỉ wiring CLI + fail-closed guard.
"""

from __future__ import annotations

from pathlib import Path

import click
from crawl_datasets_common.observability import configure_logging, get_logger
from crawl_datasets_common.settings import load_settings

from .pipeline import run

log = get_logger("cleaner")


@click.command()
@click.option("--in", "in_", required=True, type=click.Path(path_type=Path))
@click.option("--out", required=True, type=click.Path(path_type=Path))
def main(in_: Path, out: Path) -> None:
    """Run clean + filter pipeline (§5) on extracted shards."""
    configure_logging()
    settings = load_settings()

    # Fail-closed guard (§5.4/§13). Pydantic đã chặn ở load; giữ đây phòng thủ 2 lớp.
    if settings.clean.minhash.scope not in {"per_source", "per_crawl"}:
        raise SystemExit(
            f"minhash.scope={settings.clean.minhash.scope!r} vi phạm §5.4 "
            "— phải per_source/per_crawl (không global)"
        )

    log.info(
        "clean_start",
        lang_id=settings.clean.lang_id,
        lang_allow=settings.clean.lang_allow,
        minhash_scope=settings.clean.minhash.scope,
        vi_overrides=settings.clean.vi_overrides.model_dump(),
    )

    stats = run(in_, out, settings)

    log.info("clean_done", out=str(out), seen=stats.seen, kept=stats.kept)


if __name__ == "__main__":
    main()
