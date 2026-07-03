# Crawl → Clean → Build → Integrate

Reference skeleton cho service dựng dataset fine-tuning (SFT/instruction-tuning) đa ngữ (VN + EN/multilingual).

> **Spec là source of truth:** [`crawl-clean-dataset-service.md`](./crawl-clean-dataset-service.md). Mọi quyết định implementation (tool, config key, threshold, thứ tự stage, hardware target) đều được fix bởi spec. Repo này chỉ là **skeleton** — chưa có logic pipeline thật, chỉ có wiring + contract + entrypoint để P0 MVP bắt đầu triển khai.

## Cấu trúc

```
.
├── apps/                       # Mỗi stage/service là 1 package độc lập
│   ├── probe/                  # S0 — Source probe (robots, sitemap, JS, license)
│   ├── crawler/                # S1 — Crawl (Scrapy / httpx+selectolax / Playwright)
│   ├── extractor/              # S2 — Extract (trafilatura, pymupdf, MinerU)
│   ├── cleaner/                # S3 — Clean+filter (NFC, GlotLID, Gopher, MinHash, Presidio)
│   ├── profiler/               # S4 — Profile + suggestions
│   ├── builder/                # S5 — Build (ChatML/ShareGPT/Alpaca → Parquet)
│   ├── integrator/             # S6 — Integrate (cross-dedup + mix)
│   └── service/                # FastAPI + arq
├── libs/
│   └── common/                 # Shared: config, schema, storage, observability, provenance
├── configs/
│   ├── default.yaml            # §9.3 config (single source of truth)
│   └── dev.yaml                # Local overrides
├── ops/
│   ├── docker-compose.yml      # Redis, MinIO, Prometheus, Grafana
│   ├── prometheus.yml
│   ├── grafana/
│   └── Dockerfile
├── dvc.yaml                    # Pipeline stages (deps, outs, params)
├── Makefile
└── pyproject.toml              # uv workspace
```

## Nguyên tắc không thương lượng (§0)

1. **Fail-closed** — verifier exception = FAIL, không bao giờ PASS.
2. **Streaming, not load-all** — shard-based, không `load_dataset(...).to_list()`.
3. **Per-source / per-crawl dedup** — global dedup chỉ dùng cho cross-dataset (§8.2).
4. **NFC normalize** trước mọi hash/dedup.
5. **Stable ID** (`AddId` đầu pipeline) cho mọi dedup/versioning.
6. **`license:unknown` → loại khỏi dataset publish**, chỉ giữ raw tier audit.
7. **Per-stage checkpointing** + `_SUCCESS` marker + `manifest.json`.
8. **Config là single source of truth** (Pydantic `BaseSettings`, không hardcode).

## Hardware split (§9.2)

- **CPU local:** crawl, extract, filter, CPU MinHash (datatrove).
- **RTX 4090 24GB:** BGE-M3 embed, small classifier, semantic dedup vừa.
- **A100 80GB burst (Vast.ai):** NeMo Curator fuzzy/semantic dedup scale lớn.

## Bắt đầu

```bash
# Cài uv (nếu chưa có)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync workspace + dev deps
uv sync --all-extras --all-groups

# Chạy service local (cần Redis ở ops/)
docker compose -f ops/docker-compose.yml up -d redis minio prometheus grafana
uv run --package service uvicorn crawl_datasets_service.main:app --reload

# Audit spec
uv run verify-design-spec
```

## Phased build (§12)

- **P0 MVP:** probe + httpx/Scrapy + trafilatura + NFC/ftfy → GlotLID → Gopher+C4 → exact+MinHash dedup → Presidio → ChatML JSONL. datatrove backbone. DVC. Seed + checkpoint + Prometheus.
- **P1:** Playwright pool, profiling, decontam, quality classifier, VN overrides.
- **P2:** cross-dedup Zyda-2, NeMo GPU dedup, semantic dedup.
- **P3:** FastAPI hoàn chỉnh, Grafana dashboard, Langfuse (nếu có LLM-judge).