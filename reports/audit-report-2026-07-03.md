# Audit & Verify Report — CrawlDatasets

- **Ngày:** 2026-07-03
- **Phạm vi:** toàn bộ product (spec + 9 package + configs + ops + tests + verifier skill)
- **Kết luận:** ✅ **Toàn bộ gate xanh** sau 4 vòng react-fix. Lệnh vỡ ban đầu (`uv sync` / `make test` chết ở llvmlite build) đã hoạt động bình thường. Gate tổng: `make verify`.

---

## 1. Cấu trúc product

```
CrawlDatasets/
├── crawl-clean-dataset-service.md   # SPEC — product source of truth (473 dòng, §0–§13)
├── libs/common/                     # contract chung (528 LOC)
│   └── schema · settings · storage · provenance · licensing · fetch · observability
├── apps/                            # 7 stage + service, map 1:1 với spec
│   ├── probe/      S0 §2  (197 LOC)  probe.py
│   ├── crawler/    S1 §3  (215 LOC)  frontier.py
│   ├── extractor/  S2 §4  (355 LOC)  html_extract · pdf_extract
│   ├── cleaner/    S3 §5  (787 LOC)  normalize · lid · filters · dedup · pii · decontam
│   ├── profiler/   S4 §6  (186 LOC)  profile.py
│   ├── builder/    S5 §7  (208 LOC)  formats.py
│   ├── integrator/ S6 §8  (318 LOC)  crossdedup (Zyda-2) · mix
│   └── service/           (125 LOC)  FastAPI main + arq worker
├── tests/                           # 15 file test (~1.300 LOC), có e2e S1→S6 + bộ test verifier
├── configs/                         # default.yaml ⟷ settings.py ⟷ §9.3 (key-for-key)
├── dvc.yaml                         # repro gate — deps/outs/params per stage (§7.3)
├── ops/                             # Dockerfile, compose, Prometheus + Grafana funnel
├── Makefile                         # sync/lint/type/test/audit/verify/dvc-repro/run-service
└── .claude/skills/verify-design-spec/  # verifier (verify.mjs) + SKILL.md
```

Mỗi app đúng per-stage pattern: `pipeline.py` (logic thật: streaming shard, `record_drop`, `_SUCCESS`) + `__main__.py` (thin click CLI) + module thuần unit-testable. Backend nặng gate qua `try/except ImportError` với fallback pure-Python.

**Còn lại P1 (hook-only, chủ đích):** quality classifier, BGE-M3/UMAP/HDBSCAN clustering (S4), Playwright JS-render, arq worker wiring.

---

## 2. Phát hiện ban đầu (audit lần 1)

| # | Mức | Vấn đề | Nguyên nhân gốc |
|---|---|---|---|
| RC1 | **P0** | `uv sync`/`uv run`/`make test` vỡ trên Python 3.13 | `apps/profiler` khai `umap-learn`/`hdbscan` là **base dep** dù code không import (clustering là P1 hook) — vi phạm chính gated-backend pattern của repo |
| RC2 | **P0** | Lock pin `llvmlite 0.36.0` + `numba 0.53.1` (2021, sdist-only) | `requires-python = ">=3.12"` **không chặn trên** → universal resolver phải thỏa fork Python ≥3.14 → chọn bản cổ không khai upper-bound metadata → build từ source fail (`setup.py` guard: chỉ hỗ trợ <3.10) |
| RC3 | Trung bình | `verify.mjs --target .` báo 14 lỗi nhưng **toàn bộ là false positive** | Walker không skip `.venv`/cache; verifier tự flag chính nó (bảng rule chứa anti-pattern mẫu) |
| RC4 | Nhỏ | FP tại `tests/test_entrypoints.py:3` | Docstring chứa nguyên văn `LicenseTag.unknown` |
| RC5 | Trung bình | `make type` không chạy được native | Thiếu module map cho src-layout (trước đây phải set `MYPYPATH` tay) |
| RC6 | Trung bình | 3 test giả định "env chưa cài backend" | Khi backend cài thật (trafilatura, presidio) → hành vi đổi → test vỡ. Test không deterministic theo trạng thái env |
| RC7 | Nhỏ | Fast dev loop leak | `uv run --no-project` vẫn layer lên `.venv` → backend nặng lọt vào "throwaway env" |

---

## 3. Bộ verify tường minh (V1–V8) + kết quả cuối

| Gate | Lệnh | Kỳ vọng | Kết quả cuối |
|---|---|---|---|
| V1 | `uv lock` + `uv lock --check` | resolve sạch, lock fresh | ✅ llvmlite 0.36→**0.48.0**, numba 0.53→**0.66.0**, đủ wheel cp313 (llvmlite/numba/hdbscan 0.8.44/umap 0.5.12) |
| V2 | `node verify.mjs` (spec audit) | exit 0; markers 51/15/11 đúng baseline; đủ §0–§13, mermaid S0–S6, 26 keys §9.3 | ✅ |
| V3 | `node verify.mjs --target .` | exit 0, **0 false positive** | ✅ (trước fix: 14 FP) |
| V4 | `uv sync --all-groups` | cài full env sạch | ✅ (trước fix: vỡ ở llvmlite build) |
| V5 | `ruff check apps libs tests` | 0 lỗi | ✅ |
| V6 | `make type` (mypy `--strict`) | 0 lỗi, chạy native | ✅ Success: 46 source files |
| V7 | `make test` (`uv run pytest`) | all pass | ✅ **83 passed** (66 cũ + 17 mới) |
| V8a | `uv sync --all-extras --all-groups --dry-run` | plan cài được (extras `cluster`/`embed`) | ✅ |
| V8b | `uv run --isolated --no-project --with pytest ... pytest tests/` | env **không** backend nặng vẫn xanh | ✅ 82 passed + 1 skipped (test trafilatura tự skip — đúng thiết kế) |

