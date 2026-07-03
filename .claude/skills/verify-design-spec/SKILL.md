---
name: verify-design-spec
description: Verify any code, config, or plan for the CrawlDatasets project against crawl-clean-dataset-service.md, the product source of truth. Use when reviewing/writing crawler, cleaner, dataset-builder, or integrator code; when editing pipeline YAML; when the user asks to "check", "verify", "validate", "audit", or "compliance-check" against the spec; or before merging changes that touch the crawl→clean→build→integrate pipeline.
---

# verify-design-spec

Product source of truth: [`crawl-clean-dataset-service.md`](../../../crawl-clean-dataset-service.md). Every implementation decision (tool choice, config key, filter threshold, pipeline order, hardware target) is fixed by that doc. This skill runs the check.

**Paths below are relative to the repo root `/Users/vudang/PythonLab/CrawlDatasets/`.**

## Run (agent path) — FIRST

Audit the design doc itself (integrity check — always safe):

```bash
node .claude/skills/verify-design-spec/verify.mjs
```

Verify a candidate file/directory against spec rules:

```bash
node .claude/skills/verify-design-spec/verify.mjs --target path/to/code_or_config
```

Machine-readable output (JSON):

```bash
node .claude/skills/verify-design-spec/verify.mjs --json
```

Exit codes: `0` clean, `1` warnings only, `2` errors present.

## What the driver checks

**On the spec itself:**
- Source markers `[src]` / `[2nd]` / `[guess]` counted and reported (baseline: 51 / 15 / 11 as of 2026-07-03). Adding claims without markers is a spec regression.
- All §X and §X.Y cross-references resolve to real headers.
- Mermaid flowchart in §1 parses and contains all pipeline nodes `S0..S6`.
- §9.3 config block declares the canonical keys: `seed`, `pipeline_version`, `render`, `lang_id`, `lang_allow`, `minhash`, `pii`, `decontam`, `source_priority`, `mix_ratios`.
- Non-negotiable invariants from §0 + §13 are present in the doc: fail-closed, NFC, per-source/per-crawl dedup, stable ID / AddId, `license:unknown` exclusion, decontamination gate, per-record provenance, per-stage checkpointing.
- Default tool names from §10 are actually mentioned somewhere in the spec: trafilatura, GlotLID, datatrove, Presidio, DVC, FastAPI, arq, Scrapy, Playwright, BGE-M3, NeMo Curator.

**On a `--target` (Python/TS/YAML/TOML files, recursively):**

Python/TS/JS violations:
- `load_dataset(...).to_list(...)` — violates §0/§9.1 "streaming, not load-all".
- `BeautifulSoup` import — §9.1 mandates `selectolax`/`lxml`.
- Bare `except Exception: pass` — violates §0 fail-closed (verifier errors must FAIL, not silently pass).
- `license = "unknown"` or `"license": "unknown"` — §2/§13 requires `license:unknown` records be excluded from release datasets.
- `normalize = "NFKD"` — §5.1/§11 requires NFC for Vietnamese.
- `lang_id = "cld3"` — §5.2 requires GlotLID-M v3 over CLD3.
- `LicenseTag.<attr>` — §7.2 `LicenseTag` is a `Literal`, not an `Enum`; attribute access crashes at runtime (use `UNKNOWN_LICENSE` or a string value).

YAML/TOML config violations:
- `scope: global` under `minhash` — §5.4/§13 requires `per_source` / `per_crawl`.
- `respect_robots: false` — §2 legal gate is fail-closed.
- `pyproject.toml` missing `[project]` (or `[tool.uv.workspace]` on the root) — PEP 621: uv can't build/resolve the package.

Extend the two rule tables inside `verify.mjs` (`violations` and `cfgViolations`) as new spec-derived invariants come up.

## When to run

- **Before writing code** for any pipeline stage: read the relevant §, then codify with these rules.
- **On every config edit** to a pipeline YAML: run with `--target <yaml>`.
- **On every PR touching S0–S6**: run with `--target apps/<crawler>/src` (or equivalent).
- **After editing the spec**: re-run the no-arg audit — any new red is a doc regression (a broken cross-ref, a missing tool default, a dropped invariant).

## Gotchas

- The `[src]` / `[2nd]` / `[guess]` counts are informational, not gated — the doc's honest citation practice depends on humans, not this script. But the counts should never drop without justification (removed a source? or forgot to tag?).
- Target scanner is a **linter, not a type-checker**. It catches obvious violations by pattern; it does not prove correctness. A file that passes still needs human review against the spec.
- YAML rule engine reads files as text; comments containing violating strings will false-positive. Prefer keeping the violating patterns out of comments too — they're anti-patterns.
- Scanner skips `node_modules/` and any `.git*` path; extend the walker in `verify.mjs` if new build directories appear (e.g. `.venv`, `dist`, `build/`).
- The verifier resolves the spec at `../../../crawl-clean-dataset-service.md` relative to `verify.mjs`. If the spec is renamed or moved, update `SPEC_PATH` in `verify.mjs`.

## Provenance

Design doc is authored in Vietnamese with `[src]`/`[2nd]`/`[guess]` markers. All product decisions (crawl framework, extractor, LID, dedup params, PII backend, format, versioning, hardware split, mix ratios, VN overrides) are fixed by the doc — this skill enforces the contract. See `CLAUDE.md` at the repo root for the human-readable summary of the doc's conventions.
