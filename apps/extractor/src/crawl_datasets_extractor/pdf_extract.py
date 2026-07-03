"""PDF → text (§4.2). pymupdf (fitz) cho PDF text thường; MinerU/marker cho STEM (hook).

pymupdf là optional backend (extra `pdf`). Thiếu → trả None (fail-closed: doc PDF không
rút được text sẽ bị S2 drop + log, không lưu rỗng).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

_fitz: Any = None
try:
    import pymupdf

    _fitz = pymupdf
except ImportError:  # pragma: no cover
    try:
        import fitz

        _fitz = fitz
    except ImportError:
        _fitz = None


def pymupdf_available() -> bool:
    return _fitz is not None


def extract_pdf(path: Path) -> tuple[str, str] | None:
    """Trả (text, extractor_name) hoặc None nếu thiếu backend / rỗng."""
    if _fitz is None:
        return None
    doc = _fitz.open(path)
    try:
        text = "\n".join(page.get_text() for page in doc).strip()
    finally:
        doc.close()
    if not text:
        return None
    version = getattr(_fitz, "__version__", "") or getattr(_fitz, "VersionBind", "")
    return text, f"pymupdf-{version}" if version else "pymupdf"
