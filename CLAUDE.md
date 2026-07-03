# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A **Crawl → Clean → Build → Integrate** service for producing SFT/instruction-tuning datasets (Vietnamese + English/multilingual), targeting **RTX 4090 24GB local + A100 80GB burst on Vast.ai**. Two layers:

1. **The spec — `crawl-clean-dataset-service.md`** (Vietnamese reference architecture, §0–§13) is the **product source of truth**. Every implementation decision (tool choice, config key, threshold, pipeline order, hardware target) is fixed by it.
2. **A uv-workspace monorepo** implementing that spec: `apps/` (one package per stage S0–S6 + `service`) and `libs/common` (shared contract). **All seven stages S0–S6 have real pipeline logic** (pure-Python core; heavy backends gated — see patterns below). What is still P1/hook-only: quality classifier, BGE-M3/UMAP/HDBSCAN clustering in S4, Playwright JS-render, arq worker wiring.

Before writing or reviewing pipeline code, read the relevant §, then run the **verify-design-spec** skill (below) — it enforces the spec contract. Do not change spec-fixed decisions without flagging the conflict.

## Commands

Canonical targets (`Makefile`):

| Task | Command |
|---|---|
| Sync workspace + dev deps | `make sync` (`uv sync --all-extras --all-groups`) |
| Lint / format | `make lint` (`ruff check apps libs`) · `make format` |
| Type-check (strict) | `make type` (`mypy apps libs`) |
| Tests | `make test` (`uv run pytest`) |
| Audit against spec | `make audit` (`node .claude/skills/verify-design-spec/verify.mjs`) |
| **Full gate (pre-merge)** | `make verify` (lock-check + spec scan `--target .` + lint + type + test) |
| Reproduce pipeline | `make dvc-repro` (`uv run dvc repro`) |
| Run service | `make run-service` (uvicorn `crawl_datasets_service.main:app`) |

- **Single test:** `uv run pytest tests/test_cleaner.py::test_pipeline_end_to_end` (or `pytest -k <expr>`). `tests/conftest.py` puts every `apps/*/src` + `libs/*/src` on `sys.path`, so tests import `crawl_datasets_*` **without** an install.
- **Spec compliance on a file/dir:** `node .claude/skills/verify-design-spec/verify.mjs --target <path>` (exit 0 clean, 1 warn, 2 error). Run before merging anything touching S0–S6.

**Fast dev loop (no heavy install):** a full sync pulls heavy deps (datatrove, presidio→spaCy, pyarrow; torch via the `embed` extra). The whole pure-Python core + tests run **without** those (gated backends fall back — see below), so the quick path is a throwaway env:
```bash
ruff check apps libs tests
uv run --isolated --no-project --with pytest --with pydantic --with pyyaml --with structlog --with click pytest tests/
```
`--isolated` matters: without it uv layers onto `.venv`, so already-installed heavy backends leak in and you are NOT testing the fallback path. Tests must stay deterministic in **both** env states: force the fallback by monkeypatching the gated global (`html_extract._trafilatura`, `sys.modules["presidio_analyzer"]`), and `pytest.skip` backend-only tests when the import is absent — see `tests/test_extractor.py` / `tests/test_cleaner.py`.

`mypy --strict` needs the full env (`uv sync --all-groups`); cross-package module mapping is configured via `mypy_path` in the root `pyproject.toml` (add new members there), and requires the `libs/common/.../py.typed` marker (its absence silently makes mypy skip cross-package types). Untyped third-party libs are allow-listed under `[[tool.mypy.overrides]]` — add new gated backends there.

**Dependency window:** S4 clustering deps (umap-learn/hdbscan → numba/llvmlite) live behind the profiler's `cluster` extra — never as base deps (guarded by `tests/test_packaging.py::test_heavy_backends_are_extras_not_base_deps`). Universal resolution is capped at `python_version < '3.14'` via `[tool.uv] environments` in the root `pyproject.toml`; without the cap, the resolver satisfies future-Python forks with 2021-era sdist-only llvmlite and `uv sync` breaks at build time.

## Architecture (big picture)

