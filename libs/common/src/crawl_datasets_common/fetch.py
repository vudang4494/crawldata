"""HTTP fetch util (§3) — httpx gated. Trả FetchResult | None (thiếu backend/lỗi).

Tách riêng để S0 probe + S1 crawl inject fetch giả trong test (không network).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_httpx: Any = None
try:
    import httpx

    _httpx = httpx
except ImportError:  # pragma: no cover
    _httpx = None

USER_AGENT = "crawl-datasets/1.3 (+https://example.com/bot)"


@dataclass
class FetchResult:
    url: str
    status: int
    text: str
    headers: dict[str, str] = field(default_factory=dict)


def http_available() -> bool:
    return _httpx is not None


def http_get(
    url: str, *, timeout: float = 10.0
) -> FetchResult | None:  # pragma: no cover
    """GET url qua httpx (nếu có). Lỗi network / thiếu backend → None."""
    if _httpx is None:
        return None
    try:
        resp = _httpx.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            headers={"user-agent": USER_AGENT},
        )
    except Exception:  # network boundary — mọi lỗi fetch → None, stage tự xử lý
        return None
    return FetchResult(
        url=str(resp.url),
        status=resp.status_code,
        text=resp.text,
        headers={k.lower(): v for k, v in resp.headers.items()},
    )
