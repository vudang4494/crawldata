"""Tổng hợp report cho smoke E2E run — đọc manifest/_SUCCESS mọi tier → markdown.

Stdlib-only. Dùng bởi scripts/smoke_e2e.sh;
chạy tay: python scripts/smoke_report.py data/smoke
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())


def main(out_root: str) -> int:
    root = Path(out_root)
    tiers = {
        "S1 raw": root / "s1" / "raw",
        "S2 extracted": root / "s2" / "extracted",
        "S3 clean": root / "s3" / "clean",
        "S5 dataset": root / "s5" / "dataset",
    }

    lines: list[str] = ["# Smoke E2E report", ""]

    profile_s0 = _load_json(root / "s0" / "source_profile.json")
    lines += [
        "## S0 probe (§2)",
        "",
        f"- url: `{profile_s0.get('url', '?')}` · fetched: {profile_s0.get('fetched')}",
        f"- render: `{profile_s0.get('render')}`"
        f" · license: `{profile_s0.get('license')}`"
        f" · crawl_delay: {profile_s0.get('crawl_delay')}",
        f"- seed_urls từ sitemap: {len(profile_s0.get('seed_urls', []))}",
        "",
        "## Stage manifests (per-tier `_SUCCESS` + `manifest.json`)",
        "",
        "| Tier | _SUCCESS | records | dropped (reason: n) |",
        "|---|---|---|---|",
    ]

    ok = True
    for name, tier in tiers.items():
        success = (tier / "_SUCCESS").exists()
        ok = ok and success
        manifest = _load_json(tier / "manifest.json")
        n = manifest.get("n_records", "?")
        dropped = manifest.get("metadata", {}).get("dropped", {})
        drop_str = ", ".join(f"{k}: {v}" for k, v in sorted(dropped.items())) or "—"
        lines.append(f"| {name} | {'✅' if success else '❌'} | {n} | {drop_str} |")

    prof = _load_json(root / "s4" / "profile_report.json")
    lines += [
        "",
        "## S4 profile (§6)",
        "",
        f"- n_docs: {prof.get('n_docs')} · lang_dist: {prof.get('lang_dist')}",
        f"- license_dist: {prof.get('license_dist')}",
        f"- pii: {prof.get('pii_found_frac')}"
        f" · suggestions: {len(prof.get('suggestions', []))}",
    ]
    for s in prof.get("suggestions", []):
        lines.append(f"  - {s}")
    if prof.get("clustering_skipped"):
        skip = prof["clustering_skipped"]
        lines.append(f"- clustering_skipped: `{skip}` (§6 advisory)")

    mix = _load_json(root / "s6" / "mix_manifest.json")
    final_n = _count_lines(root / "s6" / "part-00000.jsonl")
    lines += [
        "",
        "## S6 integrate (§8)",
        "",
        f"- final records: {final_n}",
        f"- mix_manifest: {json.dumps(mix, ensure_ascii=False)}",
        "",
        "## Sample record (dataset tier, record đầu)",
        "",
    ]
    sample_path = root / "s5" / "dataset" / "part-00000.jsonl"
    if sample_path.exists():
        with sample_path.open(encoding="utf-8") as fh:
            first = fh.readline().strip()
        if first:
            pretty = json.dumps(json.loads(first), ensure_ascii=False, indent=2)
            if len(pretty) > 2200:
                pretty = pretty[:2200] + "\n… (cắt bớt)"
            lines += ["```json", pretty, "```"]

    verdict = "PASS" if ok and final_n > 0 else "FAIL"
    lines += ["", f"## Kết luận: **{verdict}**", ""]
    if verdict == "PASS":
        lines.append(
            "Chuỗi S0→S6 chạy hết, mọi tier có `_SUCCESS`, dataset cuối có record."
        )
    else:
        lines.append(
            "Thiếu `_SUCCESS` hoặc dataset cuối rỗng — xem bảng manifest ở trên."
        )

    report_path = root / "smoke_report.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"report: {report_path}")
    print(f"verdict: {verdict} (final records: {final_n})")
    return 0 if verdict == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "data/smoke"))
