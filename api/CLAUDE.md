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
- Auth: `NFL_API_KEY` set → every route except `/health` requires `X-API-Key` (`auth.py`); unset or
  empty → open. `/health` is the only unauthenticated route, by construction (`main.py` registers it
  on the app, everything else on the `protected` router).

## Module map (`src/nfl_api/`)

| file | role |
|---|---|
| `config.py` | frozen `Settings` from env (`NFL_DATABASE_URL`, `NFL_API_KEY`, `NFL_API_CORS_ORIGINS`) |
| `schemas.py` | pydantic response models, one per mart, plus `GameQuery` (the `/games` query params) |
| `games_query.py` | pure SQL composition for `/games`: filter tables, sort, paging, count |
| `repository.py` | `Repository` protocol + `PostgresRepository`, the only code that touches psycopg |
| `db.py` | `make_pool` (psycopg_pool, `dict_row`) and the `get_repository` dependency |
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
- `/games` runs the page and the `count(*)` in one transaction on one connection so `total` matches
  the page. `/ops/runs` fetches steps with `run_id = ANY(...)`, never per run.
- Errors: `OperationalError`/`PoolTimeout` → 503, `QueryCanceled` (role timeout) → 504; `/health`
  returns 503 with `status: degraded` instead of raising. The pool opens with `wait=False`, so the
  process starts even when Postgres is down.
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
