.PHONY: help install sync lint format type test audit verify docker-up docker-down dvc-repro run-service run-worker

help:
	@echo "Targets:"
	@echo "  install      Install uv (one-time)"
	@echo "  sync         uv sync --all-extras --all-groups"
	@echo "  lint         ruff check apps libs"
	@echo "  format       ruff format apps libs"
	@echo "  type         mypy apps libs"
	@echo "  test         pytest"
	@echo "  audit        node .claude/skills/verify-design-spec/verify.mjs"
	@echo "  verify       full gate: lock-check + spec scan + lint + type + test"
	@echo "  docker-up    docker compose -f ops/docker-compose.yml up -d"
	@echo "  docker-down  docker compose -f ops/docker-compose.yml down"
	@echo "  dvc-repro    dvc repro"
	@echo "  run-service  uvicorn crawl_datasets_service.main:app --reload"
	@echo "  run-worker   arq crawl_datasets_service.worker.WorkerSettings (cần Redis)"

install:
	curl -LsSf https://astral.sh/uv/install.sh | sh

sync:
	uv sync --all-extras --all-groups

lint:
	uv run ruff check apps libs

format:
	uv run ruff format apps libs

type:
	uv run mypy apps libs

test:
	uv run pytest

audit:
	node .claude/skills/verify-design-spec/verify.mjs

# Gate đầy đủ trước khi merge — V1 lock, V2+V3 spec/compliance, V5 lint, V6 type, V7 test.
verify:
	uv lock --check
	node .claude/skills/verify-design-spec/verify.mjs --target .
	uv run ruff check apps libs tests
	uv run mypy apps libs
	uv run pytest -q

docker-up:
	docker compose -f ops/docker-compose.yml up -d

docker-down:
	docker compose -f ops/docker-compose.yml down

dvc-repro:
	uv run dvc repro

run-service:
	uv run --package crawl-datasets-service uvicorn crawl_datasets_service.main:app --reload

# Worker arq (cần Redis: make docker-up)
run-worker:
	uv run --package crawl-datasets-service arq crawl_datasets_service.worker.WorkerSettings