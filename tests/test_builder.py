"""S5 build (§7) — formats + license gate (§2) + provenance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
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


# --- §7.1 Phase B — synthetic QA ------------------------------------------------


def _synth_settings() -> Settings:
    s = Settings()
    s.build.synth.enabled = True
    s.build.synth.questions_per_doc = 2
    return s


def _write_clean(tmp_path: Path, n: int = 1) -> Path:
    in_dir = tmp_path / "clean"
    in_dir.mkdir()
    (in_dir / "p.jsonl").write_text(
        "\n".join(json.dumps(_clean_rec("cc-by")) for _ in range(n)),
        encoding="utf-8",
    )
    return in_dir


def test_synth_mode_generates_qa_records(tmp_path: Path) -> None:
    from crawl_datasets_builder.synth import QASynthesizer

    s = _synth_settings()
    fake = (
        '{"pairs": [{"question": "Tài liệu nói gì?", "answer": "Nói xin chào."},'
        '{"question": "Ai viết?", "answer": "Không rõ."}]}'
    )
    synth = QASynthesizer(s.build.synth, s.agent, llm=lambda messages: fake)
    stats = run(_write_clean(tmp_path), tmp_path / "out", s, synthesizer=synth)
    assert stats.built == 2  # 1 doc → 2 cặp QA
    recs = [
        json.loads(line)
        for line in (tmp_path / "out" / "dataset" / "part-00000.jsonl")
        .read_text()
        .splitlines()
    ]
    assert [m["role"] for m in recs[0]["messages"]] == ["user", "assistant"]
    assert recs[0]["meta"]["synthetic"] is True
    assert recs[0]["meta"]["synth_model"] == s.agent.model
    assert recs[0]["meta"]["source_url"] == "https://a/1"  # giữ nguồn gốc
    assert recs[0]["meta"]["id"] != recs[1]["meta"]["id"]  # id ổn định per-cặp


def test_synth_bad_json_drops_doc_not_run(tmp_path: Path) -> None:
    from crawl_datasets_builder.synth import QASynthesizer

    s = _synth_settings()
    synth = QASynthesizer(s.build.synth, s.agent, llm=lambda messages: "không JSON")
    stats = run(_write_clean(tmp_path), tmp_path / "out", s, synthesizer=synth)
    assert stats.built == 0 and stats.dropped.get("synth_failed") == 1


def test_synth_retries_bad_json_then_succeeds() -> None:
    from crawl_datasets_builder.synth import QASynthesizer

    s = _synth_settings()
    responses = iter(["rác", '{"pairs": [{"question": "Q?", "answer": "A."}]}'])
    synth = QASynthesizer(s.build.synth, s.agent, llm=lambda m: next(responses))
    assert synth.generate("text") == [("Q?", "A.")]


def test_synth_enabled_without_backend_fails_closed(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from crawl_datasets_common import llm as common_llm

    monkeypatch.setattr(common_llm, "_httpx", None)
    with pytest.raises(RuntimeError, match="httpx"):
        run(_write_clean(tmp_path), tmp_path / "out", _synth_settings())
