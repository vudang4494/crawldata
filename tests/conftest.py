"""Test bootstrap — đưa mọi package src của workspace lên sys.path.

Cho phép chạy `pytest` mà không cần `uv sync` trước (src-layout monorepo):
mọi `crawl_datasets_*` import được từ apps/*/src và libs/*/src.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

for _src in [
    *sorted((ROOT / "apps").glob("*/src")),
    *sorted((ROOT / "libs").glob("*/src")),
]:
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

# Entrypoint gọi load_settings() không tham số → dùng config mặc định (absolute).
os.environ.setdefault("CDS_CONFIG", str(ROOT / "configs" / "default.yaml"))
