# crawl-datasets-common

Shared library cho tất cả stages/services. Định nghĩa contract:

- `settings` — Pydantic config (§9.3 single source of truth)
- `schema` — SFT record + Provenance + stable ID (§7.2)
- `storage` — tiers + checkpointing (`_SUCCESS`, `manifest.json`)
- `observability` — structlog + Prometheus counter
- `provenance` — verify provenance đầy đủ (§0 fail-closed)

## Nguyên tắc

- Mọi threshold, model name, scope đều đi qua `Settings` — không hardcode.
- Mọi record SFT đều phải mang provenance. Thiếu → drop (fail-closed).
- `license:unknown` → `Provenance.is_publishable == False` → loại khỏi release.