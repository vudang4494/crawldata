"""Schema + provenance (§7.2).

Stable ID bắt buộc — mọi dedup/removal workflow cần document ID ổn định (§7.2, §13).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Literal, get_args

from pydantic import BaseModel, Field, computed_field

LicenseTag = Literal["cc-by", "cc-by-sa", "cc0", "public-domain", "odc-by", "unknown"]
"""§2 — license:unknown → loại khỏi dataset publish (fail-closed)."""

LICENSE_TAGS: tuple[LicenseTag, ...] = get_args(LicenseTag)
"""Mọi tag hợp lệ. `LicenseTag` là Literal (KHÔNG phải Enum) — không có `.unknown`."""

UNKNOWN_LICENSE: LicenseTag = "unknown"
"""§2/§13 — sentinel license chưa xác định; chỉ giữ ở raw tier để audit."""


def stable_id(*parts: str) -> str:
    """Hash ổn định cho document ID. §7.2 — AddId đầu pipeline."""
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()[:16]


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class Provenance(BaseModel):
    """§0 — mỗi record mang provenance đầy đủ, thiếu → không vào dataset."""

    source_url: str
    crawl_ts: datetime
    license: LicenseTag
    extractor: str
    pipeline_version: str
    seed: int
    filters_passed: list[str] = Field(default_factory=list)
    # §7.1 Phase B — record do LLM sinh (QA) từ source; giữ source_url gốc.
    synthetic: bool = False
    synth_model: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_publishable(self) -> bool:
        """§2/§13 — license:unknown không được publish."""
        return self.license != "unknown"


class SFTRecord(BaseModel):
    """§7.2 — schema chuẩn cho SFT record."""

    id: str
    messages: list[Message]
    lang: str
    quality: float | None = None
    prov: Provenance

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_publishable(self) -> bool:
        """Fail-closed: thiếu provenance hoặc license:unknown → loại."""
        return self.prov.is_publishable


def make_provenance(
    *,
    source_url: str,
    license_: LicenseTag,
    extractor: str,
    pipeline_version: str,
    seed: int,
    filters_passed: list[str],
    crawl_ts: datetime | None = None,
) -> Provenance:
    return Provenance(
        source_url=source_url,
        crawl_ts=crawl_ts or datetime.now(UTC),
        license=license_,
        extractor=extractor,
        pipeline_version=pipeline_version,
        seed=seed,
        filters_passed=filters_passed,
    )
