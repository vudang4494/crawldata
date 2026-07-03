"""Provenance helpers — đảm bảo mỗi record có provenance đầy đủ (§0).

Thiếu bất kỳ field nào trong `source_url, crawl_ts, license, extractor,
pipeline_version, filters_passed[]` → không vào dataset.
"""

from __future__ import annotations

from typing import Any

REQUIRED_FIELDS: tuple[str, ...] = (
    "source_url",
    "crawl_ts",
    "license",
    "extractor",
    "pipeline_version",
    "filters_passed",
)


class ProvenanceError(ValueError):
    """Raised khi record thiếu provenance bắt buộc. Fail-closed (§0)."""


def verify_provenance(prov: dict[str, Any]) -> None:
    """Verify record có đủ provenance. Thiếu → raise (không silently pass)."""
    missing = [f for f in REQUIRED_FIELDS if f not in prov or prov[f] is None]
    if missing:
        msg = f"record missing required provenance fields: {missing}"
        raise ProvenanceError(msg)
    if not isinstance(prov["filters_passed"], list):
        msg = "filters_passed must be a list"
        raise ProvenanceError(msg)
