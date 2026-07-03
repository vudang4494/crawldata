"""Observability skeleton (§9.4).

- structlog JSON: mỗi drop ghi `{doc_id, stage, reason}`.
- Prometheus counter: `stage_records_total{stage,status}`,
  `drop_reason_total{stage,reason}`, `stage_duration_seconds`.
- Langfuse: chỉ khi có LLM-in-loop (§0, §9.4).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import structlog

try:
    from prometheus_client import Counter, Histogram

    _PROM_AVAILABLE = True
except ImportError:  # skeleton chạy được kể cả khi thiếu prom client
    _PROM_AVAILABLE = False


def configure_logging(level: str = "INFO") -> None:
    """structlog JSON output (§9.4)."""
    logging.basicConfig(level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level)),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    return structlog.get_logger(name)


# Prometheus metrics — guard import để skeleton không phụ thuộc cứng vào client
if _PROM_AVAILABLE:
    records_total = Counter(
        "stage_records_total",
        "Records processed per stage",
        labelnames=("stage", "status"),  # status: in | out | dropped
    )
    drop_reason = Counter(
        "drop_reason_total",
        "Drop events per stage and reason",
        labelnames=("stage", "reason"),
    )
    stage_duration = Histogram(
        "stage_duration_seconds",
        "Stage processing duration",
        labelnames=("stage",),
    )
else:
    records_total = drop_reason = stage_duration = None  # type: ignore[assignment]


def record_drop(stage: str, reason: str) -> None:
    """Log + (nếu có) emit drop counter."""
    get_logger(stage).warning("record_dropped", stage=stage, reason=reason)
    if drop_reason is not None:
        drop_reason.labels(stage=stage, reason=reason).inc()


@contextmanager
def stage_timer(stage: str) -> Iterator[None]:
    """Measure stage duration, log start/end."""
    log = get_logger(stage)
    log.info("stage_start", stage=stage)
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        log.info("stage_end", stage=stage, duration_seconds=elapsed)
        if stage_duration is not None:
            stage_duration.labels(stage=stage).observe(elapsed)
