.PHONY: help install sync lint format type test audit docker-up docker-down dvc-repro run-service

help:
	@echo "Targets:"
	@echo "  install      Install uv (one-time)"
	@echo "  sync         uv sync --all-extras --all-groups"
	@echo "  lint         ruff check apps libs"
	@echo "  format       ruff format apps libs"
	@echo "  type         mypy apps libs"
	@echo "  test         pytest"
	@echo "  audit        node .claude/skills/verify-design-spec/verify.mjs"
	@echo "  docker-up    docker compose -f ops/docker-compose.yml up -d"
	@echo "  docker-down  docker compose -f ops/docker-compose.yml down"
	@echo "  dvc-repro    dvc repro"
	@echo "  run-service  uvicorn crawl_datasets_service.main:app --reload"

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

docker-up:
	docker compose -f ops/docker-compose.yml up -d

docker-down:
	docker compose -f ops/docker-compose.yml down

dvc-repro:
	uv run dvc repro

run-service:
	uv run --package service uvicorn crawl_datasets_service.main:app --reload