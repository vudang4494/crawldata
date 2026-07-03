"""Clustering / topic discovery (§6, P1) — BGE-M3 embed → UMAP → HDBSCAN.

Backend nặng gate qua extras `embed` (sentence-transformers) + `cluster`
(umap-learn/hdbscan); embed chạy 4090 (§9.2). S4 chỉ báo cáo, không gate data
→ thiếu backend KHÔNG raise: trả skip-reason tường minh để report ghi lại
(fail-visible, không silent). Seed từ `global.seed` (§0 reproducibility).
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from crawl_datasets_common.settings import ClusterConfig

_st: Any = None
_umap: Any = None
_hdbscan: Any = None
try:
    from sentence_transformers import SentenceTransformer

    _st = SentenceTransformer
except ImportError:  # pragma: no cover
    _st = None
try:
    import umap as _umap_mod

    _umap = _umap_mod
except ImportError:  # pragma: no cover
    _umap = None
try:
    import hdbscan as _hdbscan_mod

    _hdbscan = _hdbscan_mod
except ImportError:  # pragma: no cover
    _hdbscan = None


def build_clusters(
    texts: list[str], *, cfg: ClusterConfig, seed: int
) -> tuple[dict[str, Any] | None, str | None]:
    """(report, skip_reason) — đúng một trong hai khác None."""
    if not cfg.enabled:
        return None, "disabled"
    missing = [
        name
        for name, mod in (
            ("sentence-transformers", _st),
            ("umap-learn", _umap),
            ("hdbscan", _hdbscan),
        )
        if mod is None
    ]
    if missing:
        return None, "missing_backend:" + ",".join(missing)
    if len(texts) < cfg.min_cluster_size:
        return None, f"too_few_docs:{len(texts)}"

    embeddings = _st(cfg.embed_model).encode(texts)  # BGE-M3 — 4090 (§9.2)
    reduced = _umap.UMAP(n_components=5, random_state=seed).fit_transform(embeddings)
    labels = _hdbscan.HDBSCAN(min_cluster_size=cfg.min_cluster_size).fit_predict(
        reduced
    )

    sizes: Counter[int] = Counter(int(label) for label in labels)
    noise = sizes.pop(-1, 0)
    return {
        "sampled_docs": len(texts),
        "n_clusters": len(sizes),
        "noise_frac": round(noise / len(texts), 3),
        "cluster_sizes": {str(k): v for k, v in sorted(sizes.items())},
        "embed_model": cfg.embed_model,
    }, None
