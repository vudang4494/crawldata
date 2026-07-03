"""Provenance verify — §0 fail-closed."""

from __future__ import annotations

import pytest
from crawl_datasets_common.provenance import ProvenanceError, verify_provenance


def test_passes_with_all_required_fields() -> None:
    verify_provenance(
        {
            "source_url": "https://x",
            "crawl_ts": "2026-01-01T00:00:00Z",
            "license": "cc-by",
            "extractor": "trafilatura",
            "pipeline_version": "1.3.0",
            "filters_passed": ["gopher"],
        }
    )


def test_fails_when_source_url_missing() -> None:
    with pytest.raises(ProvenanceError, match="source_url"):
        verify_provenance(
            {
                "crawl_ts": "2026-01-01",
                "license": "cc-by",
                "extractor": "x",
                "pipeline_version": "1.3.0",
                "filters_passed": [],
            }
        )


def test_fails_when_filters_passed_not_list() -> None:
    with pytest.raises(ProvenanceError, match="list"):
        verify_provenance(
            {
                "source_url": "x",
                "crawl_ts": "t",
                "license": "cc-by",
                "extractor": "x",
                "pipeline_version": "1.3.0",
                "filters_passed": "string",
            }
        )


def test_fails_when_field_is_none() -> None:
    with pytest.raises(ProvenanceError):
        verify_provenance(
            {
                "source_url": None,  # type: ignore[dict-item]
                "crawl_ts": "t",
                "license": "cc-by",
                "extractor": "x",
                "pipeline_version": "1.3.0",
                "filters_passed": [],
            }
        )
