.PHONY: install test lint demo serve types types-check frontend frontend-lint frontend-test frontend-check up down logs

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

types: ## rewrite the committed OpenAPI document from the Pydantic models
	uv run python scripts/dump_openapi.py frontend/openapi.json
	cd frontend && npm run types

types-check: ## fail if the committed OpenAPI document no longer matches the models
	uv run python scripts/dump_openapi.py frontend/openapi.json
	git diff --exit-code -- frontend/openapi.json

frontend: ## serve the unit browser, with reload (needs `make serve` in another shell)
	cd frontend && npm run dev

frontend-lint: ## prettier and eslint over the frontend
	cd frontend && npm run lint

frontend-test: ## run the frontend unit tests
	cd frontend && npm test

frontend-check: ## type-check the frontend and build it
	cd frontend && npm run check && npm run build

up: ## bring the whole stack up in containers (API on :8000, browser on :5173)
	docker compose up --build

down: ## stop the stack and drop its containers
	docker compose down

logs: ## follow the stack's logs
	docker compose logs -f
