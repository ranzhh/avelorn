.PHONY: install test lint demo

# Which end-to-end demo `make demo` runs — any scripts/<DEMO>_demo.py, e.g.
# shooting, melee, charge, turn, bow_of_avelorn, lion_cloak, receiving_a_charge.
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
