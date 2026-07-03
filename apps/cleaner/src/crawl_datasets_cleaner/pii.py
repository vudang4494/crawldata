"""PII scrubbing (§5.5, §11) — VN regex high-recall (fail-closed) + Presidio NER.

FineWeb tối thiểu: email + public IP. VN thêm: CCCD/CMND (9–12 số), SĐT +84 (§11).
Presidio (NER person/location) là backend optional, nặng (load spaCy) → chỉ init khi
`pii.backend == presidio` VÀ cài sẵn (build_presidio → None nếu không).
"""

from __future__ import annotations

import re
from typing import Any

# §5.5/§11 — high-recall cho định danh nhạy cảm.
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_IPV4 = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
_PHONE_VN = re.compile(r"(?<![\d+])(?:\+84|0)\d{9}(?!\d)")
_CCCD = re.compile(r"(?<!\d)(?:\d{12}|\d{9})(?!\d)")  # CCCD 12 / CMND 9

# Thứ tự quan trọng: redact email/IP/phone (nuốt chữ số) trước ID trần.
_RULES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (_EMAIL, "[EMAIL]", "email"),
    (_IPV4, "[IP]", "ip"),
    (_PHONE_VN, "[PHONE]", "phone_vn"),
    (_CCCD, "[ID]", "cccd_cmnd"),
)


class PresidioRedactor:
    """NER-based redaction (person/location/…) — mở rộng regex (§5.5). Lazy spaCy."""

    def __init__(self) -> None:
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine

        # Presidio ship type chưa đầy đủ (__init__ untyped, RecognizerResult của
        # analyzer vs anonymizer là 2 class lệch nhau dù runtime tương thích) —
        # giữ anonymizer duck-typed qua Any, tránh type-ignore lệ thuộc env.
        anonymizer_cls: Any = AnonymizerEngine
        self._analyzer = AnalyzerEngine()
        self._anonymizer = anonymizer_cls()

    def redact(self, text: str) -> tuple[str, list[str]]:
        results = self._analyzer.analyze(text=text, language="en")
        if not results:
            return text, []
        out = self._anonymizer.anonymize(text=text, analyzer_results=results)
        return out.text, sorted({r.entity_type for r in results})


def build_presidio() -> PresidioRedactor | None:
    """Init Presidio nếu cài sẵn; None nếu thiếu backend/model (fallback regex-only)."""
    try:
        return PresidioRedactor()
    except (ImportError, OSError, ValueError, RuntimeError):
        return None


def redact_pii(
    text: str, *, vi_regex: bool = True, presidio: Any = None
) -> tuple[str, list[str]]:
    """Redact PII. Trả (text_redact, loại_PII). Presidio (nếu có) chạy trước regex.

    vi_regex=False → regex chỉ email + IP (FineWeb tối thiểu, §5.5).
    """
    found: list[str] = []
    if presidio is not None:
        text, ner_types = presidio.redact(text)
        found.extend(ner_types)
    for pattern, tag, name in _RULES:
        if not vi_regex and name in {"phone_vn", "cccd_cmnd"}:
            continue
        text, count = pattern.subn(tag, text)
        if count:
            found.append(name)
    return text, found
