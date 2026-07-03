"""PII scrubbing (§5.5, §11) — VN regex high-recall (fail-closed).

FineWeb tối thiểu: email + public IP. VN thêm: CCCD/CMND (9–12 số), SĐT +84 (§11).
Presidio (NER person/location) là backend optional, nặng (load spaCy) → hook riêng,
KHÔNG auto-init trong pipeline P0.
"""

from __future__ import annotations

import re

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


def redact_pii(text: str, *, vi_regex: bool = True) -> tuple[str, list[str]]:
    """Redact PII bằng regex. Trả (text_đã_redact, các_loại_PII_tìm_thấy).

    vi_regex=False → chỉ email + IP (FineWeb tối thiểu, §5.5).
    """
    found: list[str] = []
    for pattern, tag, name in _RULES:
        if not vi_regex and name in {"phone_vn", "cccd_cmnd"}:
            continue
        text, count = pattern.subn(tag, text)
        if count:
            found.append(name)
    return text, found


def presidio_available() -> bool:
    """True nếu Presidio backend cài sẵn (NER person/location — mở rộng regex)."""
    try:
        import presidio_analyzer  # noqa: F401
    except ImportError:
        return False
    return True
