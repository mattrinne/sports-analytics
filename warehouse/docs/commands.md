# Commands

From `warehouse/` with `uv`; the same CLI runs in the image from the repo root as
`docker compose run --rm pipeline <command>`.

```bash
uv sync                                  # creates .venv with the package + dev tools (dbt included)
uv run nfl-pipeline list
uv run nfl-pipeline load pbp --season 2024
uv run nfl-pipeline refresh -d schedules -d teams
uv run nfl-pipeline backfill --start 2010 -d team_stats_week -d player_stats_week
uv run nfl-pipeline transform            # dbt build: upsert clean.* and nfl.* marts; extra args go to dbt build
uv run nfl-pipeline backfill --full-refresh -d schedules   # drop + recreate a model (load → rebuild → truncate)
uv run nfl-pipeline staging truncate -d pbp -y   # by hand; refresh/backfill already do it (-y skips the prompt)
uv run nfl-pipeline current-season       # the season nflreadpy considers current (what refresh loads)
uv run nfl-pipeline -v refresh ...       # debug logging
cd dbt && uv run dbt build --profiles-dir .        # same as transform
uv run dbt docs generate --project-dir dbt --profiles-dir dbt && uv run dbt docs serve --project-dir dbt
uv run pytest && uv run ruff check src tests scripts
```

Shared `refresh`/`backfill` options: `loading.md`, Options.

## Connection and environment

The CLI reads `NFL_DATABASE_URL` (default: the compose Postgres on localhost, `nfl`/`nfl`) and the
`NFLREADPY_CACHE*` variables; dbt gets the same connection as `NFL_DB_*` parts, derived from the URL
unless you set them yourself (`dbt/profiles.yml`); a `?sslmode=` query parameter on the URL is
carried into `NFL_DB_SSLMODE`. A bare `uv run` sees exported env vars, not `.env` (compose reads
that).

## Repo-root equivalents

```bash
docker compose build pipeline                                # rebuild after changing src/, dbt/ or data/
docker compose run --rm pipeline refresh -d teams            # or backfill / transform / staging truncate
docker compose exec -T postgres psql -U nfl -d nfl -c "select * from ops.runs order by run_id desc limit 5"
```

## Verify a change end to end

`dbt build` green twice in a row (the second run should `MERGE 0` on untouched models), `pytest`,
`ruff`, a `docker compose run --rm pipeline refresh -d <small dataset>` that exits 0 with a
`success` row in `ops.runs`, and a look at the affected table in psql.
