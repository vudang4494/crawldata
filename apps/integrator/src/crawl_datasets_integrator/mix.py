"""Mixing / balancing (§8.3) — cân theo TOKEN (không theo #doc), reproducible.

Dedup TRƯỚC khi tính ratio (§8.3). VN low-resource dễ bị English lấn → cân theo token
để giữ đúng mix_ratios. Ghi mix_manifest.json (nguồn → token → ratio → seed).
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .crossdedup import record_text

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _tokens(rec: dict[str, Any]) -> int:
    return len(_WORD_RE.findall(record_text(rec)))


def _lang(rec: dict[str, Any]) -> str:
    meta = rec.get("meta", {})
    return str(meta.get("lang", rec.get("lang", "und")))


def mix(
    records: list[dict[str, Any]], mix_ratios: dict[str, float], seed: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Chọn subset để token-share per lang ≈ mix_ratios. Deterministic (giữ thứ tự)."""
    by_lang: dict[str, list[dict[str, Any]]] = defaultdict(list)
    tok_by_lang: dict[str, int] = defaultdict(int)
    for rec in records:
        lg = _lang(rec)
        by_lang[lg].append(rec)
        tok_by_lang[lg] += _tokens(rec)

    # Tổng token khả thi T bị chặn bởi lang thiếu nhất so với ratio của nó.
    langs = [
        lg for lg in mix_ratios if mix_ratios[lg] > 0 and tok_by_lang.get(lg, 0) > 0
    ]
    if not langs:
        return records, {
            "seed": seed,
            "note": "no matching langs",
            "docs": len(records),
        }
    total = min(tok_by_lang[lg] / mix_ratios[lg] for lg in langs)

    selected: list[dict[str, Any]] = []
    per_lang: dict[str, dict[str, Any]] = {}
    for lg in langs:
        budget = mix_ratios[lg] * total
        used = docs = 0
        for rec in by_lang[lg]:
            if used >= budget:
                break
            selected.append(rec)
            used += _tokens(rec)
            docs += 1
        per_lang[lg] = {"tokens": used, "docs": docs, "ratio_target": mix_ratios[lg]}

    grand_total = sum(int(v["tokens"]) for v in per_lang.values()) or 1
    for v in per_lang.values():
        v["ratio_real"] = round(int(v["tokens"]) / grand_total, 3)
    manifest = {"seed": seed, "total_tokens": grand_total, "langs": per_lang}
    return selected, manifest
