"""Language ID (§5.2). GlotLID-M v3 default (đa ngữ + low-resource), fallback heuristic.

GlotLID = model fasttext trên HF (cis-lmu/glotlid). Không auto-download: chỉ load khi
env `GLOTLID_MODEL` trỏ model.bin (tránh network trong test/CI). Không có → heuristic
VN/EN (placeholder P0; score đủ để test threshold lang_score_min §5.2/§5.3).
"""

from __future__ import annotations

import os
import re
from typing import Any

from .filters import EN_STOPWORDS, VN_STOPWORDS

# ký tự đặc trưng tiếng Việt (đã NFC) — phân biệt VN với ngôn ngữ gần.
_VN_CHARS = frozenset(
    "ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ"
)
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _heuristic(text: str) -> tuple[str, float]:
    letters = [c for c in text.lower() if c.isalpha()]
    if not letters:
        return ("und", 0.0)
    vn_ratio = sum(1 for c in letters if c in _VN_CHARS) / len(letters)
    words = {w.lower() for w in _WORD_RE.findall(text)}
    if vn_ratio > 0.02:
        return ("vi", 0.9)
    if words & VN_STOPWORDS:
        return ("vi", 0.7)
    ascii_ratio = sum(1 for c in letters if c.isascii()) / len(letters)
    if ascii_ratio > 0.9:
        return ("en", 0.9 if words & EN_STOPWORDS else 0.65)
    return ("und", 0.3)


def _try_load_glotlid() -> Any:
    path = os.environ.get("GLOTLID_MODEL")
    if not path:
        return None
    try:  # opt-in — chỉ khi có model path
        import fasttext

        return fasttext.load_model(path)
    except (ImportError, ValueError, OSError):  # pragma: no cover
        return None


class LanguageIdentifier:
    """§5.2 — detect(text) → (lang, score). Filter theo lang_score_min ở pipeline."""

    def __init__(self, backend: str = "glotlid") -> None:
        self.backend = backend
        self._model = _try_load_glotlid() if backend == "glotlid" else None

    @property
    def using_glotlid(self) -> bool:
        return self._model is not None

    def detect(self, text: str) -> tuple[str, float]:
        if self._model is not None:  # pragma: no cover — cần model file
            labels, probs = self._model.predict(text.replace("\n", " "), k=1)
            lang = labels[0].removeprefix("__label__").split("_")[0]
            return (lang, float(probs[0]))
        return _heuristic(text)