- **uv workspace:** `libs/common` (shared contract) + `apps/{probe,crawler,extractor,cleaner,profiler,builder,integrator,service}`. Each pipeline app is an independent package exposing a `crawl-datasets-<x>` console script (`__main__.py`); `service` is a FastAPI + arq app (no CLI). Every app depends on `crawl-datasets-common` (resolved via `[tool.uv.sources]` workspace, not PyPI). Root `pyproject.toml` is a **virtual** workspace root (`[tool.uv.workspace]`, no `[project]`).
- **Immutable storage tiers** (`libs/common/storage.py`): `raw/` → `extracted/` → `clean/` → `dataset/`. Each tier is the immutable input of the next, so the pipeline replays from any point. Stages read/write **shards** and drop a `_SUCCESS` marker + `manifest.json` per shard; reruns skip completed shards (idempotent). Never load a whole tier into memory.
- **Pipeline stages** map 1:1 to spec sections: S0 probe (§2) → S1 crawl (§3) → S2 extract (§4) → S3 clean/core (§5) → S4 profile (§6) / S5 build (§7) → S6 integrate (§8). **`dvc.yaml`** declares each stage's `deps/outs/params`, so changing a config param triggers `dvc repro` to rerun only affected stages — this is the reproducibility gate (§7.3). `raw/` and large tiers are `cache: false` (immutable / large).
- **Config as single source of truth:** `configs/default.yaml` ⟷ `libs/common/settings.py` (Pydantic models) ⟷ spec **§9.3**, key-for-key. `configs/dev.yaml` = local overrides; resolution order is explicit path > `CDS_CONFIG` env > `configs/default.yaml`. Never hardcode thresholds/model literals. Renaming a key means updating the YAML, `settings.py`, **and** every §9.3 reference in the spec.
- **Contract types** (`libs/common/schema.py`, spec §7.2): `SFTRecord` + `Provenance` + `stable_id()`. Fail-closed provenance is enforced by Pydantic required fields + `provenance.verify_provenance`. `LicenseTag` is a `Literal`, **not an `Enum`** — use the `UNKNOWN_LICENSE` constant / a string value, never attribute access (`LicenseTag.unknown` crashes; the verifier flags it).
- **Observability** (`libs/common/observability.py`, §9.4): structlog JSON + Prometheus counters (`stage_records_total`, `drop_reason_total`, `stage_duration_seconds`). The prometheus_client import is guarded so code runs without it.
- **Shared helpers** in `libs/common`: `fetch.py` (`http_get` / `FetchResult`, httpx-gated — S0/S1 accept an injectable `fetch` callable so tests never hit the network) and `licensing.py` (`detect_license`, used by both S0 probe and S2 extract per §2 "ghi license từ S0/S2").

## Per-stage code pattern (follow it when extending a stage)

Every pipeline app has the same shape — match it:
- **`pipeline.py`** holds the real logic: a `run(in_dir, out_dir, settings) -> XStats` that **streams** input shards, applies the stage, `record_drop(stage, reason)` on every rejection (fail-closed, never silently skip), writes an output shard, and calls `mark_done(tier, ...)`. `XStats` is a `@dataclass` with a `dropped: Counter[str]`.
- **`__main__.py`** is a thin `click` CLI that loads settings, logs start, calls `pipeline.run`, logs done. No logic here.
- **Specialized modules** hold the pure functions (e.g. cleaner: `normalize`/`lid`/`filters`/`dedup`/`pii`/`decontam`; probe: `probe.py`; crawler: `frontier.py`). Keep them pure and unit-testable.
- **Gated optional backend** — the load-bearing pattern. Heavy/optional deps (httpx, trafilatura, pymupdf, datatrove, fasttext/GlotLID, Presidio, pyarrow) are imported behind `try/except ImportError` into an `_x: Any = None` module global, with a **pure-Python fallback** (stdlib HTML stripper, VN/EN LID heuristic, regex-only PII, JSONL-instead-of-Parquet). This keeps the core runnable and every test green with zero heavy installs. Never add a hard top-level import of a heavy dep; gate it and provide a fallback (and add it to the mypy overrides).
- **Determinism:** anything random (MinHash hash coefficients, sampling) is seeded from `settings.global_.seed`; use `hashlib` (blake2b), never Python's salted `hash()`. Dedup is per-source in S3 (`dedup.py`) but GLOBAL-with-ranking in S6 (`crossdedup.py`, Zyda-2) — that's the one sanctioned global dedup (§8.2).
- **Data contract between stages** (JSONL records): crawl→`{source_url, html, crawl_ts, content_type}` · extract→`{id, text, source_url, crawl_ts, license, extractor}` · clean→adds `lang`/`pii_found`/`prov` · build→ChatML/ShareGPT/Alpaca with a `meta` block. An `tests/test_pipeline_e2e.py` exercises S1→S6 with an injected fetcher.

