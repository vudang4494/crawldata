"""S4 profile (§6) — distribution stats + rule-based suggestions."""

from __future__ import annotations

from typing import Any

from crawl_datasets_profiler.profile import build_profile


def _rec(
    lang: str, lic: str, host: str, words: int, pii: list[str] | None = None
) -> dict[str, Any]:
    return {
        "text": "word " * words,
        "lang": lang,
        "pii_found": pii or [],
        "prov": {"license": lic, "source_url": f"https://{host}/x"},
    }


def test_build_profile_distributions() -> None:
    recs = [
        _rec("en", "cc-by", "a.com", 100),
        _rec("vi", "unknown", "a.com", 100),
        _rec("en", "cc-by", "a.com", 1, pii=["email"]),
    ]
    p = build_profile(recs)
    assert p.n_docs == 3
    assert p.lang_dist == {"en": 2, "vi": 1}
    assert p.license_dist.get("unknown") == 1
    assert p.domain_dist.get("a.com") == 3
    assert p.pii_dist.get("email") == 1
    assert p.length_stats["min"] == 1.0
    assert p.anomalies["near_empty"] == 1  # doc 1 từ


def test_suggestions_flag_skew_and_unknown_license() -> None:
    recs = [_rec("en", "unknown", "only.com", 100) for _ in range(5)]
    sug = build_profile(recs).suggestions
    assert any("only.com" in s for s in sug)  # 100% một domain
    assert any("license:unknown" in s for s in sug)
