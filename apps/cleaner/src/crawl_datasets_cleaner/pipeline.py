"""S3 clean pipeline (§5) — orchestrate theo đúng thứ tự FineWeb ablation.

normalize(§5.1) → LID(§5.2) → Gopher rep → Gopher quality(§5.3) → C4 → FineWeb custom
→ exact + MinHash dedup(§5.4) → PII(§5.5) → decontam(§5.6).

Fail-closed: mỗi drop có reason (log + Prometheus). Streaming shard, NFC trước dedup,
stable ID, provenance đầy đủ (§0). Không load-all.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from crawl_datasets_common.observability import (
    get_logger,
    record_drop,
    records_total,
    stage_timer,
)
from crawl_datasets_common.schema import (
    LICENSE_TAGS,
    UNKNOWN_LICENSE,
    LicenseTag,
    make_provenance,
    stable_id,
)
from crawl_datasets_common.settings import Settings
from crawl_datasets_common.storage import StorageLayout, mark_done

from .decontam import Decontaminator
from .dedup import LSHIndex, MinHasher, content_hash, scope_key
from .filters import c4_filter, fineweb_custom, gopher_quality, gopher_repetition
from .lid import LanguageIdentifier
from .normalize import normalize_text
from .pii import redact_pii

log = get_logger("cleaner")
_STAGE = "S3"


@dataclass
class CleanStats:
    seen: int = 0
    kept: int = 0
    dropped: Counter[str] = field(default_factory=Counter)


def _parse_ts(value: object) -> datetime | None:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


class DocCleaner:
    """Áp pipeline §5 lên từng document. State (dedup/LID) sống suốt 1 lần chạy."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        c = settings.clean
        self.clean = c
        self.lid = LanguageIdentifier(c.lang_id)
        self.hasher = MinHasher(
            c.minhash.num_hashes, c.minhash.ngram, settings.global_.seed
        )
        self.lsh = LSHIndex(c.minhash.bands, c.minhash.rows)
        self.seen_hashes: set[str] = set()
        self.decontam = Decontaminator(c.decontam.ngram)
        self.lang_score_min: dict[str, float] = c.lang_score_min.model_dump()

    def clean_one(
        self, doc: Mapping[str, Any]
    ) -> tuple[dict[str, Any] | None, str | None]:
        raw = doc.get("text")
        source_url = doc.get("source_url")
        if not isinstance(raw, str) or not raw.strip():
            return None, "no_text"
        if not isinstance(source_url, str) or not source_url:
            return None, "no_source_url"  # fail-closed: provenance bắt buộc (§0)

        passed: list[str] = []
        text = normalize_text(raw)  # §5.1 — NFC trước mọi hash/dedup
        if not text:
            return None, "empty_after_normalize"

        lang, score = self.lid.detect(text)  # §5.2
        if lang not in self.clean.lang_allow:
            return None, f"lang_not_allowed:{lang}"
        if score < self.lang_score_min.get(lang, 1.0):
            return None, f"lang_score_low:{lang}"
        passed.append("lid")

        if (rep := gopher_repetition(text)) is not None:  # §5.3
            return None, rep
        qual = gopher_quality(
            text, self.clean.gopher_quality, lang, self.clean.vi_overrides
        )
        if qual is not None:
            return None, qual
        passed.append("gopher")

        text, c4_reason = c4_filter(text)  # §5.3 (có thể sửa text)
        if c4_reason is not None:
            return None, c4_reason
        passed.append("c4")

        if (fw := fineweb_custom(text)) is not None:  # §5.3
            return None, fw
        passed.append("fineweb")

        chash = content_hash(text)  # §5.4 exact — rẻ nhất, chạy đầu dedup
        if chash in self.seen_hashes:
            return None, "exact_dup"
        self.seen_hashes.add(chash)
        doc_id = stable_id(chash)

        sig = self.hasher.signature(text)  # §5.4 MinHash per-source
        if sig is not None:
            scope = scope_key(source_url, self.clean.minhash.scope)
            if self.lsh.add_or_is_dup(scope, doc_id, sig):
                return None, "minhash_dup"
        passed.append("dedup")

        redacted, pii_types = redact_pii(text, vi_regex=self.clean.pii.vi_regex)  # §5.5
        passed.append("pii")

        if self.decontam.is_contaminated(text):  # §5.6
            return None, "decontam"
        passed.append("decontam")

        raw_license = doc.get("license")
        lic: LicenseTag = (
            raw_license if raw_license in LICENSE_TAGS else UNKNOWN_LICENSE
        )
        prov = make_provenance(
            source_url=source_url,
            license_=lic,
            extractor=str(doc.get("extractor", "unknown")),
            pipeline_version=self.settings.global_.pipeline_version,
            seed=self.settings.global_.seed,
            filters_passed=passed,
            crawl_ts=_parse_ts(doc.get("crawl_ts")),
        )
        record = {
            "id": doc_id,
            "text": redacted,
            "lang": lang,
            "quality": None,  # quality classifier là P1 (§5.3)
            "pii_found": pii_types,
            "prov": prov.model_dump(mode="json"),
        }
        return record, None


def _iter_lines(in_dir: Path) -> Iterator[str]:
    if not in_dir.exists():
        return
    for f in sorted(in_dir.rglob("*.jsonl")):
        with f.open(encoding="utf-8") as fh:
            yield from fh


def run(in_dir: Path, out_dir: Path, settings: Settings) -> CleanStats:
    """Stream extracted JSONL → clean shard + `_SUCCESS`/manifest (idempotent)."""
    clean_tier = StorageLayout(root=out_dir).tier("clean")
    cleaner = DocCleaner(settings)
    stats = CleanStats()
    out_path = clean_tier / "part-00000.jsonl"

    def _inc(status: str) -> None:
        if records_total is not None:
            records_total.labels(stage=_STAGE, status=status).inc()

    with stage_timer(_STAGE), out_path.open("w", encoding="utf-8") as out_f:
        for line in _iter_lines(in_dir):
            if not line.strip():
                continue
            stats.seen += 1
            _inc("in")
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                stats.dropped["bad_json"] += 1
                record_drop(_STAGE, "bad_json")  # fail-closed: không nuốt im lặng
                continue
            record, reason = cleaner.clean_one(doc)
            if reason is not None:
                stats.dropped[reason] += 1
                record_drop(_STAGE, reason)
                _inc("dropped")
                continue
            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
            stats.kept += 1
            _inc("out")

    mark_done(
        clean_tier,
        n_records=stats.kept,
        metadata={
            "seen": stats.seen,
            "kept": stats.kept,
            "dropped": dict(stats.dropped),
            "lang_id": settings.clean.lang_id,
            "using_glotlid": cleaner.lid.using_glotlid,
            "minhash_scope": settings.clean.minhash.scope,
        },
    )
    log.info(
        "clean_summary", seen=stats.seen, kept=stats.kept, dropped=dict(stats.dropped)
    )
    return stats
