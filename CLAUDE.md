# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A **single-document design repo**, not a code project. The only file is `crawl-clean-dataset-service.md` — a reference architecture (in Vietnamese) for a **Crawl → Clean → Build → Integrate** service that produces SFT/instruction-tuning datasets (Vietnamese + English/multilingual), targeting **RTX 4090 24GB local + A100 80GB burst on Vast.ai**.

There is no code, no package manifest, no tests, no build/lint tooling, and no git history. Do not invent commands or scaffold a project structure unless the user explicitly asks. When asked to "run" or "build" something, first confirm whether the user wants the design doc updated or a real implementation started.

## Document conventions (respect when editing)

- **Language:** Vietnamese prose with English technical terms kept as-is (e.g., "fail-closed", "shard", "MinHash+LSH"). Do not translate technical terms to Vietnamese.
- **Source markers:** every non-trivial claim is tagged. Preserve these tags on any edit:
  - `[src]` — has a direct source (see §Nguồn chính at the bottom).
  - `[2nd]` — inferred from a source or from recall.
  - `[guess]` — opinion/estimate, not verified.
  New claims must carry one of these markers. Never silently upgrade a `[guess]` to `[src]` without citing the source.
- **Structure:** the doc is numbered §0–§13 plus a sources section. Section numbers are referenced inline (e.g., "xem §4", "§5.3"). If you renumber sections, update every cross-reference.
- **Tables and Mermaid:** the architecture diagram in §1 and comparison tables (crawlers, extractors, dedup params, tool stack) are the doc's core. Keep table column order consistent across sections when adding rows.
- **Config example in §9.3** is the single source of truth for parameter names used elsewhere in the doc (e.g., `lang_score_min`, `minhash.bands`, `source_priority`). Renaming a key requires updating every reference.
- **Failure-modes table (§13)** mirrors design principles (§0) and stage-level warnings. If you add a new principle or caveat, add the paired failure mode.

## Domain-specific rules the doc encodes

These are design decisions the user has committed to — don't propose changes that contradict them without flagging the conflict:

- **Fail-closed everywhere.** A verifier exception = FAIL, never PASS. Records missing provenance (`source_url`, `crawl_ts`, `license`, `extractor`, `pipeline_version`, `filters_passed[]`) do not enter the dataset.
- **Per-stage checkpointing with `_SUCCESS` markers**, shard-based streaming, idempotent reruns. Never suggest "load everything into memory" patterns.
- **Extraction is separated from crawling** (S1 stores raw HTML/WARC; S2 extracts). This is deliberate so extractors can be replayed without re-crawling.
- **Deduplication is per-source / per-crawl by default**, not global (FineWeb ablation result). Cross-dataset dedup (§8.2) is the exception, with source ranking priority.
- **Vietnamese overrides are required** in §5.3: English Gopher stop-words and mean-word-length rules do not transfer to Vietnamese. Unicode NFC normalization is mandatory before any hashing/dedup.
- **License gate is fail-closed:** `license:unknown` records are kept in raw tier for audit but excluded from any published/released dataset.
- **Hardware split:** CPU-bound work (crawl/extract/filter/CPU-MinHash via datatrove) stays local; GPU-heavy dedup (NeMo Curator fuzzy/semantic) is A100 burst only; 4090 handles embeddings (BGE-M3), small classifiers, and modest semantic dedup.
- **Tool defaults:** trafilatura (extract), GlotLID-M v3 (LID), datatrove (pipeline backbone), Presidio + VN regex (PII), DVC + HF Hub (versioning), FastAPI + arq (service/queue). Do not switch defaults casually — the doc justifies each choice.

## When adding a new source

If citing a paper, use the arXiv ID format already in the doc (e.g., `arXiv 2406.17557`) and add it to the "Nguồn chính" list at the bottom, then tag the claim `[src]`.