## Document conventions (respect when editing the spec)

- **Language:** Vietnamese prose with English technical terms kept as-is (e.g., "fail-closed", "shard", "MinHash+LSH"). Do not translate technical terms to Vietnamese.
- **Source markers:** every non-trivial claim is tagged. Preserve these tags on any edit:
  - `[src]` — has a direct source (see §Nguồn chính at the bottom).
  - `[2nd]` — inferred from a source or from recall.
  - `[guess]` — opinion/estimate, not verified.
  New claims must carry one of these markers. Never silently upgrade a `[guess]` to `[src]` without citing the source. (The verifier counts markers; baseline 51/15/11.)
- **Structure:** the doc is numbered §0–§13 plus a sources section. Section numbers are referenced inline (e.g., "xem §4", "§5.3"). If you renumber sections, update every cross-reference — the verifier fails on unresolved `§X.Y` refs.
- **Tables and Mermaid:** the architecture diagram in §1 and comparison tables (crawlers, extractors, dedup params, tool stack) are the doc's core. Keep table column order consistent across sections when adding rows.
- **Config example in §9.3** is the single source of truth for parameter names used elsewhere. Renaming a key requires updating every reference (spec + `settings.py` + `configs/*.yaml`).
- **Failure-modes table (§13)** mirrors design principles (§0) and stage-level warnings. If you add a new principle or caveat, add the paired failure mode.

## Domain-specific rules the doc encodes

Design decisions the user has committed to — don't propose changes that contradict them without flagging the conflict:

- **Fail-closed everywhere.** A verifier exception = FAIL, never PASS. Records missing provenance (`source_url`, `crawl_ts`, `license`, `extractor`, `pipeline_version`, `filters_passed[]`) do not enter the dataset.
- **Per-stage checkpointing with `_SUCCESS` markers**, shard-based streaming, idempotent reruns. Never suggest "load everything into memory" patterns.
- **Extraction is separated from crawling** (S1 stores raw HTML/WARC; S2 extracts) so extractors can be replayed without re-crawling.
- **Deduplication is per-source / per-crawl by default**, not global (FineWeb ablation). Cross-dataset dedup (§8.2) is the exception, with source ranking priority. `minhash.scope: global` is rejected at config load.
- **Vietnamese overrides are required** in §5.3: English Gopher stop-words and mean-word-length rules do not transfer to Vietnamese. Unicode NFC normalization is mandatory before any hashing/dedup.
- **License gate is fail-closed:** `license:unknown` records are kept in raw tier for audit but excluded from any published/released dataset.
- **Hardware split:** CPU-bound work (crawl/extract/filter/CPU-MinHash via datatrove) stays local; GPU-heavy dedup (NeMo Curator fuzzy/semantic) is A100 burst only; 4090 handles embeddings (BGE-M3), small classifiers, and modest semantic dedup.
- **Tool defaults:** trafilatura (extract), GlotLID-M v3 (LID), datatrove (pipeline backbone), Presidio + VN regex (PII), DVC + HF Hub (versioning), FastAPI + arq (service/queue). Do not switch defaults casually — the doc justifies each choice.

## When adding a new source

If citing a paper, use the arXiv ID format already in the doc (e.g., `arXiv 2406.17557`) and add it to the "Nguồn chính" list at the bottom of the spec, then tag the claim `[src]`.
