"""Deduplication (§5.4) — exact (sha256) + MinHash+LSH per-source/per-crawl.

Pure-Python P0 (datatrove MinhashDedup là backbone ở scale lớn, §5.4). Hash bằng
blake2b (KHÔNG dùng `hash()` — salted per-process, phá reproducibility §0).
MinHash seed lấy từ global_seed → cùng seed ⇒ cùng signature.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse

_MERSENNE = (1 << 61) - 1
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def content_hash(text: str) -> str:
    """sha256 của NFC text — exact-dup key (chạy đầu, rẻ nhất, §5.4)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def scope_key(source_url: str, scope: str) -> str:
    """§5.4 — dedup per-source (host) / per-crawl. Không global (FineWeb ablation)."""
    host = urlparse(source_url).netloc or source_url
    return f"{scope}:{host}"


def _h32(data: bytes) -> int:
    return int.from_bytes(hashlib.blake2b(data, digest_size=4).digest(), "big")


def _shingles(text: str, ngram: int) -> set[int]:
    words = _WORD_RE.findall(text.lower())
    if not words:
        return set()
    if len(words) < ngram:
        return {_h32(" ".join(words).encode("utf-8"))}
    return {
        _h32(" ".join(words[i : i + ngram]).encode("utf-8"))
        for i in range(len(words) - ngram + 1)
    }


class MinHasher:
    """MinHash signature deterministic (§5.4 params: num_hashes, ngram; seed §0)."""

    def __init__(self, num_hashes: int, ngram: int, seed: int) -> None:
        self.ngram = ngram
        self._ab: list[tuple[int, int]] = [
            (_h32(f"{seed}:a:{i}".encode()) | 1, _h32(f"{seed}:b:{i}".encode()))
            for i in range(num_hashes)
        ]

    def signature(self, text: str) -> tuple[int, ...] | None:
        shingles = _shingles(text, self.ngram)
        if not shingles:
            return None
        return tuple(
            min((a * s + b) % _MERSENNE for s in shingles) for a, b in self._ab
        )


class LSHIndex:
    """LSH banding (§5.4: bands×rows). add_or_is_dup → True nếu near-dup doc đã thấy."""

    def __init__(self, bands: int, rows: int) -> None:
        self.bands = bands
        self.rows = rows
        self._buckets: dict[tuple[str, int, tuple[int, ...]], str] = {}

    def add_or_is_dup(self, scope: str, doc_id: str, sig: tuple[int, ...]) -> bool:
        keys = [
            (scope, band, sig[band * self.rows : (band + 1) * self.rows])
            for band in range(self.bands)
        ]
        if any(k in self._buckets for k in keys):
            return True  # near-dup → drop, giữ doc xuất hiện trước (keep-first)
        for k in keys:
            self._buckets[k] = doc_id
        return False
