"""HTML → text (§4.1). trafilatura = default (RefinedWeb/FineWeb), giữ metadata+date.

trafilatura là optional backend; thiếu → fallback stdlib stripper (bỏ script/style/nav/
footer, chèn xuống dòng ở block tag). Fallback đủ để P0/test chạy không cần trafilatura.
rs-trafilatura/resiliparse cho scale để mở rộng (§4.1) — hook qua tên `primary`.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

_trafilatura: Any = None
try:
    import trafilatura

    _trafilatura = trafilatura
except ImportError:  # pragma: no cover
    _trafilatura = None

# boilerplate — bỏ hẳn (fallback không có model như trafilatura nên lọc thô).
_SKIP_TAGS = frozenset(
    {
        "script",
        "style",
        "noscript",
        "template",
        "svg",
        "nav",
        "header",
        "footer",
        "aside",
        "form",
        "button",
    }
)
_BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "br",
        "li",
        "tr",
        "section",
        "article",
        "blockquote",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "ul",
        "ol",
    }
)
_WS_RE = re.compile(r"[ \t]+")
_NL_RE = re.compile(r"\n\s*\n\s*\n+")


class _Stripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title: str | None = None
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title and self.title is None:
            self.title = text
        self.parts.append(text)


def _fallback(html: str) -> tuple[str, str | None]:
    parser = _Stripper()
    parser.feed(html)
    joined = " ".join(p if p != "\n" else "\n" for p in parser.parts)
    text = _NL_RE.sub("\n\n", _WS_RE.sub(" ", joined)).strip()
    return text, parser.title


def extract_html(
    html: str, primary: str = "trafilatura"
) -> tuple[str, str, str | None] | None:
    """Trả (text, extractor_name, title) hoặc None nếu không rút được text."""
    if primary == "trafilatura" and _trafilatura is not None:
        text = _trafilatura.extract(html, include_comments=False, include_tables=True)
        if text and text.strip():
            version = getattr(_trafilatura, "__version__", "")
            name = f"trafilatura-{version}" if version else "trafilatura"
            return text.strip(), name, None
    text, title = _fallback(html)
    if text:
        return text, "htmlparser-fallback", title
    return None
