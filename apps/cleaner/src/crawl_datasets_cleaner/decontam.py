"""Decontamination (§5.6) — loại doc gần-trùng test set benchmark (chống leak).

13-gram substring match kiểu GPT-3 (§5.6). Benchmark n-grams nạp từ ngoài (MMLU,
AIME, MATH-500, MGSM…); chưa nạp → no-op (nhưng mechanism thật, có test).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def word_ngrams(text: str, n: int) -> Iterator[str]:
    words = _WORD_RE.findall(text.lower())
    for i in range(len(words) - n + 1):
        yield " ".join(words[i : i + n])


class Decontaminator:
    """§5.6 — drop doc nếu chứa n-gram trùng benchmark test set."""

    def __init__(
        self, ngram: int = 13, benchmark_ngrams: set[str] | None = None
    ) -> None:
        self.ngram = ngram
        self._bench: set[str] = benchmark_ngrams or set()

    @classmethod
    def from_texts(cls, ngram: int, texts: Iterable[str]) -> Decontaminator:
        bench: set[str] = set()
        for t in texts:
            bench.update(word_ngrams(t, ngram))
        return cls(ngram=ngram, benchmark_ngrams=bench)

    @property
    def active(self) -> bool:
        return bool(self._bench)

    def is_contaminated(self, text: str) -> bool:
        if not self._bench:
            return False
        return any(g in self._bench for g in word_ngrams(text, self.ngram))
