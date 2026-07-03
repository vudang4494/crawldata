"""License detection (§2) — dùng chung S0 probe + S2 extract ("ghi license từ S0/S2").

Fail-closed: không marker CC/PD/ODC rõ ràng → UNKNOWN_LICENSE (chỉ raw tier audit).
"""

from __future__ import annotations

import re

from .schema import UNKNOWN_LICENSE, LicenseTag

_LICENSE_PATTERNS: dict[LicenseTag, tuple[str, ...]] = {
    "cc0": (r"creativecommons\.org/publicdomain/zero", r"\bcc0\b"),
    "public-domain": (r"creativecommons\.org/publicdomain/mark", r"public domain"),
    "cc-by": (r"creativecommons\.org/licenses/by", r"\bcc[ -]by\b"),
    "odc-by": (r"opendatacommons\.org/licenses/by", r"\bodc[ -]by\b"),
}


def detect_license(text: str, headers: dict[str, str] | None = None) -> LicenseTag:
    """§2 fail-closed — không có marker rõ ràng → UNKNOWN_LICENSE."""
    haystack = text.lower()
    if headers:
        haystack += " " + " ".join(headers.values()).lower()
    for tag, patterns in _LICENSE_PATTERNS.items():
        if any(re.search(p, haystack) for p in patterns):
            return tag
    return UNKNOWN_LICENSE
