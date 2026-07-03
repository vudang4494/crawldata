"""S6 integrate pipeline (§8) — align + cross-dedup (Zyda-2) + mix → integrated dataset.

1. Schema align (§8.1): gán _source label cho base/new (theo source_priority).
2. Cross-dedup (§8.2): MinHash+LSH global → components → giữ nguồn hạng cao.
3. Mix (§8.3): dedup TRƯỚC khi tính ratio; cân theo token; ghi mix_manifest.json.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crawl_datasets_common.observability import get_logger, stage_timer
from crawl_datasets_common.settings import Settings

from .crossdedup import cross_dedup
from .mix import mix

log = get_logger("integrator")


@dataclass
class IntegrateStats:
    base: int = 0
    new: int = 0
    after_dedup: int = 0
    removed_dup: int = 0
    final: int = 0
    manifest: dict[str, Any] = field(default_factory=dict)


def _load(in_dir: Path, source: str) -> Iterator[dict[str, Any]]:
    if not in_dir.exists():
        return
    for f in sorted(in_dir.rglob("*.jsonl")):
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rec = json.loads(line)
                    rec["_source"] = source  # §8.1 gán nhãn nguồn cho ranking
                    yield rec


def run(
    base_dir: Path, new_dir: Path, out_dir: Path, settings: Settings
) -> IntegrateStats:
    """Integrate new vào base → integrated/part-00000.jsonl + mix_manifest.json."""
    cfg = settings.integrate
    priority = cfg.source_priority
    base_src = priority[0] if priority else "base"
    new_src = priority[1] if len(priority) > 1 else "new"

    base_recs = list(_load(base_dir, base_src))
    new_recs = list(_load(new_dir, new_src))
    stats = IntegrateStats(base=len(base_recs), new=len(new_recs))
    out_dir.mkdir(parents=True, exist_ok=True)

    with stage_timer("S6"):
        merged = base_recs + new_recs
        if cfg.cross_dedup:
            merged, removed = cross_dedup(
                merged, settings.clean.minhash, settings.global_.seed, priority
            )
            stats.removed_dup = removed
        stats.after_dedup = len(merged)

        selected, manifest = mix(merged, cfg.mix_ratios, settings.global_.seed)
        stats.final = len(selected)
        stats.manifest = manifest

        out_path = out_dir / "part-00000.jsonl"
        with out_path.open("w", encoding="utf-8") as out_f:
            for rec in selected:
                rec.pop("_source", None)
                out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        (out_dir / "mix_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    log.info(
        "integrate_summary",
        base=stats.base,
        new=stats.new,
        removed_dup=stats.removed_dup,
        final=stats.final,
    )
    return stats
