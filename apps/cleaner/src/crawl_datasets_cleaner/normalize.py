"""Normalization (§5.1) — NFC bắt buộc trước MỌI hash/dedup (§5.1, §11).

Tiếng Việt: cùng một chữ có nhiều dạng Unicode → không NFC thì dedup/so khớp sai.
ftfy sửa mojibake (optional backend, fallback identity nếu chưa cài).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

_fix_text: Any = None
try:  # ftfy là optional (§5.1 finishing) — skeleton chạy được khi thiếu
    import ftfy

    _fix_text = ftfy.fix_text
except ImportError:  # pragma: no cover
    _fix_text = None

# zero-width + soft-hyphen → xoá (hỏng dedup nếu để lại)
_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍﻿­"), None)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_INLINE_WS_RE = re.compile(r"[ \t]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")


def has_ftfy() -> bool:
    """True nếu backend ftfy sẵn sàng (để observability/report)."""
    return _fix_text is not None


def normalize_text(text: str) -> str:
    """ftfy (nếu có) → NFC → xoá control/zero-width → chuẩn whitespace.

    NFC PHẢI chạy trước khi văn bản được hash/dedup ở bước sau (§5.1).
    """
    if _fix_text is not None:
        text = _fix_text(text)
    text = unicodedata.normalize("NFC", text)
    text = text.translate(_ZERO_WIDTH)
    text = _CONTROL_RE.sub("", text)
    text = _INLINE_WS_RE.sub(" ", text)
    text = _MULTI_NL_RE.sub("\n\n", text)
    return text.strip()
