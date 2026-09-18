# sports-analytics — working notes for Claude

NFL warehouse: nflverse data (via `nflreadpy`) + Wikipedia coaching staffs → Postgres, loaded by
the `nfl-pipeline` CLI running as a scheduled container, transformed by dbt. One user. Dev
environment is docker compose on a laptop; the deployed shape is Azure (Postgres Flexible Server,
the pipeline as a Container Apps Job, later the UI as a Container App), kept as cheap as possible
because the user pays for it. Data is pulled once and analyzed forever; there is no live data.
`README.md` is the user-facing doc; this file is the contributor's mental model and the rules
that are easy to break.

## Purpose and direction

The warehouse is the foundation, not the product. The end goal is a **web UI for analyzing and
visualizing NFL data for sports betting**: curated datasets (team/coach/referee/situational
splits against the closing line), and eventually predictive models (spread, total, win
probability) trained on the history held here. Everything is historical — there is no live odds
feed — so the value is in backtesting, trend discovery and model training, not in-game pricing.

What this means for work in this repo:

- **Betting-relevant columns are first-class.** `schedules` carries nflverse closing lines
  (`spread_line` positive = home favoured, `total_line`, moneylines, spread/over/under odds).
  Treat them, `result` and `total` as the labels every analysis and model will key on; never
  drop or "clean away" odds columns. Line-movement / opening lines are not in nflverse and are a
  known gap (deferred; would need a separate source and its own identity work).
- **Datasets for the UI and models are persisted marts in `nfl`**, built the same way as the
  dimensions (contract, integer PK, `created_at`/`updated_at`, incremental merge). A feature
  table for a model is a mart, not a notebook artifact. Views only re-present marts.
- **Grain and keys must be UI-friendly**: integer keys, one row per (game, team) or (game,
  team, player) etc., stable across seasons, joinable to `nfl.teams`/`coaches`/`referees`/
  `stadiums` without going back through `reference.*_identities`. The UI should read `nfl.*`
  only.
- **Models are a separate layer** (Python, not dbt). Training reads `nfl.*`; predictions,
  backtest results and model metadata land in their own schema (name TBD, e.g. `models`) with
  the same contract/PK discipline, so the UI can show a model's history alongside the data.
- **Web UI ("The Hook") is not yet started.** Theme is decided: "gold on graphite" terminal, tokens and
  rules in `docs/ui/` (all monospace, square, dark; green/red/gold = cover/loss/push and nothing
  else; team colours only as swatches). Stack and content priorities are still open, see
  `docs/ui-brainstorm.md`. It runs as a scale-to-zero Container App next to the pipeline job,
  reads `nfl.*` (and `ops.*` for data health) directly or through a thin read-only API, and must
  also run locally against compose.

## Repo map

One folder per component; the root holds only what spans them. Each component has its own
`CLAUDE.md` with its rules — read it before working there.

| path | what |
|---|---|
| `warehouse/` | the data warehouse: `src/nfl_pipeline` (loader, runner, CLI), `dbt/` (clean, reference, nfl), `data/` (curated inputs), `tests/`, `scripts/`, `Dockerfile`, `pyproject.toml`. Own uv project: `cd warehouse` for `uv run ...`. Rules: `warehouse/CLAUDE.md`. |
| `docker-compose.yaml` | local stack, run from the root: `postgres` plus the on-demand `pipeline` service (`build: ./warehouse`). `api`/`web` services join here later. |
| `.env` / `.env.example` | shared by compose and the CLI (`NFL_DATABASE_URL`, `NFL_START_SEASON`, `NFL_ALERT_WEBHOOK_URL`). |
| `docker/postgres/init/` | Postgres bootstrap on first boot: `nfl` database, schemas, `search_path`. |
| `deploy/azure/` | infra runbook + idempotent `az` scripts (Flexible Server, Container Apps env, jobs). Will grow api/web sections. |
| `docs/` | The Hook: `ui-brainstorm.md`, `ui/theme.md`, `ui/tokens.css`. |
| future `api/`, `web/` | The Hook's read-only API and UI; each its own toolchain and `CLAUDE.md`. |

**Hard rule from the user:** nothing downloaded at runtime is written to disk (no vendored
dictionaries, no wikitext cache, dbt writes `target/`/logs to `/tmp` in containers, nflreadpy's
cache is off in the image and on a named volume locally). Curated, human-owned inputs live under
`warehouse/data/` (`metadata/*.yaml`, `seeds/*.csv`, `coaching_staff_overrides.csv`) and are copied
into the image, as is `warehouse/dbt/`: rebuild the image after changing either.

## Commands (repo root)

```bash
docker compose up -d                               # postgres only
docker compose build pipeline                      # image = what Azure runs, built from ./warehouse
docker compose run --rm pipeline refresh -d teams  # or backfill / transform / metadata build / staging truncate
docker compose exec -T postgres psql -U nfl -d nfl -c "select * from ops.runs order by run_id desc limit 5"
cd warehouse && uv sync && uv run pytest && uv run ruff check src tests scripts
```

Commit only when asked.

## How the user likes to work

Short what/why/cost before an infrastructure or design choice, then a clear recommendation; they
decide quickly and sometimes reverse earlier designs (aggressive pruning → faithful copy; views →
persisted marts). When asked for an opinion, give an honest one and stop; when told to build,
build the whole thing, verify it, and report plainly including what was changed from the literal
spec and why.
