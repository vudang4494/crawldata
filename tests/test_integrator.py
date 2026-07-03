"""S6 integrate (§8) — cross-dedup (Zyda-2 ranking) + token-based mix."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from crawl_datasets_common.settings import MinHashConfig, Settings
from crawl_datasets_integrator.crossdedup import cross_dedup
from crawl_datasets_integrator.mix import mix
from crawl_datasets_integrator.pipeline import run

_TEXT = (
    "the quick brown fox jumps over the lazy dog many times in the green field today"
)


def _doc(source: str, lang: str = "en", text: str = _TEXT) -> dict[str, Any]:
    return {
        "messages": [{"role": "assistant", "content": text}],
        "meta": {"lang": lang},
        "_source": source,
    }


def test_cross_dedup_keeps_higher_ranked_source() -> None:
    kept, removed = cross_dedup(
        [_doc("crawl_new"), _doc("curated_v2")],
        MinHashConfig(),
        seed=42,
        source_priority=["curated_v2", "crawl_new"],
    )
    assert removed == 1 and len(kept) == 1
    assert kept[0]["_source"] == "curated_v2"  # giữ nguồn hạng cao (§8.2)


def test_mix_downsamples_over_represented_lang() -> None:
    en = [_doc("s", "en", "word " * 100) for _ in range(5)]  # 500 token
    vi = [_doc("s", "vi", "từ " * 10)]  # 10 token
    _, manifest = mix(en + vi, {"en": 0.5, "vi": 0.5}, seed=42)
    assert manifest["langs"]["en"]["tokens"] < 500  # en bị downsample (cân token)
    assert "vi" in manifest["langs"]


def test_integrate_pipeline_dedup_and_manifest(tmp_path: Path) -> None:
    base, new = tmp_path / "base", tmp_path / "new"
    base.mkdir()
    new.mkdir()
    doc = {
        "messages": [{"role": "assistant", "content": _TEXT}],
        "meta": {"lang": "en"},
    }
    (base / "b.jsonl").write_text(json.dumps(doc), encoding="utf-8")
    (new / "n.jsonl").write_text(json.dumps(doc), encoding="utf-8")  # trùng base

    stats = run(base, new, tmp_path / "out", Settings())
    assert stats.base == 1 and stats.new == 1
    assert stats.removed_dup == 1  # cross-dedup loại bản trùng
    assert (tmp_path / "out" / "mix_manifest.json").exists()
    assert (tmp_path / "out" / "part-00000.jsonl").exists()
