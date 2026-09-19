# Pipeline image: `nfl-pipeline` CLI + dbt project + curated inputs. Runs one command and exits;
# used locally via `docker compose run --rm pipeline ...` and in Azure as a Container Apps Job.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim
RUN useradd --create-home --uid 1000 nfl && mkdir -p /cache && chown nfl:nfl /cache
WORKDIR /app
COPY --from=build --chown=nfl:nfl /app/.venv /app/.venv
COPY --chown=nfl:nfl dbt ./dbt
COPY --chown=nfl:nfl data ./data
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    NFL_DBT_DIR=/app/dbt NFL_DATA_DIR=/app/data \
    DBT_TARGET_PATH=/tmp/dbt/target DBT_LOG_PATH=/tmp/dbt/logs DBT_SEND_ANONYMOUS_USAGE_STATS=false \
    NFLREADPY_CACHE=off
USER nfl
ENTRYPOINT ["nfl-pipeline"]
CMD ["--help"]
