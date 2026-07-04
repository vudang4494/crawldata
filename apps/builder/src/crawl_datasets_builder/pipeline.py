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
from crawl_datasets_common.schema import Message, Provenance, SFTRecord, stable_id
from crawl_datasets_common.settings import Settings
from crawl_datasets_common.storage import StorageLayout, mark_done

from .formats import serialize, to_messages
from .synth import QASynthesizer, build_synthesizer

log = get_logger("builder")
_STAGE = "S5"

_pa: Any = None
_pq: Any = None
try:
    import pyarrow as _pa_mod
    import pyarrow.parquet as _pq_mod

    _pa = _pa_mod
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


def run(
    in_dir: Path,
    out_dir: Path,
    settings: Settings,
    synthesizer: QASynthesizer | None = None,
) -> BuildStats:
    """clean shards → dataset/part-00000.jsonl (+ .parquet nếu có pyarrow).

    `build.synth.enabled` (§7.1 Phase B): mỗi doc → LLM sinh cặp QA thay vì
    wrap text; `synthesizer` inject được cho test (mặc định build từ config —
    raise fail-closed nếu bật mà thiếu backend).
    """
    dataset_tier = StorageLayout(root=out_dir).tier("dataset")
    fmt = settings.build.format
    if synthesizer is None:
        synthesizer = build_synthesizer(settings.build.synth, settings.agent)
    stats = BuildStats()
    rows: list[str] = []
    out_path = dataset_tier / "part-00000.jsonl"

    def _inc(status: str) -> None:
        if records_total is not None:
            records_total.labels(stage=_STAGE, status=status).inc()

    def _emit(sft: SFTRecord, out_f: Any) -> None:
        line = json.dumps(serialize(sft, fmt), ensure_ascii=False)
        out_f.write(line + "\n")
        rows.append(line)
        stats.built += 1
        _inc("out")

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
                prov = Provenance(**prov_raw)
            except (ValueError, TypeError):
                stats.dropped["invalid_record"] += 1
                record_drop(_STAGE, "invalid_record")
                continue
            # §2 — license gate TRƯỚC khi build/sinh (không tốn inference
            # cho doc sẽ bị loại khỏi release).
            if not prov.is_publishable:
                stats.dropped["license_unknown"] += 1
                record_drop(_STAGE, "license_unknown")
                _inc("dropped")
                continue
            if synthesizer is None:
                try:
                    sft = SFTRecord(
                        id=str(rec["id"]),
                        messages=to_messages(rec),
                        lang=str(rec.get("lang", "und")),
                        quality=rec.get("quality"),
                        prov=prov,
                    )
                except (KeyError, ValueError, TypeError):
                    stats.dropped["invalid_record"] += 1
                    record_drop(_STAGE, "invalid_record")
                    continue
                _emit(sft, out_f)
                continue
            # §7.1 Phase B — LLM sinh QA; lỗi per-doc → drop, không chặn run.
            try:
                pairs = synthesizer.generate(str(rec.get("text", "")))
            except RuntimeError as exc:  # SynthError / LLM không phản hồi
                stats.dropped["synth_failed"] += 1
                record_drop(_STAGE, "synth_failed")
                log.warning("synth_failed", id=rec.get("id"), error=str(exc))
                _inc("dropped")
                continue
            synth_prov = prov.model_copy(
                update={"synthetic": True, "synth_model": synthesizer.model}
            )
            for i, (question, answer) in enumerate(pairs):
                sft = SFTRecord(
                    id=stable_id(str(rec.get("id", "")), str(i)),
                    messages=[
                        Message(role="user", content=question),
                        Message(role="assistant", content=answer),
                    ],
                    lang=str(rec.get("lang", "und")),
                    quality=rec.get("quality"),
                    prov=synth_prov,
                )
                _emit(sft, out_f)

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
            "synth": synthesizer is not None,  # §7.1 Phase B
            "pipeline_version": settings.global_.pipeline_version,
        },
    )
    log.info(
        "build_summary", seen=stats.seen, built=stats.built, dropped=dict(stats.dropped)
    )
    return stats
