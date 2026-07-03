"""Quality filters (§5.3) — Gopher quality/repetition, C4, FineWeb custom.

Mỗi filter trả `str | None`: None = giữ, str = lý do drop (fail-closed + observability).
VN overrides (§5.3): thay stop-word English, tắt rule mean-word-length cho lang='vi'.
"""

from __future__ import annotations

import re
from collections import Counter

from crawl_datasets_common.settings import GopherQuality, VIOverrides

# §5.3 — stop-word English (Gopher default) VÔ NGHĨA với tiếng Việt → có bộ VN riêng.
EN_STOPWORDS: frozenset[str] = frozenset(
    {"the", "be", "to", "of", "and", "that", "have", "with"}
)
VN_STOPWORDS: frozenset[str] = frozenset(
    {
        "và",
        "là",
        "của",
        "có",
        "được",
        "cho",
        "những",
        "một",
        "các",
        "để",
        "trong",
        "người",
    }
)

_WORD_RE = re.compile(r"\w+", re.UNICODE)
_ALPHA_RE = re.compile(r"[^\W\d_]", re.UNICODE)
_BULLET_PREFIX = ("•", "-", "*", "‣", "·", "◦")
_TERMINAL_PUNCT = (".", "!", "?", '"', "'", "”", "’", "。", "…", "”")

# §5.3 Gopher repetition — datatrove defaults (không nằm trong §9.3 config).
_DUP_LINE_FRAC_MAX = 0.30
_DUP_PARA_FRAC_MAX = 0.30
_TOP_NGRAM_CHAR_FRAC_MAX = {2: 0.20, 3: 0.18, 4: 0.16}


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def gopher_quality(
    text: str, cfg: GopherQuality, lang: str, vi: VIOverrides
) -> str | None:
    """Gopher quality filter (§5.3). None = pass, str = lý do drop."""
    words = _words(text)
    n = len(words)
    if not (cfg.min_words <= n <= cfg.max_words):
        return f"gopher_word_count:{n}"

    # Mean word length — §5.3: tắt cho VN (space-tokenization giả định English).
    if not (lang == "vi" and vi.disable_word_len_rule):
        mean_len = sum(len(w) for w in words) / n
        if not (cfg.mean_word_length_min <= mean_len <= cfg.mean_word_length_max):
            return f"gopher_mean_word_len:{mean_len:.1f}"

    symbols = text.count("#") + text.count("…")
    if symbols / n > cfg.symbol_to_word_ratio:
        return "gopher_symbol_ratio"

    lines = _lines(text)
    if lines:
        bullet = sum(1 for ln in lines if ln.startswith(_BULLET_PREFIX)) / len(lines)
        if bullet > cfg.bullet_line_ratio:
            return "gopher_bullet_lines"
        ellipsis = sum(1 for ln in lines if ln.endswith("…")) / len(lines)
        if ellipsis > cfg.ellipsis_line_ratio:
            return "gopher_ellipsis_lines"

    alpha_words = sum(1 for w in words if _ALPHA_RE.search(w))
    if alpha_words / n < cfg.alpha_word_ratio:
        return "gopher_alpha_ratio"

    # §5.3 VN override: dùng stop-word VN thay English.
    stop = VN_STOPWORDS if (lang == "vi" and vi.use_vi_stopwords) else EN_STOPWORDS
    lowered = {w.lower() for w in words}
    if len(lowered & stop) < cfg.min_stopwords:
        return "gopher_stopwords"
    return None


def gopher_repetition(text: str) -> str | None:
    """Gopher repetition filter (§5.3 subset) — dup line/para + top n-gram char frac."""
    lines = _lines(text)
    if len(lines) >= 2:
        dup_line_frac = 1.0 - len(set(lines)) / len(lines)
        if dup_line_frac > _DUP_LINE_FRAC_MAX:
            return "rep_dup_lines"
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paras) >= 2:
        dup_para_frac = 1.0 - len(set(paras)) / len(paras)
        if dup_para_frac > _DUP_PARA_FRAC_MAX:
            return "rep_dup_paras"

    words = _words(text)
    total_chars = sum(len(w) for w in words)
    for n, cap in _TOP_NGRAM_CHAR_FRAC_MAX.items():
        if len(words) < n:
            continue
        grams = [tuple(words[i : i + n]) for i in range(len(words) - n + 1)]
        top_gram, count = Counter(grams).most_common(1)[0]
        if count < 2:
            continue
        gram_chars = sum(len(w) for w in top_gram) * count
        if total_chars and gram_chars / total_chars > cap:
            return f"rep_top_{n}gram"
    return None


def c4_filter(text: str) -> tuple[str, str | None]:
    """C4 filters (§5.3, subset FineWeb dùng). Trả (text_đã_lọc_dòng, lý_do_drop|None).

    - Drop doc chứa 'lorem ipsum'.
    - Line-level: bỏ dòng 'javascript', dòng terms/cookie, dòng không có terminal punct.
    - GIỮ terminal-punctuation; BỎ curly-bracket filter (FineWeb: hại HellaSwag).
    """
    if "lorem ipsum" in text.lower():
        return text, "c4_lorem_ipsum"

    kept: list[str] = []
    for raw in text.splitlines():
        ln = raw.strip()
        if not ln:
            kept.append(raw)
            continue
        low = ln.lower()
        if "javascript" in low:
            continue
        if "terms of use" in low or "cookie policy" in low or "terms-of-use" in low:
            continue
        if not ln.endswith(_TERMINAL_PUNCT):
            continue
        kept.append(raw)

    cleaned = "\n".join(kept).strip()
    if not cleaned:
        return cleaned, "c4_all_lines_dropped"
    return cleaned, None


def fineweb_custom(text: str) -> str | None:
    """FineWeb custom (§5.3 subset) — loại doc list-like (đa số dòng ngắn/bullet)."""
    lines = _lines(text)
    if len(lines) < 3:
        return None
    listy = sum(
        1 for ln in lines if ln.startswith(_BULLET_PREFIX) or len(_words(ln)) < 3
    )
    if listy / len(lines) > 0.5:
        return "fineweb_list_like"
    return None
