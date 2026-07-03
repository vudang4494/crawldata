"""DatasetPlan (§14) — hợp đồng giữa Agent LLM và pipeline.

LLM chỉ ĐỀ XUẤT plan; mọi gate (robots §2, license §2, dedup scope §5.4,
PII §5.5, decontam §5.6) vẫn enforce trong pipeline deterministic. Plan là
subset AN TOÀN của config §9.3 — cố tình không có field nào nới gate
(không respect_robots, không minhash.scope, không tắt PII).
"""

from __future__ import annotations

from typing import Literal

from crawl_datasets_common.settings import Settings
from pydantic import BaseModel, Field, field_validator


class DatasetPlan(BaseModel):
    """Kế hoạch build dataset từ 1 nguồn — do agent đề xuất, user duyệt."""

    goal: str
    criteria: list[str] = Field(default_factory=list)  # tiêu chí agent phân tích
    seeds: list[str]
    max_depth: int = Field(default=2, ge=0, le=6)
    max_pages: int = Field(default=500, ge=1, le=20_000)
    render: Literal["auto", "http", "browser"] = "auto"
    lang_allow: list[str] = Field(default_factory=lambda: ["vi", "en"])
    build_format: Literal["chatml", "sharegpt", "alpaca"] = "chatml"
    quality_min_score: float | None = Field(default=None, ge=0.0, le=1.0)
    notes: str = ""

    @field_validator("seeds")
    @classmethod
    def _seeds_are_http(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("plan cần ít nhất 1 seed URL")
        for u in v:
            if not u.startswith(("http://", "https://")):
                raise ValueError(f"seed không phải http(s): {u!r}")
        return v


def apply_plan(settings: Settings, plan: DatasetPlan) -> Settings:
    """Merge plan vào bản copy của Settings — chỉ các key an toàn (§14)."""
    s = settings.model_copy(deep=True)
    s.crawl.max_depth = plan.max_depth
    s.crawl.render = plan.render
    s.clean.lang_allow = plan.lang_allow
    s.build.format = plan.build_format
    # min_score chỉ áp khi quality đã bật sẵn trong config (cần model_path thật).
    if plan.quality_min_score is not None and s.clean.quality.enabled:
        s.clean.quality.min_score = plan.quality_min_score
    return s
