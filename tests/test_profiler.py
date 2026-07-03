"""S4 profile (§6) — distribution stats + suggestions + clustering (P1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from crawl_datasets_common.settings import Settings
from crawl_datasets_profiler.pipeline import run
from crawl_datasets_profiler.profile import build_profile


def _rec(
    lang: str, lic: str, host: str, words: int, pii: list[str] | None = None
) -> dict[str, Any]:
    return {
        "text": "word " * words,
        "lang": lang,
        "pii_found": pii or [],
        "prov": {"license": lic, "source_url": f"https://{host}/x"},
    }


def test_build_profile_distributions() -> None:
    recs = [
        _rec("en", "cc-by", "a.com", 100),
        _rec("vi", "unknown", "a.com", 100),
        _rec("en", "cc-by", "a.com", 1, pii=["email"]),
    ]
    p = build_profile(recs)
    assert p.n_docs == 3
    assert p.lang_dist == {"en": 2, "vi": 1}
    assert p.license_dist.get("unknown") == 1
    assert p.domain_dist.get("a.com") == 3
    assert p.pii_dist.get("email") == 1
    assert p.length_stats["min"] == 1.0
    assert p.anomalies["near_empty"] == 1  # doc 1 từ


def test_suggestions_flag_skew_and_unknown_license() -> None:
    recs = [_rec("en", "unknown", "only.com", 100) for _ in range(5)]
    sug = build_profile(recs).suggestions
    assert any("only.com" in s for s in sug)  # 100% một domain
    assert any("license:unknown" in s for s in sug)


# --- §6 clustering (P1) — BGE-M3→UMAP→HDBSCAN, gated extras --------------------


def _write_clean(clean_dir: Path, n: int) -> None:
    clean_dir.mkdir(parents=True)
    lines = [
        json.dumps({**_rec("en", "cc-by", "a.com", 100), "text": f"doc {i} " * 60})
        for i in range(n)
    ]
    (clean_dir / "part-00000.jsonl").write_text("\n".join(lines), encoding="utf-8")


def test_clustering_disabled_reports_skip(tmp_path: Path) -> None:
    _write_clean(tmp_path / "clean", 6)
    profile = run(tmp_path / "clean", tmp_path / "out", Settings())
    assert profile.clustering is None and profile.clustering_skipped == "disabled"
    report = json.loads((tmp_path / "out" / "profile_report.json").read_text())
    assert report["clustering_skipped"] == "disabled"


def test_clustering_missing_backend_is_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S4 không gate data → thiếu backend KHÔNG raise, nhưng phải fail-visible."""
    from crawl_datasets_profiler import cluster

    monkeypatch.setattr(cluster, "_st", None)
    settings = Settings()
    settings.profile.cluster.enabled = True
    _write_clean(tmp_path / "clean", 6)
    profile = run(tmp_path / "clean", tmp_path / "out", settings)
    assert profile.clustering is None
    assert profile.clustering_skipped is not None
    assert profile.clustering_skipped.startswith("missing_backend:")
    assert "sentence-transformers" in profile.clustering_skipped


def test_clustering_with_fake_backends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chuỗi embed→UMAP→HDBSCAN chạy đúng qua backend giả (deterministic mọi env)."""
    from crawl_datasets_profiler import cluster

    class _FakeEmbedder:
        def __init__(self, model_name: str) -> None:
            assert model_name == "BAAI/bge-m3"  # §10 default

        def encode(self, texts: list[str]) -> list[list[float]]:
            return [[float(len(t) % 7), 1.0] for t in texts]

    class _FakeUMAP:
        def __init__(self, n_components: int, random_state: int) -> None:
            assert random_state == 42  # seed từ global.seed (§0)

        def fit_transform(self, emb: list[list[float]]) -> list[list[float]]:
            return emb

    class _FakeHDBSCAN:
        def __init__(self, min_cluster_size: int) -> None:
            pass

        def fit_predict(self, x: list[list[float]]) -> list[int]:
            return [0, 0, 0, 1, 1, -1][: len(x)]

    monkeypatch.setattr(cluster, "_st", _FakeEmbedder)
    monkeypatch.setattr(cluster, "_umap", type("M", (), {"UMAP": _FakeUMAP}))
    monkeypatch.setattr(cluster, "_hdbscan", type("M", (), {"HDBSCAN": _FakeHDBSCAN}))

    settings = Settings()
    settings.profile.cluster.enabled = True
    settings.profile.cluster.min_cluster_size = 2
    _write_clean(tmp_path / "clean", 6)
    profile = run(tmp_path / "clean", tmp_path / "out", settings)

    assert profile.clustering_skipped is None
    assert profile.clustering is not None
    c = profile.clustering
    assert c["n_clusters"] == 2 and c["cluster_sizes"] == {"0": 3, "1": 2}
    assert c["noise_frac"] == pytest.approx(1 / 6, abs=1e-3)
    assert c["sampled_docs"] == 6 and c["total_docs"] == 6  # no silent cap
