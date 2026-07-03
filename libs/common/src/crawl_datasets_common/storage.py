"""Storage tiers + per-stage checkpointing (§0).

Tiers (immutable input của tier sau):
  raw/        — HTML/WARC từ S1
  extracted/  — JSONL text+meta từ S2
  clean/      — JSONL post-filter từ S3
  dataset/    — Parquet/Arrow versioned từ S5

Mỗi stage ghi shards + `_SUCCESS` marker + `manifest.json`. Rerun bỏ qua
shard đã có `_SUCCESS` (idempotent).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

SUCCESS_MARKER = "_SUCCESS"
MANIFEST_NAME = "manifest.json"


@dataclass
class StorageLayout:
    root: Path

    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def extracted(self) -> Path:
        return self.root / "extracted"

    @property
    def clean(self) -> Path:
        return self.root / "clean"

    @property
    def dataset(self) -> Path:
        return self.root / "dataset"

    def tier(self, name: str) -> Path:
        """Generic accessor. name in {raw, extracted, clean, dataset}."""
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        return path


@dataclass
class ShardStatus:
    shard_id: str
    path: Path
    success: bool
    n_records: int = 0
    metadata: dict[str, object] = field(default_factory=dict)


def is_done(shard_dir: Path) -> bool:
    """Check idempotent rerun: đã có `_SUCCESS` thì skip."""
    return (shard_dir / SUCCESS_MARKER).exists()


def mark_done(
    shard_dir: Path, *, n_records: int, metadata: dict[str, object] | None = None
) -> None:
    """Ghi `_SUCCESS` + `manifest.json` cho shard. Idempotent."""
    shard_dir.mkdir(parents=True, exist_ok=True)
    (shard_dir / SUCCESS_MARKER).touch()
    manifest = {
        "shard": shard_dir.name,
        "n_records": n_records,
        "metadata": metadata or {},
    }
    (shard_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2)
    )


def list_shards(tier_dir: Path) -> list[Path]:
    """Liệt kê shard subdirs trong một tier, sort theo tên."""
    if not tier_dir.exists():
        return []
    return sorted(p for p in tier_dir.iterdir() if p.is_dir())


def pending_shards(tier_dir: Path, shard_ids: list[str]) -> list[str]:
    """Shards chưa có `_SUCCESS` — cần chạy lại."""
    return [s for s in shard_ids if not is_done(tier_dir / s)]
