#!/usr/bin/env bash
# Smoke E2E (§2–§8): serve fixture site local → chạy S0..S6 thật qua CLI → data/smoke/ + report.
# Chạy được trên máy CPU-only (core pure-Python; backend nặng gated tự fallback).
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${SMOKE_PORT:-8931}"
OUT="data/smoke"
SITE="tests/fixtures/smoke_site"
BASE="http://127.0.0.1:${PORT}"
PY=".venv/bin/python"
BIN=".venv/bin"

rm -rf "$OUT"
mkdir -p "$OUT"

"$PY" -m http.server "$PORT" --directory "$SITE" --bind 127.0.0.1 >/dev/null 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT
for _ in $(seq 1 50); do
  curl -fsS "$BASE/robots.txt" >/dev/null 2>&1 && break
  sleep 0.1
done

echo "== S0 probe =="
"$BIN/crawl-datasets-probe"   --url "$BASE/" --out "$OUT/s0"
echo "== S1 crawl =="
"$BIN/crawl-datasets-crawl"   --seeds "$BASE/" --depth 2 --out "$OUT/s1"
echo "== S2 extract =="
"$BIN/crawl-datasets-extract" --in "$OUT/s1/raw" --out "$OUT/s2"
echo "== S3 clean =="
"$BIN/crawl-datasets-clean"   --in "$OUT/s2/extracted" --out "$OUT/s3"
echo "== S4 profile =="
"$BIN/crawl-datasets-profile" --in "$OUT/s3/clean" --out "$OUT/s4"
echo "== S5 build =="
"$BIN/crawl-datasets-build"   --in "$OUT/s3/clean" --out "$OUT/s5"
echo "== S6 integrate =="
mkdir -p "$OUT/base_empty"
"$BIN/crawl-datasets-integrate" --base "$OUT/base_empty" --new "$OUT/s5/dataset" --out "$OUT/s6"

echo "== report =="
"$PY" scripts/smoke_report.py "$OUT"
