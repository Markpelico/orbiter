# ORBITER developer entrypoints. CI calls these; humans can too.
# On Windows without make, run the underlying commands directly.

.PHONY: install lint typecheck test test-integration check up down api worker relay

install:
	uv sync

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

typecheck:
	uv run mypy

test:
	uv run pytest

test-integration:
	uv run pytest -m integration

check: lint typecheck test

# Local stack (requires Docker)
up:
	docker compose up -d --build

down:
	docker compose down -v

api:
	uv run uvicorn orbiter.api.app:create_app --factory --host 0.0.0.0 --port 8000

worker:
	uv run python -m orbiter.worker.main

relay:
	uv run python -m orbiter.relay.outbox_relay
