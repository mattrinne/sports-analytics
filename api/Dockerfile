# API image: read-only FastAPI over nfl.* and ops.*. Long-running: `docker compose up -d api`
# locally; serves on :8000.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim
RUN useradd --create-home --uid 1000 nfl
WORKDIR /app
COPY --from=build --chown=nfl:nfl /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1
USER nfl
EXPOSE 8000
CMD ["uvicorn", "nfl_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
