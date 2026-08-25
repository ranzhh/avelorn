.PHONY: install test lint demo serve types frontend

# Which end-to-end demo `make demo` runs — any scripts/<DEMO>_demo.py:
# shooting, melee, turn, or soften_the_charge.
DEMO ?= shooting

install: ## install dependencies and git hooks
	uv sync
	uv run pre-commit install

test: ## run the test suite
	uv run pytest

lint: ## run all pre-commit hooks (ruff, ty, hygiene) on the full tree
	uv run pre-commit run --all-files

demo: ## end-to-end demo from the data files (DEMO=shooting|melee|charge)
	uv run python scripts/$(DEMO)_demo.py

serve: ## serve the unit database over HTTP, with reload (docs at /docs)
	uv run fastapi dev src/avelorn/api/app.py

types: ## regenerate the frontend's TypeScript types from the API's OpenAPI document
	uv run python scripts/dump_openapi.py frontend/openapi.json
	cd frontend && npx openapi-typescript openapi.json -o src/lib/api/schema.d.ts

frontend: ## serve the unit browser, with reload (needs `make serve` in another shell)
	cd frontend && npm run dev
