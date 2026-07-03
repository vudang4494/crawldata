"""Schema contract — §7.2 SFTRecord + Provenance."""

from __future__ import annotations

import pytest
from crawl_datasets_common.schema import (
    Message,
    Provenance,
    SFTRecord,
    make_provenance,
    stable_id,
)
from pydantic import ValidationError


def _record(**overrides: object) -> SFTRecord:
    prov = make_provenance(
        source_url="https://example.com/a",
        license_="cc-by",
        extractor="trafilatura-2.1.0",
        pipeline_version="1.3.0",
        seed=42,
        filters_passed=["gopher", "c4"],
    )
    rec = SFTRecord(
        id=stable_id("hello world"),
        messages=[
            Message(role="user", content="hi"),
            Message(role="assistant", content="hello"),
        ],
        lang="vi",
        prov=prov,
    )
    return rec.model_copy(update=overrides)  # type: ignore[arg-type]


def test_stable_id_is_deterministic() -> None:
    assert stable_id("a", "b") == stable_id("a", "b")
    assert stable_id("a", "b") != stable_id("a", "c")


def test_publishable_when_license_known() -> None:
    assert _record().is_publishable is True


def test_unknown_license_not_publishable() -> None:
    """§2 — license:unknown → loại khỏi dataset publish."""
    rec = _record(
        prov=make_provenance(
            source_url="https://example.com/a",
            license_="unknown",
            extractor="x",
            pipeline_version="1.3.0",
            seed=1,
            filters_passed=[],
        )
    )
    assert rec.is_publishable is False


def test_license_literal_tags() -> None:
    # Literal-validate qua Provenance (Pydantic check).
    with pytest.raises(ValidationError):
        Provenance(  # type: ignore[call-arg]
            source_url="x",
            crawl_ts="2026-01-01",
            license="proprietary",  # type: ignore[arg-type]
            extractor="x",
            pipeline_version="1.3.0",
            seed=1,
            filters_passed=[],
        )


def test_filters_passed_must_be_list() -> None:
    with pytest.raises(ValidationError):
        Provenance(  # type: ignore[call-arg]
            source_url="x",
            crawl_ts="2026-01-01",
            license="cc-by",
            extractor="x",
            pipeline_version="1.3.0",
            seed=1,
            filters_passed="oops",  # type: ignore[arg-type]
        )
