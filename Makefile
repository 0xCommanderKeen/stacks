.PHONY: install check dev api web samples types test-browser

install:
	uv sync --locked
	pnpm --dir frontend install --frozen-lockfile

types:
	uv run python scripts/export_schema.py
	pnpm --dir frontend types

check:
	uv run ruff check backend scripts
	uv run ruff format --check backend scripts
	uv run pytest -q
	$(MAKE) types
	git diff --exit-code -- openapi.json frontend/src/lib/schema.d.ts
	pnpm --dir frontend check
	pnpm --dir frontend lint
	pnpm --dir frontend build

api:
	uv run uvicorn stacks.app:create_app --factory --host 127.0.0.1 --port 8000

web:
	pnpm --dir frontend dev

samples:
	uv run python -m stacks.samples

test-browser:
	pnpm --dir frontend test
