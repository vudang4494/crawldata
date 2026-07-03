# Crawl → Clean → Build → Integrate

Reference skeleton cho service dựng dataset fine-tuning (SFT/instruction-tuning) đa ngữ (VN + EN/multilingual).

> **Spec là source of truth:** [`crawl-clean-dataset-service.md`](./crawl-clean-dataset-service.md). Mọi quyết định implementation (tool, config key, threshold, thứ tự stage, hardware target) đều được fix bởi spec. **Toàn bộ pipeline S0–S6 + các feature P1 đã implement** (core pure-Python, backend nặng gated qua extras — thiếu backend vẫn chạy với fallback). Còn lại: P2 (NeMo GPU dedup, semantic dedup) và P3 (service polish).

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
│   ├── agent/                  # §14 — Agent intake (URL+nhu cầu → LLM local → DatasetPlan → pipeline)
│   └── service/                # FastAPI + arq (+ /agent/sessions)
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
make run-service   # FastAPI (uvicorn)
make run-worker    # arq worker chạy job crawl/build/integrate

# Gate đầy đủ trước khi merge (lock + spec scan + lint + type + test)
make verify

# Agent intake (§14) — cần Ollama chạy model local (mặc định gemma4:e4b)
uv run crawl-datasets-agent --url https://nguon.vn --need "SFT song ngữ ~100 trang" --out data/proj
```

## Phased build (§12)

- **P0 MVP — ✅ xong:** probe + crawl + trafilatura + NFC/ftfy → LID → Gopher+C4 → exact+MinHash dedup → PII → ChatML JSONL. DVC. Seed + checkpoint + Prometheus.
- **P1 — ✅ xong:** Playwright render (§3.2), profiling+clustering (§6), decontam (§5.6), quality classifier (§5.3), VN overrides (§5.3/§11), arq worker wiring; cross-dedup Zyda-2 + mix (§8) cũng đã có.
- **P2:** NeMo GPU dedup (A100 burst), semantic dedup.
- **P3:** service polish (job progress/eta), Grafana dashboard, Langfuse (nếu có LLM-judge).