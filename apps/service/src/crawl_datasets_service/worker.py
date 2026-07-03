"""arq worker settings (skeleton)."""

from __future__ import annotations

from arq.connections import RedisSettings
from crawl_datasets_common.settings import load_settings

settings = load_settings()


class WorkerSettings:
    functions: list[object] = []  # TODO(P3): crawl, extract, clean, build, integrate
    redis_settings = RedisSettings(host="redis", port=6379)
    max_jobs = 4
