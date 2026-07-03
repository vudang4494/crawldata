"""Probe detections (§2) — pure functions trên nội dung đã fetch (test không cần net).

robots.txt, sitemap, JS-render heuristic, feed/API, license gate (§2 fail-closed).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# License detection (§2) dùng chung ở crawl_datasets_common.licensing.detect_license.
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class RobotsInfo:
    crawl_delay: float | None = None
    sitemaps: list[str] = field(default_factory=list)
    disallow: list[str] = field(default_factory=list)


def parse_robots(text: str) -> RobotsInfo:
    """Parse robots.txt → crawl-delay, sitemaps, disallow (§2/§3.3 politeness)."""
    info = RobotsInfo()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip().lower(), val.strip()
        if key == "crawl-delay":
            try:
                info.crawl_delay = float(val)
            except ValueError:
                continue
        elif key == "sitemap" and val:
            info.sitemaps.append(val)
        elif key == "disallow" and val:
            info.disallow.append(val)
    return info


def parse_sitemap(xml: str) -> list[str]:
    """Trả danh sách URL từ <loc> (sitemap/sitemap-index) — seed frontier trực tiếp."""
    return [u.strip() for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)]


def detect_render(html: str) -> str:
    """Heuristic http/browser (§3.2): root rỗng + nhiều script + ít text → browser."""
    text_len = len(_TAG_RE.sub(" ", html).strip())
    scripts = len(re.findall(r"<script\b", html, re.IGNORECASE))
    empty_root = bool(
        re.search(r'<div[^>]*id=["\']?(?:root|app)["\']?[^>]*>\s*</div>', html, re.I)
    )
    if (empty_root and scripts >= 3 and text_len < 500) or (
        text_len < 200 and scripts >= 5
    ):
        return "browser"
    return "http"


def detect_feeds(html: str) -> list[str]:
    """RSS/Atom feed hoặc API — ưu tiên hơn scrape HTML (§2, ổn định hơn)."""
    return re.findall(
        r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]*?'
        r'href=["\']([^"\']+)',
        html,
        re.IGNORECASE,
    )
