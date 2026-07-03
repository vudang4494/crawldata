"""S5 build (§7) — clean → SFTRecord → JSONL (+Parquet). License gate fail-closed.

license:unknown → loại khỏi publish (§2/§13). Provenance đầy đủ + stable id (§7.2).
Parquet qua pyarrow (optional) cho HF datasets (columnar, memory-map).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crawl_datasets_common.observability import (
    get_logger,
    record_drop,
    records_total,
    stage_timer,
)
from crawl_datasets_common.schema import Provenance, SFTRecord
from crawl_datasets_common.settings import Settings
from crawl_datasets_common.storage import StorageLayout, mark_done

from .formats import serialize, to_messages

log = get_logger("builder")
_STAGE = "S5"

_pq: Any = None
try:
    import pyarrow as _pa
    import pyarrow.parquet as _pq_mod

    _pq = _pq_mod
except ImportError:  # pragma: no cover
    _pa = None
    _pq = None


@dataclass
class BuildStats:
    seen: int = 0
    built: int = 0
    dropped: Counter[str] = field(default_factory=Counter)


def _iter_records(in_dir: Path) -> Iterator[dict[str, Any]]:
    if not in_dir.exists():
        return
    for f in sorted(in_dir.rglob("*.jsonl")):
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)


def run(in_dir: Path, out_dir: Path, settings: Settings) -> BuildStats:
    """clean shards → dataset/part-00000.jsonl (+ .parquet nếu có pyarrow)."""
    dataset_tier = StorageLayout(root=out_dir).tier("dataset")
    fmt = settings.build.format
    stats = BuildStats()
    rows: list[str] = []
    out_path = dataset_tier / "part-00000.jsonl"

    def _inc(status: str) -> None:
        if records_total is not None:
            records_total.labels(stage=_STAGE, status=status).inc()

    with stage_timer(_STAGE), out_path.open("w", encoding="utf-8") as out_f:
        for rec in _iter_records(in_dir):
            stats.seen += 1
            _inc("in")
            prov_raw = rec.get("prov")
            if not isinstance(prov_raw, dict):
                stats.dropped["no_provenance"] += 1
                record_drop(_STAGE, "no_provenance")  # §0 fail-closed
                continue
            try:
                sft = SFTRecord(
                    id=str(rec["id"]),
                    messages=to_messages(rec),
                    lang=str(rec.get("lang", "und")),
                    quality=rec.get("quality"),
                    prov=Provenance(**prov_raw),
                )
            except (KeyError, ValueError, TypeError):
                stats.dropped["invalid_record"] += 1
                record_drop(_STAGE, "invalid_record")
                continue
            if not sft.is_publishable:  # §2 — license:unknown loại khỏi release
                stats.dropped["license_unknown"] += 1
                record_drop(_STAGE, "license_unknown")
                _inc("dropped")
                continue
            line = json.dumps(serialize(sft, fmt), ensure_ascii=False)
            out_f.write(line + "\n")
            rows.append(line)
            stats.built += 1
            _inc("out")

    parquet = False
    if _pq is not None and _pa is not None and rows:  # pragma: no cover — cần pyarrow
        table = _pa.table({"record": rows})
        _pq.write_table(table, dataset_tier / "part-00000.parquet")
        parquet = True

    mark_done(
        dataset_tier,
        n_records=stats.built,
        metadata={
            "seen": stats.seen,
            "built": stats.built,
            "dropped": dict(stats.dropped),
            "format": fmt,
            "parquet": parquet,
            "pipeline_version": settings.global_.pipeline_version,
        },
    )
    log.info(
        "build_summary", seen=stats.seen, built=stats.built, dropped=dict(stats.dropped)
    )
    return stats
