"""Cross-dataset dedup (§8.2, pattern Zyda-2) — MinHash+LSH → connected components.

Gộp base+new, MinHash toàn bộ → graph near-dup → connected components (union-find)
→ mỗi cluster giữ 1 doc theo RANKING PRIORITY nguồn (source_priority). Khác S3
(per-source): đây là GLOBAL có ranking (§8.2), đúng chỗ global dedup được phép.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Any

from crawl_datasets_common.settings import MinHashConfig

_MERSENNE = (1 << 61) - 1
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def record_text(rec: dict[str, Any]) -> str:
    """Rút text so khớp từ record bất kỳ format (§8.1 align)."""
    if isinstance(rec.get("messages"), list):
        return " ".join(str(m.get("content", "")) for m in rec["messages"])
    if isinstance(rec.get("conversations"), list):
        return " ".join(str(c.get("value", "")) for c in rec["conversations"])
    if "output" in rec:
        return f"{rec.get('instruction', '')} {rec.get('output', '')}"
    return str(rec.get("text", ""))


def _h32(data: bytes) -> int:
    return int.from_bytes(hashlib.blake2b(data, digest_size=4).digest(), "big")


def _signature(
    text: str, ab: list[tuple[int, int]], ngram: int
) -> tuple[int, ...] | None:
    words = _WORD_RE.findall(text.lower())
    if not words:
        return None
    grams = (
        {_h32(" ".join(words).encode())}
        if len(words) < ngram
        else {
            _h32(" ".join(words[i : i + ngram]).encode())
            for i in range(len(words) - ngram + 1)
        }
    )
    return tuple(min((a * s + b) % _MERSENNE for s in grams) for a, b in ab)


class _UnionFind:
    def __init__(self, n: int) -> None:
        self._parent = list(range(n))

    def find(self, x: int) -> int:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[max(ra, rb)] = min(ra, rb)


def cross_dedup(
    records: list[dict[str, Any]],
    cfg: MinHashConfig,
    seed: int,
    source_priority: list[str],
) -> tuple[list[dict[str, Any]], int]:
    """Trả (kept_records, removed_count). Mỗi cluster giữ doc nguồn hạng cao nhất."""
    n = len(records)
    ab = [
        (_h32(f"{seed}:a:{i}".encode()) | 1, _h32(f"{seed}:b:{i}".encode()))
        for i in range(cfg.num_hashes)
    ]
    sigs = [_signature(record_text(r), ab, cfg.ngram) for r in records]

    uf = _UnionFind(n)
    buckets: dict[tuple[int, tuple[int, ...]], int] = {}
    for idx, sig in enumerate(sigs):
        if sig is None:
            continue
        for band in range(cfg.bands):
            key = (band, sig[band * cfg.rows : (band + 1) * cfg.rows])
            if key in buckets:
                uf.union(buckets[key], idx)
            else:
                buckets[key] = idx

    rank = {src: i for i, src in enumerate(source_priority)}

    def _rank(i: int) -> tuple[int, int]:
        return (rank.get(str(records[i].get("_source", "")), len(source_priority)), i)

    comps: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        comps[uf.find(i)].append(i)

    kept: list[dict[str, Any]] = []
    removed = 0
    for members in comps.values():
        best = min(members, key=_rank)
        kept.append(records[best])
        removed += len(members) - 1
    return kept, removed
