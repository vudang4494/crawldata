"""S5 build (§7) — formats + license gate (§2) + provenance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from crawl_datasets_builder.formats import serialize
from crawl_datasets_builder.pipeline import run
from crawl_datasets_common.schema import Message, SFTRecord, make_provenance
from crawl_datasets_common.settings import Settings


def _sft(license_: str = "cc-by") -> SFTRecord:
    prov = make_provenance(
        source_url="https://a/1",
        license_=license_,  # type: ignore[arg-type]
        extractor="trafilatura",
        pipeline_version="1.3.0",
        seed=42,
        filters_passed=["gopher"],
    )
    return SFTRecord(
        id="abc",
        messages=[Message(role="assistant", content="doc text")],
        lang="en",
        prov=prov,
    )


def test_serialize_all_formats() -> None:
    sft = _sft()
    assert serialize(sft, "chatml")["messages"][0]["role"] == "assistant"
    assert serialize(sft, "sharegpt")["conversations"][0]["from"] == "gpt"
    assert serialize(sft, "alpaca")["output"] == "doc text"


def _clean_rec(license_: str) -> dict[str, Any]:
    return {
        "id": f"id-{license_}",
        "text": "Hello document.",
        "lang": "en",
        "quality": None,
        "prov": _sft(license_).prov.model_dump(mode="json"),
    }


def test_build_excludes_unknown_license(tmp_path: Path) -> None:
    in_dir = tmp_path / "clean"
    in_dir.mkdir()
    (in_dir / "p.jsonl").write_text(
        "\n".join(json.dumps(_clean_rec(lic)) for lic in ("cc-by", "unknown")),
        encoding="utf-8",
    )
    stats = run(in_dir, tmp_path / "out", Settings())
    assert stats.built == 1  # unknown bị loại (§2)
    assert stats.dropped.get("license_unknown") == 1
    recs = [
        json.loads(line)
        for line in (tmp_path / "out" / "dataset" / "part-00000.jsonl")
        .read_text()
        .splitlines()
    ]
    assert len(recs) == 1
    assert "messages" in recs[0] and recs[0]["meta"]["license"] == "cc-by"
