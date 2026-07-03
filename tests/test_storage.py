"""Storage + checkpointing."""

from __future__ import annotations

from pathlib import Path

from crawl_datasets_common.storage import (
    SUCCESS_MARKER,
    StorageLayout,
    is_done,
    mark_done,
    pending_shards,
)


def test_storage_layout_tiers(tmp_path: Path) -> None:
    layout = StorageLayout(root=tmp_path)
    assert layout.raw == tmp_path / "raw"
    assert layout.extracted == tmp_path / "extracted"
    assert layout.clean == tmp_path / "clean"
    assert layout.dataset == tmp_path / "dataset"


def test_mark_done_writes_success_and_manifest(tmp_path: Path) -> None:
    shard = tmp_path / "shard_0001"
    mark_done(shard, n_records=42, metadata={"foo": "bar"})
    assert (shard / SUCCESS_MARKER).exists()
    assert is_done(shard)
    manifest = (shard / "manifest.json").read_text()
    assert "42" in manifest and "foo" in manifest


def test_pending_shards_skips_done(tmp_path: Path) -> None:
    a = tmp_path / "a"
    a.mkdir()
    mark_done(a, n_records=1)
    assert pending_shards(tmp_path, ["a", "b"]) == ["b"]
