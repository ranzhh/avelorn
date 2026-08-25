FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Outside /app, so the bind mount that carries the source in does not shadow it.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

# The lockfile alone settles the dependencies, so editing a source file does
# not reinstall them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --extra api --frozen --no-install-project

COPY src ./src
COPY data ./data
RUN uv sync --extra api --frozen

EXPOSE 8000
CMD ["uv", "run", "fastapi", "dev", "src/avelorn/api/app.py", "--host", "0.0.0.0"]
