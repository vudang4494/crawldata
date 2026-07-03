"""Settings/config (Pydantic). Single source of truth (§9.3).

Đọc YAML theo `config.yaml` (hoặc path env `CDS_CONFIG`), validate bằng Pydantic.
Không hardcode threshold/model literal trong code (§0).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


class GlobalSettings(BaseModel):
    seed: int = 42
    pipeline_version: str = "1.3.0"


class CrawlSettings(BaseModel):
    render: str = Field(default="auto", pattern="^(auto|http|browser)$")
    render_min_text_len: int = 200  # §3.2 auto: text < threshold → escalate browser
    max_depth: int = 3
    per_host_concurrency: int = 4
    respect_robots: bool = True  # §2 — fail-closed


class ExtractSettings(BaseModel):
    primary: str = Field(default="trafilatura")
    fallback: str = Field(default="readability")


class LangScoreMin(BaseModel):
    vi: float = 0.60
    en: float = 0.65

    @field_validator("*")
    @classmethod
    def _range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            msg = f"lang_score_min must be in [0,1], got {v}"
            raise ValueError(msg)
        return v


class GopherQuality(BaseModel):
    min_words: int = 50
    max_words: int = 100_000
    mean_word_length_min: int = 3
    mean_word_length_max: int = 10
    symbol_to_word_ratio: float = 0.1
    bullet_line_ratio: float = 0.9
    ellipsis_line_ratio: float = 0.3
    alpha_word_ratio: float = 0.8
    min_stopwords: int = 2


class VIOverrides(BaseModel):
    """§5.3 — VN phải override các rule English."""

    use_vi_stopwords: bool = True
    disable_word_len_rule: bool = True


class MinHashConfig(BaseModel):
    """§5.4 — FineWeb ablation: per-source/per-crawl tốt hơn global."""

    ngram: int = 5
    num_hashes: int = 112
    bands: int = 14
    rows: int = 8
    scope: str = Field(default="per_source", pattern="^(per_source|per_crawl)$")


class PIIConfig(BaseModel):
    backend: str = Field(default="presidio")
    vi_regex: bool = True  # §11 — CCCD/CMND/SĐT +84
    # §5.5 — NER chỉ áp cho lang có model; EN NER trên VN → false-positive nặng.
    presidio_langs: list[str] = Field(default_factory=lambda: ["en"])


class DecontamConfig(BaseModel):
    benchmarks: list[str] = Field(
        default_factory=lambda: ["mmlu", "aime", "math500", "mgsm"]
    )
    ngram: int = 13  # §5.6 — GPT-3 style


class QualityConfig(BaseModel):
    """§5.3 — quality classifier (tùy chọn, P1). enabled=true đòi backend thật."""

    enabled: bool = False
    backend: str = Field(default="fasttext", pattern="^(fasttext)$")
    model_path: str | None = None
    positive_label: str = "__label__hq"  # FineWeb-Edu style label dương
    min_score: float = 0.5


class CleanSettings(BaseModel):
    lang_id: str = Field(default="glotlid")
    lang_allow: list[str] = Field(default_factory=lambda: ["vi", "en"])
    lang_score_min: LangScoreMin = Field(default_factory=LangScoreMin)
    gopher_quality: GopherQuality = Field(default_factory=GopherQuality)
    vi_overrides: VIOverrides = Field(default_factory=VIOverrides)
    minhash: MinHashConfig = Field(default_factory=MinHashConfig)
    pii: PIIConfig = Field(default_factory=PIIConfig)
    decontam: DecontamConfig = Field(default_factory=DecontamConfig)
    quality: QualityConfig = Field(default_factory=QualityConfig)


class ClusterConfig(BaseModel):
    """§6 — clustering BGE-M3→UMAP→HDBSCAN (P1). Backend nặng: extras cluster+embed."""

    enabled: bool = False
    embed_model: str = "BAAI/bge-m3"  # §10 — embed trên 4090
    max_docs: int = 2000  # cap bounded-memory; sample ghi vào report (no silent cap)
    min_cluster_size: int = 5


class ProfileSettings(BaseModel):
    cluster: ClusterConfig = Field(default_factory=ClusterConfig)


class ServiceSettings(BaseModel):
    """§1 — FastAPI + arq (Redis queue)."""

    redis_url: str = "redis://localhost:6379"
    max_jobs: int = 4


class BuildSettings(BaseModel):
    format: str = Field(default="chatml", pattern="^(chatml|sharegpt|alpaca)$")


class IntegrateSettings(BaseModel):
    cross_dedup: bool = True
    source_priority: list[str] = Field(
        default_factory=lambda: ["curated_v2", "crawl_new"]
    )
    mix_ratios: dict[str, float] = Field(default_factory=lambda: {"vi": 0.5, "en": 0.5})

    @field_validator("mix_ratios")
    @classmethod
    def _sum_one(cls, v: dict[str, float]) -> dict[str, float]:
        if abs(sum(v.values()) - 1.0) > 1e-3:
            msg = f"mix_ratios must sum to 1.0, got {sum(v.values())}"
            raise ValueError(msg)
        return v


class Settings(BaseModel):
    """Top-level — khớp §9.3 config skeleton."""

    global_: GlobalSettings = Field(default_factory=GlobalSettings, alias="global")
    crawl: CrawlSettings = Field(default_factory=CrawlSettings)
    extract: ExtractSettings = Field(default_factory=ExtractSettings)
    clean: CleanSettings = Field(default_factory=CleanSettings)
    profile: ProfileSettings = Field(default_factory=ProfileSettings)
    build: BuildSettings = Field(default_factory=BuildSettings)
    integrate: IntegrateSettings = Field(default_factory=IntegrateSettings)
    service: ServiceSettings = Field(default_factory=ServiceSettings)

    model_config = {"populate_by_name": True}

    @classmethod
    def from_yaml(cls, path: str | Path) -> Settings:
        with Path(path).open() as f:
            raw: dict[str, Any] = yaml.safe_load(f)
        return cls.model_validate(raw)


def load_settings(path: str | Path | None = None) -> Settings:
    """Load config. Path resolution: explicit > env > default configs/default.yaml."""
    import os

    if path is None:
        path = os.environ.get("CDS_CONFIG", "configs/default.yaml")
    return Settings.from_yaml(path)
