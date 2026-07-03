"""JS-render (§3.2, P1) — Playwright gated backend cho site render:browser.

Browser đắt 10–50× so với HTTP (§3.1) nên chỉ dùng khi config `crawl.render`
yêu cầu; block image/font/media để tiết kiệm (§3.2/§9.1); tái dùng browser
context. Thiếu Playwright → `build_renderer()` trả None (caller quyết định
fail-closed hay chạy tiếp http-only theo mode).
"""

from __future__ import annotations

import re
from typing import Any

from crawl_datasets_common.fetch import FetchResult
from crawl_datasets_common.observability import get_logger

log = get_logger("crawler.render")

_playwright: Any = None
try:
    from playwright.sync_api import sync_playwright as _pw_mod

    _playwright = _pw_mod
except ImportError:  # pragma: no cover
    _playwright = None

_TAG_RE = re.compile(r"<[^>]+>")
_EMPTY_ROOT_RE = re.compile(
    r'<div[^>]*id=["\']?(?:root|app)["\']?[^>]*>\s*</div>', re.IGNORECASE
)
_BLOCKED_RESOURCES = frozenset({"image", "font", "media"})


def needs_render(html: str, min_text_len: int) -> bool:
    """§3.2 auto: text sau strip-tag < threshold HOẶC root SPA rỗng → escalate."""
    text_len = len(_TAG_RE.sub(" ", html).strip())
    return text_len < min_text_len or bool(_EMPTY_ROOT_RE.search(html))


class BrowserRenderer:  # pragma: no cover — cần browser thật; logic ở needs_render
    """Playwright pool tối giản: 1 chromium headless, context tái dùng (§3.2)."""

    def __init__(self) -> None:
        if _playwright is None:
            raise RuntimeError("playwright chưa cài (§3.2 render:browser)")
        self._pw = _playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._context = self._browser.new_context()

    def render(self, url: str) -> FetchResult | None:
        page = self._context.new_page()
        try:
            page.route("**/*", _block_heavy_resources)
            resp = page.goto(url, wait_until="networkidle")
            return FetchResult(
                url=url,
                status=resp.status if resp is not None else 200,
                text=page.content(),
                headers=dict(resp.headers) if resp is not None else {},
            )
        finally:
            page.close()

    def close(self) -> None:
        self._context.close()
        self._browser.close()
        self._pw.stop()


def _block_heavy_resources(route: Any) -> None:  # pragma: no cover
    if route.request.resource_type in _BLOCKED_RESOURCES:
        route.abort()
    else:
        route.continue_()


def build_renderer() -> BrowserRenderer | None:
    """Init Playwright nếu sẵn sàng; None nếu thiếu backend/browser (log rõ)."""
    if _playwright is None:
        return None
    try:
        return BrowserRenderer()
    except Exception as exc:  # pragma: no cover — launch fail (chưa playwright install)
        log.warning("render_backend_unavailable", error=str(exc))
        return None
