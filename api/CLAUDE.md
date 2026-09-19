# api — working notes for Claude

Read-only FastAPI over the warehouse marts. This folder is its own uv project; run `uv ...` from
here and `docker compose ...` from the repo root. The root `CLAUDE.md` has the rules that span
components; `README.md` here has the routes, filters and environment variables; `docs/commands.md`
has every command. Nothing below repeats them.

## What it is

- Reads `nfl.*` (marts) and `ops.*` (run history) and nothing else, always schema-qualified. In
  compose it connects as the read-only role `nfl_reader`; the role's privileges are defined in
  `docker/postgres/init/02-reader-role.sh` (the script is the documentation). Any URL works
  locally; the laptop default is `nfl:nfl@localhost`.
- Auth is enforced by construction: `/health` is registered on the app, every data route on the
  `protected` router that depends on `require_api_key` (`auth.py`). FastAPI's `/docs`, `/redoc`
  and `/openapi.json` expose the schema but no data and are deliberately left open so Swagger's
  Authorize button works. The user-visible behaviour is in `README.md`, Environment.

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
  lifespan. Before reporting a change done, run the unit tests, lint and the integration test with
  the reader URL (`docs/commands.md`) and rebuild the compose image.

Commit only when asked. Paths in this file are relative to `api/`.
