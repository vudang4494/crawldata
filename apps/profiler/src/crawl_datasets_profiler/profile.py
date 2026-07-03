"""Distribution profiling + suggestions (§6) — trên clean records.

Histogram (length/lang/license/domain/PII), anomaly (near-empty/outlier), rule-based
suggestion engine. Clustering (BGE-M3→UMAP→HDBSCAN) là P1 — hook để mở rộng.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse

_WORD_RE = re.compile(r"\w+", re.UNICODE)
_LEN_BUCKETS = ((0, 50), (50, 200), (200, 1000), (1000, 5000))


def _bucket(n: int) -> str:
    for lo, hi in _LEN_BUCKETS:
        if lo <= n < hi:
            return f"{lo}-{hi}"
    return "5000+"


@dataclass
class Profile:
    n_docs: int = 0
    lang_dist: dict[str, int] = field(default_factory=dict)
    license_dist: dict[str, int] = field(default_factory=dict)
    domain_dist: dict[str, int] = field(default_factory=dict)
    length_stats: dict[str, float] = field(default_factory=dict)
    length_histogram: dict[str, int] = field(default_factory=dict)
    pii_dist: dict[str, int] = field(default_factory=dict)
    anomalies: dict[str, int] = field(default_factory=dict)
    suggestions: list[str] = field(default_factory=list)
    # §6 clustering (P1) — đúng 1 trong 2 khác None (skip-reason fail-visible).
    clustering: dict[str, Any] | None = None
    clustering_skipped: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_profile(records: Iterable[Mapping[str, Any]]) -> Profile:
    """Một lượt qua clean records → Profile + suggestions (§6)."""
    lang: Counter[str] = Counter()
    lic: Counter[str] = Counter()
    dom: Counter[str] = Counter()
    hist: Counter[str] = Counter()
    pii: Counter[str] = Counter()
    lengths: list[int] = []
    near_empty = 0

    for rec in records:
        prov = rec.get("prov", {})
        n = len(_WORD_RE.findall(str(rec.get("text", ""))))
        lengths.append(n)
        if n < 50:
            near_empty += 1
        hist[_bucket(n)] += 1
        lang[str(rec.get("lang", "und"))] += 1
        lic[str(prov.get("license", "unknown"))] += 1
        dom[urlparse(str(prov.get("source_url", ""))).netloc or "?"] += 1
        for p in rec.get("pii_found", []) or []:
            pii[str(p)] += 1

    prof = Profile(
        n_docs=len(lengths),
        lang_dist=dict(lang),
        license_dist=dict(lic),
        domain_dist=dict(dom.most_common(50)),
        pii_dist=dict(pii),
        length_histogram=dict(hist),
        anomalies={"near_empty": near_empty},
    )
    if lengths:
        prof.length_stats = {
            "min": float(min(lengths)),
            "max": float(max(lengths)),
            "mean": round(statistics.fmean(lengths), 1),
            "median": float(statistics.median(lengths)),
        }
    prof.suggestions = _suggest(prof)
    return prof


def _suggest(p: Profile) -> list[str]:
    """Rule trên stats → gợi ý actionable (§6, người duyệt)."""
    out: list[str] = []
    n = p.n_docs or 1
    for host, c in p.domain_dist.items():
        if c / n > 0.8:
            out.append(f"domain '{host}' chiếm {c / n:.0%} — đa dạng hóa nguồn (skew)")
    for lg, c in p.lang_dist.items():
        if c / n > 0.8 and len(p.lang_dist) > 1:
            out.append(
                f"lang '{lg}' chiếm {c / n:.0%} — cân nhắc upsample lang thiểu số"
            )
    unknown = p.license_dist.get("unknown", 0)
    if unknown:
        out.append(f"{unknown} doc license:unknown — sẽ bị loại khỏi release (§2)")
    if p.anomalies.get("near_empty", 0) / n > 0.3:
        out.append("nhiều doc <50 từ — xem lại extractor/Gopher min_words (§5.3)")
    return out
