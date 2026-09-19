# api — working notes for Claude

Read-only FastAPI over the warehouse marts. This folder is its own uv project; run `uv ...` from
here and `docker compose ...` from the repo root. The root `CLAUDE.md` has the purpose and repo map.

## What it is

- Reads `nfl.*` (marts) and `ops.*` (run history) and nothing else, always schema-qualified. It
  connects as the read-only role `nfl_reader` in compose (`docker/postgres/init/02-reader-role.sh`:
  SELECT on `nfl` and `ops`, `default_transaction_read_only`, 15 s `statement_timeout`); any URL
  works locally, the laptop default is `nfl:nfl@localhost`.
- Routes: `/teams`, `/coaches` (+ `/{id}/tenures` from `nfl.coaching_tenures_detail`), `/referees`,
  `/stadiums` (complete lists and `/{id}`), `/games` (filtered, sorted, paginated `Page[Game]`) and
  `/games/{game_id}`, `/ops/runs?limit=`, `/health`. OpenAPI at `/docs`.
- Auth: `NFL_API_KEY` set → every data route requires `X-API-Key` (`auth.py`); unset or empty →
  open. Unauthenticated by construction: `/health` (registered on the app, everything else on the
  `protected` router) and FastAPI's `/docs`, `/redoc`, `/openapi.json`, which expose the schema but
  no data and are deliberately left open so Swagger's Authorize button works.

## Module map (`src/nfl_api/`)

| file | role |
|---|---|
| `config.py` | frozen `Settings` from env (`NFL_DATABASE_URL`, `NFL_API_KEY`, `NFL_API_CORS_ORIGINS`, `NFL_API_POOL_MIN/MAX`) |
| `schemas.py` | pydantic response models, one per mart, plus `GameQuery` (the `/games` query params) |
| `games_query.py` | pure SQL composition for `/games`: filter tables, sort, paging, count |
| `repository.py` | `Repository` protocol + `PostgresRepository`, the only code that touches psycopg |
| `db.py` | `make_pool` (psycopg_pool, `dict_row`, REPEATABLE READ) and the `Repo` dependency alias |
| `auth.py` | `require_api_key` |
| `main.py` | `create_app(settings)`: lifespan opens the pool, CORS, routers, `/health`, 503/504 handlers |
| `routers/` | `dimensions.py`, `games.py`, `ops.py` |

## Rules

- **Response models mirror the dbt contracts** in `warehouse/dbt/models/marts/*.yml` column for
  column; `tests/test_schemas.py::test_model_matches_contract` fails when they drift. Change the yml
  and `schemas.py` together. `Game` carries every `nfl.schedules` column (odds included) plus
  `home_team_abbr`/`away_team_abbr` joined from `nfl.teams`; nothing else is embedded.
- **SQL only through `psycopg.sql`**: column names via `sql.Identifier` from the literal tables in
  `games_query.py` (`_EQ`, `_RANGE`, `_EITHER`), operators from literals there, values only as
  placeholders. No f-strings into SQL, no ORM.
- **Adding a `/games` filter** = one field on `GameQuery` + one entry in the matching table + the
  parametrized tests pick it up; `test_every_query_field_is_mapped` fails until both exist. Sort
  columns are the `GameSort` literal. `total` is the points column, so total-line filters are named
  `total_line_min/max`.
- **One checkout, one snapshot per request.** Pooled connections run REPEATABLE READ
  (`db._configure`), so the statements of one repository method share a snapshot: `/games` page and
  `count(*)` agree even if a dbt merge commits in between, `/ops/runs` runs and steps match. A
  method does all its statements inside a single `with self._conn()`; never check out twice.
  `/ops/runs` fetches steps with `run_id = ANY(...)`, never per run. `/health` is one statement.
- Errors: `OperationalError`/`PoolTimeout` → 503, `QueryCanceled` (role timeout) → 504; `/health`
  returns 503 with `status: degraded, database: unavailable` (the real error goes to the log, not
  the response). The pool opens with `wait=False`, so the process starts even when Postgres is down.
- Sync endpoints run on anyio worker threads; the lifespan caps them at `pool_max` so a burst waits
  for a thread instead of failing pool checkout. Size both with `NFL_API_POOL_MAX`.
- **Tests never open a connection** except `tests/test_integration.py`, which is skipped unless
  `NFL_TEST_DATABASE_URL` is set. Unit tests inject `FakeRepository` (`tests/conftest.py`) through
  `app.dependency_overrides[get_repository]`; `TestClient(app)` without `with` never runs the
  lifespan. Run the integration test with the reader URL so it also proves the grants.

## Commands

```bash
uv sync && uv run pytest && uv run ruff check src tests
NFL_TEST_DATABASE_URL=postgresql://nfl_reader:nfl_reader@localhost:5432/nfl uv run pytest tests/test_integration.py
uv run uvicorn nfl_api.main:app --reload                # laptop, against compose Postgres on :5432
cd .. && docker compose build api && docker compose up -d api && curl -s localhost:8000/health
docker compose exec -T postgres bash /docker-entrypoint-initdb.d/02-reader-role.sh   # role on an existing volume
```

Commit only when asked. Paths in this file are relative to `api/`.
