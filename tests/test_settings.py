"""Settings contract — đảm bảo config skeleton khớp spec §9.3."""

from __future__ import annotations

import pytest
from crawl_datasets_common.settings import load_settings


def test_default_config_loads() -> None:
    cfg = load_settings("configs/default.yaml")
    assert cfg.global_.seed == 42
    assert cfg.global_.pipeline_version == "1.3.0"


def test_respect_robots_default_true() -> None:
    """§2 — fail-closed legal gate."""
    cfg = load_settings("configs/default.yaml")
    assert cfg.crawl.respect_robots is True


def test_minhash_scope_default_per_source() -> None:
    """§5.4 — FineWeb ablation: per-source/per-crawl > global."""
    cfg = load_settings("configs/default.yaml")
    assert cfg.clean.minhash.scope in {"per_source", "per_crawl"}


def test_mix_ratios_sum_to_one() -> None:
    cfg = load_settings("configs/default.yaml")
    total = sum(cfg.integrate.mix_ratios.values())
    assert abs(total - 1.0) < 1e-3


def test_vi_lang_threshold_present() -> None:
    """§5.3 — VN threshold riêng."""
    cfg = load_settings("configs/default.yaml")
    assert "vi" in cfg.clean.lang_score_min.model_dump()
    assert cfg.clean.lang_allow == ["vi", "en"]


def test_vi_overrides_default() -> None:
    """§5.3 — VN stopwords + disable word-len rule."""
    cfg = load_settings("configs/default.yaml")
    assert cfg.clean.vi_overrides.use_vi_stopwords is True
    assert cfg.clean.vi_overrides.disable_word_len_rule is True


def test_invalid_minhash_scope_rejected(tmp_path: pytest.TempPathFactory) -> None:
    """§5.4 — guard scope='global' ở validation time."""
    import yaml

    bad = {
        "clean": {
            "minhash": {
                "scope": "global",
            },
        },
    }
    p = tmp_path / "bad.yaml"  # type: ignore[attr-defined]
    p.write_text(yaml.safe_dump(bad))

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        load_settings(str(p))


def test_invalid_mix_ratios_sum_rejected(tmp_path: pytest.TempPathFactory) -> None:
    """§8.3 — ratios phải sum về 1.0."""
    import yaml

    bad = {"integrate": {"mix_ratios": {"vi": 0.3, "en": 0.3}}}
    p = tmp_path / "bad.yaml"  # type: ignore[attr-defined]
    p.write_text(yaml.safe_dump(bad))

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        load_settings(str(p))
