.PHONY: install test lint demo

install: ## install dependencies and git hooks
	uv sync
	uv run pre-commit install

test: ## run the test suite
	uv run pytest

lint: ## run all pre-commit hooks (ruff, ty, hygiene) on the full tree
	uv run pre-commit run --all-files

demo: ## end-to-end shooting demo from the data files
	uv run python scripts/shooting_demo.py
