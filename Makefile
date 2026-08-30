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
local-up:
	docker compose up -d --build

local-down:
	docker compose down -v

# Cloud platform (requires AWS credentials + Terraform). THE METER:
# `make up` starts billing ~$0.30/hour; `make down` stops it. Always down
# at the end of a session.
up:
	terraform -chdir=deploy/terraform/platform init
	terraform -chdir=deploy/terraform/platform apply -auto-approve
	aws eks update-kubeconfig --name orbiter --region us-east-1
	kubectl apply -f deploy/k8s/karpenter/

down:
	-kubectl delete -k deploy/k8s --ignore-not-found --timeout=120s
	-kubectl delete -f deploy/k8s/karpenter/ --ignore-not-found --timeout=120s
	terraform -chdir=deploy/terraform/platform destroy -auto-approve

deploy:
	gh workflow run deploy.yml
	gh run watch $$(gh run list --workflow=deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId')

status:
	kubectl -n orbiter get pods,statefulsets,scaledobjects -o wide

port-forward:
	kubectl -n orbiter port-forward svc/api 8000:8000

# Load test against the local compose stack (3 min, 6 rate windows), then
# render the RESULTS.md charts from the summary + Prometheus.
load:
	docker run --rm --network orbiter_default \
	  -v ./deploy/load:/scripts grafana/k6 run \
	  --summary-export /scripts/summary.json /scripts/submit.js

charts:
	uv run scripts/make_charts.py --summary deploy/load/summary.json \
	  --start $(START) --end $(END)

api:
	uv run uvicorn orbiter.api.app:create_app --factory --host 0.0.0.0 --port 8000

worker:
	uv run python -m orbiter.worker.main

relay:
	uv run python -m orbiter.relay.outbox_relay
