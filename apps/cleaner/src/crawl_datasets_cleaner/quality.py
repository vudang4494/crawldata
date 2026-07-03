"""Quality classifier (§5.3, P1 — tùy chọn, nâng chất).

FineWeb-Edu style: chấm điểm chất lượng per-doc → filter theo `min_score`,
ghi score vào field `quality` (SFTRecord §7.2). Hai backend:

- `fasttext` (CPU): model .bin, score = P(positive_label). EN-only phổ biến —
  VN cần model multilingual/VN, đừng dùng English-only (§5.3).
- `transformer` (FineWeb2-HQ, arXiv 2502.10361): mean-pooled XLM-RoBERTa
  embeddings → MLP head per-language (`lang_heads`), sigmoid → score.
  `model_path` = HF repo (epfml/FineWeb-HQ-Classifiers, có vie_Latn+eng_Latn)
  hoặc thư mục local chứa các head `.pt`. Deps qua extra `cleaner[quality]`.

Fail-closed: `enabled=true` mà thiếu backend/model/head cho lang → RuntimeError
ngay khi khởi tạo pipeline (giống gate respect_robots §2) — không âm thầm bỏ
chấm điểm. `embed`/`heads` inject được để test không cần torch.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from crawl_datasets_common.settings import QualityConfig

_fasttext: Any = None
try:
    import fasttext as _ft_mod

    _fasttext = _ft_mod
except ImportError:  # pragma: no cover
    _fasttext = None

_torch: Any = None
_transformers: Any = None
try:
    import torch as _torch_mod
    import transformers as _tf_mod

    _torch = _torch_mod
    _transformers = _tf_mod
except ImportError:  # pragma: no cover
    _torch = None
    _transformers = None

Embedder = Callable[[str], Any]
Head = Callable[[Any], float]


class QualityScorer:
    """Wrap fastText model: score(text) = P(positive_label). lang không dùng."""

    def __init__(self, cfg: QualityConfig) -> None:
        self.cfg = cfg
        self._model = _fasttext.load_model(cfg.model_path)

    def score(self, text: str, lang: str = "") -> float:
        # fastText đòi 1 dòng; k=-1 → đủ mọi label để tìm positive_label.
        labels, probs = self._model.predict(text.replace("\n", " "), k=-1)
        for label, prob in zip(labels, probs, strict=False):
            if label == self.cfg.positive_label:
                return float(prob)
        return 0.0


def _resolve_heads_dir(model_path: str) -> Path:  # pragma: no cover — cần network
    """model_path = thư mục local, hoặc HF repo id → snapshot_download (cached)."""
    p = Path(model_path)
    if p.exists():
        return p
    from huggingface_hub import snapshot_download

    return Path(snapshot_download(model_path))


def _build_head(pt_path: Path) -> Any:  # pragma: no cover — cần torch thật
    """MLP head FineWeb2-HQ: Linear(768→256)→ReLU→Dropout→Linear(256→1)."""
    head = _torch.nn.Sequential(
        _torch.nn.Linear(768, 256),
        _torch.nn.ReLU(),
        _torch.nn.Dropout(0.2),
        _torch.nn.Linear(256, 1),
    )
    state = _torch.load(pt_path, weights_only=True, map_location="cpu")
    # state_dict gốc bọc trong attribute `classifier.` (BinaryClassifier epfml).
    head.load_state_dict(
        {k.removeprefix("classifier."): v for k, v in state.items()}
    )
    head.eval()
    return head


def _build_embedder(cfg: QualityConfig) -> Embedder:  # pragma: no cover — torch thật
    """Tokenize→XLM-R→mean-pool last_hidden_state (truncate 512, no_grad)."""
    device = "cuda" if _torch.cuda.is_available() else "cpu"
    tokenizer = _transformers.AutoTokenizer.from_pretrained(cfg.embed_model)
    model = _transformers.AutoModel.from_pretrained(cfg.embed_model).to(device)
    model.eval()

    def embed(text: str) -> Any:
        inputs = tokenizer(
            [text], return_tensors="pt", truncation=True, max_length=512
        ).to(device)
        with _torch.no_grad():
            return model(**inputs).last_hidden_state.float().mean(1).cpu()

    return embed


def _wrap_head(module: Any) -> Head:  # pragma: no cover — cần torch thật
    def head(embedding: Any) -> float:
        with _torch.no_grad():
            return float(_torch.sigmoid(module(embedding)).item())

    return head


class TransformerQualityScorer:
    """§5.3 FineWeb2-HQ: XLM-R mean-pool embed → head theo lang → sigmoid score.

    `embed`/`heads` inject được (test không cần torch); mặc định build thật từ
    `cfg.embed_model` + các head `.pt` trong `cfg.model_path` theo `lang_heads`.
    """

    def __init__(
        self,
        cfg: QualityConfig,
        *,
        embed: Embedder | None = None,
        heads: Mapping[str, Head] | None = None,
    ) -> None:
        self.cfg = cfg
        if embed is not None and heads is not None:
            self._embed = embed
            self._heads: dict[str, Head] = dict(heads)
            return
        self._embed = _build_embedder(cfg)  # pragma: no cover — cần torch thật
        heads_dir = _resolve_heads_dir(cfg.model_path or "")
        self._heads = {
            lang: _wrap_head(_build_head(heads_dir / fname))
            for lang, fname in cfg.lang_heads.items()
        }

    def score(self, text: str, lang: str = "") -> float:
        head = self._heads.get(lang)
        if head is None:  # fail-closed — lang không có head (§5.3)
            raise RuntimeError(
                f"quality.transformer: không có head cho lang={lang!r} "
                f"(lang_heads={sorted(self._heads)}) — §5.3 fail-closed"
            )
        return float(head(self._embed(text)))


Scorer = QualityScorer | TransformerQualityScorer


def build_scorer(
    cfg: QualityConfig, lang_allow: list[str] | None = None
) -> Scorer | None:
    """None khi tắt; RuntimeError khi bật mà thiếu backend/model (fail-closed)."""
    if not cfg.enabled:
        return None
    if not cfg.model_path:
        raise RuntimeError(
            "clean.quality.enabled=true nhưng thiếu model_path (§5.3 fail-closed)"
        )
    if cfg.backend == "fasttext":
        if _fasttext is None:
            raise RuntimeError(
                "clean.quality.enabled=true nhưng fasttext chưa cài "
                "(§5.3 fail-closed)"
            )
        return QualityScorer(cfg)
    # backend transformer — check config trước (không cần torch), backend sau.
    missing = [lang for lang in (lang_allow or []) if lang not in cfg.lang_heads]
    if missing:
        raise RuntimeError(
            f"quality.transformer: lang_allow {missing} không có head trong "
            "lang_heads (§5.3 fail-closed — mỗi lang cần head .pt riêng)"
        )
    if _torch is None or _transformers is None:
        raise RuntimeError(
            "clean.quality.backend=transformer nhưng torch/transformers chưa cài "
            "(extra: crawl-datasets-cleaner[quality]) — §5.3 fail-closed"
        )
    return TransformerQualityScorer(cfg)
