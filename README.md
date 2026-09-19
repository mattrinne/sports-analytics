# sports-analytics

NFL data warehouse plus a read-only API over it. [nflverse](https://github.com/nflverse) data is
pulled once via [`nflreadpy`](https://github.com/nflverse/nflreadpy) into Postgres by the
`nfl-pipeline` CLI and transformed by dbt; the `api` serves the resulting marts as JSON. It is the
data layer for **The Hook**, a sports-betting analysis UI (see `docs/`). Everything runs locally in
docker compose.

```
nflverse parquet ──nfl-pipeline──▶ Postgres: staging.* → clean.* → reference.* → nfl.*   (+ ops.* run history)
                                                                                  │
                                                                     api (FastAPI, :8000) ──▶ JSON
```

What each schema holds and how loads work: [`warehouse/README.md`](warehouse/README.md). The
routes: [`api/README.md`](api/README.md).

## Quick start

Requirements: Docker Desktop, [`uv`](https://docs.astral.sh/uv/) (for the local CLIs and tests).
The commands, from `.env` to the first load: [`docs/commands.md`](docs/commands.md). What
`backfill` and `refresh` do: [`warehouse/docs/loading.md`](warehouse/docs/loading.md).

## Components

| folder | what | docs |
|---|---|---|
| `warehouse/` | the data warehouse: `nfl-pipeline` loader + CLI, dbt project (`clean`, `reference`, `nfl`), curated inputs, tests, the pipeline image | [`warehouse/README.md`](warehouse/README.md) |
| `api/` | read-only FastAPI over the `nfl.*` marts and `ops.*` run history, the `api` image | [`api/README.md`](api/README.md) |
| `docs/` | repo-root commands; The Hook (the betting-analysis UI): style directions, layout principles, theme tokens and rules; thoughts on a cloud deployment | [`docs/commands.md`](docs/commands.md), [`docs/ui/theme.md`](docs/ui/theme.md), [`docs/cloud-deployment.md`](docs/cloud-deployment.md) |
| `docker/postgres/init/` | shared Postgres bootstrap: the `nfl` database, its schemas and the read-only `nfl_reader` role | |
| `docker-compose.yaml` | local stack: Postgres, the `api` service and the on-demand `pipeline` service | |

Each component owns its toolchain and its own `CLAUDE.md`; the root holds only what spans them.

