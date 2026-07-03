"""Quality classifier (§5.3, P1 — tùy chọn, nâng chất).

FineWeb-Edu style: chấm điểm chất lượng per-doc → filter theo `min_score`,
ghi score vào field `quality` (SFTRecord §7.2). Backend fastText (CPU, §5.3);
VN cần model multilingual/VN — đừng dùng English-only (§5.3).

Fail-closed: `enabled=true` mà thiếu backend/model → RuntimeError ngay khi
khởi tạo pipeline (giống gate respect_robots §2) — không âm thầm bỏ chấm điểm.
"""

from __future__ import annotations

from typing import Any

from crawl_datasets_common.settings import QualityConfig

_fasttext: Any = None
try:
    import fasttext as _ft_mod

    _fasttext = _ft_mod
except ImportError:  # pragma: no cover
    _fasttext = None


class QualityScorer:
    """Wrap fastText model: score(text) = P(positive_label)."""

    def __init__(self, cfg: QualityConfig) -> None:
        self.cfg = cfg
        self._model = _fasttext.load_model(cfg.model_path)

    def score(self, text: str) -> float:
        # fastText đòi 1 dòng; k=-1 → đủ mọi label để tìm positive_label.
        labels, probs = self._model.predict(text.replace("\n", " "), k=-1)
        for label, prob in zip(labels, probs, strict=False):
            if label == self.cfg.positive_label:
                return float(prob)
        return 0.0


def build_scorer(cfg: QualityConfig) -> QualityScorer | None:
    """None khi tắt; RuntimeError khi bật mà thiếu backend/model (fail-closed)."""
    if not cfg.enabled:
        return None
    if _fasttext is None:
        raise RuntimeError(
            "clean.quality.enabled=true nhưng fasttext chưa cài (§5.3 fail-closed)"
        )
    if not cfg.model_path:
        raise RuntimeError(
            "clean.quality.enabled=true nhưng thiếu model_path (§5.3 fail-closed)"
        )
    return QualityScorer(cfg)
