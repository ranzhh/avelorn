.PHONY: install test lint demo api

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

api: ## serve the unit database over HTTP, with reload (docs at /docs)
	uv run fastapi dev src/avelorn/api/app.py