**Gate 1 lệnh (mới):** `make verify` = `uv lock --check` → `verify.mjs --target .` → `ruff apps libs tests` → `mypy apps libs` → `pytest -q`. Kết quả: **xanh toàn bộ**.

---

## 4. Vòng react-fix (fix → chạy verify → còn sai → fix tiếp)

| Vòng | Gate fail | Lỗi | Fix |
|---|---|---|---|
| 1 | V3 | `Cannot access 'SKIP_DIRS' before initialization` — khối `const` khai báo sau lời gọi `scanTarget()` (temporal dead zone) | Chuyển khối `SELF`/`SKIP_DIRS` lên trước lời gọi trong `verify.mjs` |
| 2 | V6 | mypy không map được module src-layout (`source file found twice`); sau khi map, lộ **3 lỗi type thật** bị che từ trước: builder gán `None` vào Module `_pa`; presidio `AnonymizerEngine.__init__` untyped; 2 class `RecognizerResult` (analyzer vs anonymizer) lệch nhau | Codify `mypy_path` (9 src dirs) vào root `pyproject.toml`; builder dùng đúng pattern `_pa: Any = None`; anonymizer duck-typed qua `Any` (tránh `type: ignore` lệ thuộc env) |
| 3 | V7 | 3 test fail vì backend cài thật: `test_build_presidio_none_without_backend`, `test_extract_html_fallback_strips_boilerplate`, `test_s2_to_s3_end_to_end` (extractor trả `trafilatura-2.1.0` thay vì `htmlparser-fallback`) | Ép fallback tường minh bằng monkeypatch (`html_extract._trafilatura = None`, `sys.modules["presidio_analyzer"] = None`); thêm test mới cho path trafilatura thật (skip khi thiếu) |
| 4 | Gate cuối (ruff) | 2 lỗi I001 import chưa sort ở 2 file test vừa sửa | `ruff --fix` rồi chạy lại `make verify` trọn vẹn → xanh |

Phát hiện thêm khi xác minh V8: `uv run --no-project` **leak `.venv`** (trafilatura resolve từ `.venv/lib/.../site-packages`) → fast dev loop phải dùng `--isolated`; đã xác minh lại đúng thiết kế (82 pass + 1 skip) và cập nhật CLAUDE.md.

---

## 5. Fix gốc rễ + test case chống tái phát

### Packaging / resolution
- `apps/profiler/pyproject.toml`: umap-learn/hdbscan chuyển sang extra **`cluster`**, kèm floors `numba>=0.61` + `llvmlite>=0.44` (bản cổ không khai upper-bound metadata nên resolver có thể chọn nhầm sdist-only).
- Root `pyproject.toml`: **`[tool.uv] environments = ["python_version < '3.14'"]`** — chặn universal resolution rơi về llvmlite 2021; + **`mypy_path`** cho 9 member.

### Verifier
- `verify.mjs`: walker skip `SKIP_DIRS` (`.venv`, `venv`, `__pycache__`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `.dvc`, `dist`, `build`, `data`, `node_modules`) + `*.egg-info` + `.git*`, và **tự loại chính nó** (bảng rule chứa anti-pattern mẫu).

### Test case mới (17)
- **`tests/test_verifier.py`** (15 case): spec audit exit 0; repo-wide scan sạch; fixture sạch → exit 0; **mỗi rule code** (load-all, BeautifulSoup, except+pass, license:unknown, NFKD, cld3, LicenseTag-attr) và **mỗi rule config** (minhash scope global, respect_robots false, pyproject thiếu `[project]`) → exit 2; walker skip `.venv`/cache; verifier self-exclude. Fixture "xấu" ghép chuỗi runtime để chính file test không bị flag.
- **`tests/test_packaging.py::test_heavy_backends_are_extras_not_base_deps`**: dep nặng (umap/hdbscan/numba/llvmlite/sentence-transformers/FlagEmbedding/torch/playwright) xuất hiện ở base deps của bất kỳ member nào → fail ngay.
- **`tests/test_extractor.py::test_extract_html_uses_trafilatura_when_installed`**: cover path primary extractor thật (§4), skip khi thiếu backend.

### Docs đồng bộ
- `Makefile`: thêm target **`verify`**. `CLAUDE.md`: bảng Commands + fast loop `--isolated` + mục "Dependency window". `SKILL.md`: gotcha walker mới + quy trình thêm rule (mỗi rule mới phải kèm case trong `test_verifier.py`).

---

## 6. Trạng thái cuối & việc còn lại

- **`make verify`: xanh toàn bộ** — lock-check ✅ · spec+compliance ✅ · ruff ✅ · mypy strict 46 files ✅ · pytest 83/83 ✅.
- Thay đổi: 14 file (805+/661−, chủ yếu `uv.lock`), tại thời điểm viết report **chưa commit**.
- Việc còn lại (theo thiết kế, không phải lỗi): P1 hooks — quality classifier, clustering S4 (giờ cài được qua extra `cluster`), Playwright render, arq worker wiring.
