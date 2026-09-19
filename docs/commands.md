# Commands (repo root)

Compose runs from the repo root; each component's own commands run from its folder with `uv`
(`warehouse/docs/commands.md`, `api/docs/commands.md`).

```bash
cp .env.example .env                                   # every variable is documented in that file
docker compose up -d                                   # postgres + api (http://localhost:8000/docs)
docker compose build pipeline                          # the nfl-pipeline image, from ./warehouse
docker compose run --rm pipeline backfill --start 2010 # first load (hours), then dbt build
docker compose run --rm pipeline refresh               # afterwards: current season; -d teams narrows it
docker compose build api && docker compose up -d api   # rebuild the api after changing ./api
docker compose exec -T postgres psql -U nfl -d nfl -c "select * from ops.runs order by run_id desc limit 5"
```

Postgres: `postgresql://nfl:nfl@localhost:5432/nfl` (works with `psql`, DBeaver, pandas, DuckDB…).
API: <http://localhost:8000/docs>. `.env` is read by compose only; a bare `uv run ...` sees exported
env vars, and its defaults point at the compose Postgres.
