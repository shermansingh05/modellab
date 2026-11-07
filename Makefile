.PHONY: setup demo test lint api web real

setup:
	uv sync
	cd apps/web && npm ci
	@[ -f .env ] || (printf 'MODELLAB_ADMIN_TOKEN=%s\n' "$$(openssl rand -hex 24)" > .env && chmod 600 .env)

demo:
	uv run modellab demo

test:
	uv run pytest

lint:
	uv run ruff check .
	cd apps/web && npm run typecheck

api:
	set -a; . ./.env; set +a; uv run modellab api

web:
	cd apps/web && npm run build && set -a && . ../../.env && set +a && npm start

real:
	uv run modellab eval run configs/experiments/a_refusal_parent_vs_abliterated.yaml
	uv run modellab eval run configs/experiments/h_guardrail_layers.yaml
