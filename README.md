# sports-analytics

NFL data warehouse. [nflverse](https://github.com/nflverse) data is pulled once via
[`nflreadpy`](https://github.com/nflverse/nflreadpy) into Postgres by a small CLI that runs as a
scheduled container, so it can be analyzed forever without re-downloading. It is the data layer for
**The Hook**, a sports-betting analysis UI (see `docs/`).

```
nflverse parquet (GitHub releases)
        │  nflreadpy.load_*()           polars DataFrame
        ▼
 warehouse/src      ──COPY──▶  Postgres  staging.*  (landing zone: 1:1 mirror of the files, truncatable)
                                        clean.*    (dbt: same tables and columns, types fixed, upserted by key — the durable copy)
                                        reference.* (dbt: curated mappings + identity tables — every source spelling/code → key)
                                        nfl.*      (dbt: persisted dimensions derived from reference — coaches, teams; no views)
        ▲
 nfl-pipeline refresh   (scheduled container: Azure Container Apps Job, Tue+Wed; current season → dbt build → truncate staging)
 nfl-pipeline backfill  (manual: season range → dbt build → truncate staging)     ops.*  run history for both
```

## Quick start

Requirements: Docker Desktop, [`uv`](https://docs.astral.sh/uv/) (for the local CLI and tests).

```bash
cp .env.example .env                                   # passwords, optional webhook
docker compose up -d                                   # postgres (the only long-running service)
docker compose build pipeline                          # the nfl-pipeline image, from warehouse/
docker compose run --rm pipeline backfill --start 2010 # every dataset 2010→now into staging.*, then dbt build
```

Compose commands run from the repo root. Everything else about the warehouse (its CLI, dbt project,
tests) lives in [`warehouse/`](warehouse/README.md) and runs from there with `uv`.

- Warehouse: `postgresql://nfl:nfl@localhost:5432/nfl` (works with `psql`, DBeaver, pandas, DuckDB…)
- Run history: `select * from ops.runs order by run_id desc;`

The backfill loads every dataset from `NFL_START_SEASON` (2010) through the current season into
`staging.*`, then runs `dbt build` to upsert `clean.*` and the `nfl.*` marts. Afterwards
`docker compose run --rm pipeline refresh` keeps the current season fresh; deployed, an Azure
Container Apps Job runs that same command on a schedule (see [Deploying](#deploying-to-azure)).
Narrow either to some datasets with `-d pbp -d schedules`.

## Components

| folder | what | docs |
|---|---|---|
| `warehouse/` | the data warehouse: `nfl-pipeline` loader + CLI, dbt project (`clean`, `reference`, `nfl`), curated inputs, tests, the pipeline image | [`warehouse/README.md`](warehouse/README.md) |
| `deploy/azure/` | runbook and `az` scripts: Postgres Flexible Server, Container Apps environment, scheduled + manual jobs | [`deploy/azure/README.md`](deploy/azure/README.md) |
| `docs/` | The Hook (the betting-analysis UI): brainstorm, theme tokens and rules | [`docs/ui-brainstorm.md`](docs/ui-brainstorm.md) |
| `docker/postgres/init/` | shared Postgres bootstrap: the `nfl` database and its schemas | |
| `docker-compose.yaml` | local stack: Postgres plus the on-demand `pipeline` service; `api/` and `web/` will join it | |

Each component owns its toolchain and its own `CLAUDE.md`; the root holds only what spans them.

## Deploying to Azure

The warehouse runs on the cheapest serverless shape Azure offers: **Azure Database for PostgreSQL
Flexible Server** (burstable B1ms, the one always-on cost, ~$17/month with storage) and an
**Azure Container Apps Job** that starts the pipeline image on a cron trigger (`refresh`, Tue+Wed),
runs for a few minutes and exits, inside the free monthly grant. A
second, manually triggered job runs backfills. The image is pushed to GitHub Container Registry
(`ghcr.io/<owner>/nfl-pipeline`) by hand for now; a CI build is a later step.

The runbook and idempotent `az` scripts are in [`deploy/azure/`](deploy/azure/README.md).

## Roadmap

- **Current betting lines.** Historical closing lines are already in `clean.schedules`. For live/opening
  lines the plan is an append-only `staging.odds_snapshots` table (upserted into clean like everything else) fed by
  [The Odds API](https://the-odds-api.com/) (free tier: 500 credits/month) on a Thu/Sat/Sun
  cadence, as its own CLI command and scheduled job. `ODDS_API_KEY` is reserved in `.env.example`.
- Extend history: lower `NFL_START_SEASON` in `.env` or run `backfill --start 1999`. pbp/stats go
  back to 1999.
