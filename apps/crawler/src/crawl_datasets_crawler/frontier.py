"""URL frontier + link extraction (§3.3).

Dedup URL bằng set (Bloom filter cho scale là mở rộng, §3.3). Depth-bounded BFS.
"""

from __future__ import annotations

import re
from collections import deque
from urllib.parse import urljoin, urlparse

_HREF_RE = re.compile(r'<a\b[^>]*?href=["\']([^"\'#]+)', re.IGNORECASE)


def host_of(url: str) -> str:
    return urlparse(url).netloc


class Frontier:
    """FIFO frontier, dedup URL đã thấy, bỏ url vượt max_depth."""

    def __init__(self, max_depth: int) -> None:
        self.max_depth = max_depth
        self._queue: deque[tuple[str, int]] = deque()
        self._seen: set[str] = set()

    def add(self, url: str, depth: int) -> bool:
        if depth > self.max_depth or url in self._seen:
            return False
        self._seen.add(url)
        self._queue.append((url, depth))
        return True

    def pop(self) -> tuple[str, int] | None:
        return self._queue.popleft() if self._queue else None

    def __len__(self) -> int:
        return len(self._queue)


def extract_links(html: str, base_url: str) -> list[str]:
    """Rút link http(s) tuyệt đối từ HTML (bỏ fragment/mailto/js)."""
    out: list[str] = []
    for href in _HREF_RE.findall(html):
        if href.startswith(("mailto:", "javascript:", "tel:")):
            continue
        url = urljoin(base_url, href).split("#")[0]
        if url.startswith(("http://", "https://")):
            out.append(url)
    return out
