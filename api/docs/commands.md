# Commands

From `api/` with `uv`; in compose the `api` service runs the same app from the image.

```bash
uv sync
uv run uvicorn nfl_api.main:app --reload              # laptop, against compose Postgres on :5432 → http://localhost:8000/docs
uv run pytest && uv run ruff check src tests          # unit tests use an in-memory repository, no database
NFL_TEST_DATABASE_URL=postgresql://nfl_reader:nfl_reader@localhost:5432/nfl uv run pytest tests/test_integration.py
```

The integration test runs the real app against the URL given and is skipped otherwise. Run it with
the `nfl_reader` URL so it also proves the role's grants.

## Repo-root equivalents

```bash
docker compose up -d api                              # part of the default `up`
docker compose build api && docker compose up -d api  # rebuild after changing src/
curl -s localhost:8000/health
```

## Reader role on an existing volume

`docker/postgres/init/02-reader-role.sh` runs on first boot of an empty volume. On a volume created
before it existed, apply it once (idempotent):

```bash
docker compose exec -T postgres bash /docker-entrypoint-initdb.d/02-reader-role.sh
```
