# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A **Crawl → Clean → Build → Integrate** service for producing SFT/instruction-tuning datasets (Vietnamese + English/multilingual), targeting **RTX 4090 24GB local + A100 80GB burst on Vast.ai**. Two layers:

1. **The spec — `crawl-clean-dataset-service.md`** (Vietnamese reference architecture, §0–§13) is the **product source of truth**. Every implementation decision (tool choice, config key, threshold, pipeline order, hardware target) is fixed by it.
2. **A uv-workspace monorepo skeleton** implementing that spec: `apps/` (one package per stage S0–S6 + `service`) and `libs/common` (shared contract). As of the current P0 phase, every stage entrypoint is a **TODO stub** (logging + fail-closed guards + checkpoint markers, no real pipeline logic yet) — the contract layer (config/schema/storage/observability/DVC/service) is wired, the processing is not.

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
| Reproduce pipeline | `make dvc-repro` (`uv run dvc repro`) |
| Run service | `make run-service` (uvicorn `crawl_datasets_service.main:app`) |

- **Single test:** `uv run pytest tests/test_schema.py::test_stable_id_is_deterministic` (or `pytest -k <expr>`). `tests/conftest.py` puts every `apps/*/src` + `libs/*/src` on `sys.path`, so tests run **without** an install.
- **Spec compliance on a file/dir:** `node .claude/skills/verify-design-spec/verify.mjs --target <path>` (exit 0 clean, 1 warn, 2 error). Run this before merging anything touching S0–S6.

**Known caveat (P0):** `uv sync` / `uv run` / `uv lock` currently fail during resolution — several **optional** extras pin non-existent PyPI packages (`glotlid`, `nemo-curator`, `rs-trafilatura`; GlotLID actually ships via HuggingFace). This blocks the `uv`-based `make` targets but not the core code. Until those pins are fixed, run tools standalone:

```bash
ruff check apps libs tests
node .claude/skills/verify-design-spec/verify.mjs
# tests / mypy in a throwaway env (conftest handles sys.path):
uv run --no-project --with pytest --with pydantic --with pyyaml --with structlog --with click pytest tests/
```
`mypy --strict` additionally needs `types-PyYAML` + `prometheus-client` installed (and the `libs/common/.../py.typed` marker, which must stay present).

## Architecture (big picture)

- **uv workspace:** `libs/common` (shared contract) + `apps/{probe,crawler,extractor,cleaner,profiler,builder,integrator,service}`. Each pipeline app is an independent package exposing a `crawl-datasets-<x>` console script (`__main__.py`); `service` is a FastAPI + arq app (no CLI). Every app depends on `crawl-datasets-common` (resolved via `[tool.uv.sources]` workspace, not PyPI). Root `pyproject.toml` is a **virtual** workspace root (`[tool.uv.workspace]`, no `[project]`).
- **Immutable storage tiers** (`libs/common/storage.py`): `raw/` → `extracted/` → `clean/` → `dataset/`. Each tier is the immutable input of the next, so the pipeline replays from any point. Stages read/write **shards** and drop a `_SUCCESS` marker + `manifest.json` per shard; reruns skip completed shards (idempotent). Never load a whole tier into memory.
- **Pipeline stages** map 1:1 to spec sections: S0 probe (§2) → S1 crawl (§3) → S2 extract (§4) → S3 clean/core (§5) → S4 profile (§6) / S5 build (§7) → S6 integrate (§8). **`dvc.yaml`** declares each stage's `deps/outs/params`, so changing a config param triggers `dvc repro` to rerun only affected stages — this is the reproducibility gate (§7.3). `raw/` and large tiers are `cache: false` (immutable / large).
- **Config as single source of truth:** `configs/default.yaml` ⟷ `libs/common/settings.py` (Pydantic models) ⟷ spec **§9.3**, key-for-key. `configs/dev.yaml` = local overrides; resolution order is explicit path > `CDS_CONFIG` env > `configs/default.yaml`. Never hardcode thresholds/model literals. Renaming a key means updating the YAML, `settings.py`, **and** every §9.3 reference in the spec.
- **Contract types** (`libs/common/schema.py`, spec §7.2): `SFTRecord` + `Provenance` + `stable_id()`. Fail-closed provenance is enforced by Pydantic required fields + `provenance.verify_provenance`. `LicenseTag` is a `Literal`, **not an `Enum`** — use the `UNKNOWN_LICENSE` constant / a string value, never attribute access (`LicenseTag.unknown` crashes; the verifier flags it).
- **Observability** (`libs/common/observability.py`, §9.4): structlog JSON + Prometheus counters (`stage_records_total`, `drop_reason_total`, `stage_duration_seconds`). The prometheus_client import is guarded so the skeleton runs without it.

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
