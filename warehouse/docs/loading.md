# Loading: `refresh`, `backfill` and everything around a run

`src/nfl_pipeline/` is the loader. `refresh` (current season) and `backfill` (season range) build a
plan of (dataset, season) steps from the registry, run it, hand the result to dbt and record the
run. Paths are relative to `warehouse/`; the same commands run in the image from the repo root
(`docker compose run --rm pipeline <command>`).

## Path through the code

1. `nfl_pipeline.datasets.REGISTRY` lists datasets (nflreadpy loader or dotted path, min season,
   partitioned or full-replace). Adding a dataset = one `Dataset(...)` entry (any
   `nflreadpy.load_*` function, or a dotted path to a loader in this package, works); `refresh`,
   `backfill` and `list` pick it up automatically. Keep the registry source-agnostic: nothing in it
   may assume nflverse or the NFL.
2. `ingest.load_dataset(name, season)`: fetch → Polars → lowercase columns + `_loaded_at` →
   `ensure_table` (CREATE / ADD COLUMN / widen type) → `DELETE season` + `COPY` in one transaction,
   under a per-table `pg_advisory_xact_lock` (concurrent loads of one table deadlocked without it).
3. `runner.refresh_plan/backfill_plan` build the `Step(dataset, season)` list and
   `pipeline.run_pipeline` runs it: `runner.run_plan` (one worker per dataset, seasons serial
   inside it, `--workers 4`, retries on `OSError`/`OperationalError` with 30 s → 60 s backoff,
   `SeasonUnavailable` → `skipped`) → `dbt build` only if no step failed (skips are fine) →
   truncate the loaded staging tables, only after a green dbt (default; `--keep-staging` opts out)
   → `ops.runs` row finished → webhook (`NFL_ALERT_WEBHOOK_URL`) on failure. Exit 0 when everything
   loaded or skipped and dbt passed, 1 otherwise, 2 for a usage error.
4. `coaching_staff` is not nflverse: Wikipedia season articles, batched MediaWiki API, 1 req/s, in
   memory only (the current season falls back to each team's live `Template:<Team> staff`),
   corrections via `data/coaching_staff_overrides.csv`, which replaces parsed rows for the same
   season/team/role. Parser in `src/nfl_pipeline/sources/wikipedia_staff.py`; artifacts are fixed
   there, never with a mapping row (`identity.md`).

Side jobs are their own CLI command (`staging truncate`) — never add cross-cutting steps to
`refresh`. Scheduling is not part of the repo; `refresh` is run by hand from compose.

## Behaviour

- **Schema-on-write.** Tables are created from the Polars dtypes of the first file loaded. Later
  files that add columns get `ALTER TABLE ADD COLUMN`; a column whose type changes is widened
  (int → double → text). No hand-written DDL for 370-column pbp.
- **Idempotent partitions.** Seasonal datasets are `DELETE WHERE season = X` + `COPY` in one
  transaction. Re-running a season is safe. Non-seasonal datasets are `TRUNCATE` + `COPY`.
- **Fast.** Polars → CSV → `COPY FROM STDIN`. A full pbp season loads in ~3 s.
- **Cached downloads.** nflreadpy caches parquet files on a Docker volume (`NFLREADPY_CACHE_DIR`,
  24 h TTL) when run through compose; inside the image the cache is off and dbt writes its
  `target/` and logs to `/tmp`, so nothing downloaded at runtime is written to disk.
- **Parallel across datasets, serial within one.** Up to `--workers` (4) datasets load at once; a
  dataset's seasons run one after another so the per-table lock never contends and memory stays
  bounded (one pbp season is ~0.5 GB at peak; 4 workers fit a refresh in 2 GiB, use `--workers 2`
  for a backfill in a 2 GiB container).
- **A season nflverse has not published is a skip, not a failure.** `participation` (NGS
  charting) lags a season, so the current season is skipped and dbt still runs.
  `SeasonUnavailable` is detected from the text of nflreadpy's `ValueError` ("Season must be
  between"); if nflreadpy rewords it, skips become failures — `tests/test_ingest.py` pins the
  wording. Early-September runs before nflverse publishes week 1 fail on pbp after retries and
  send one alert; expected until the files appear.
- **Staging is emptied after a green dbt build** (`--keep-staging` opts out; `staging truncate -y`
  by hand). Tables stay, only the rows go (`layers.md`).

## Options

`refresh` and `backfill` share: `-d/--dataset` (repeatable subset), `--workers` (4, datasets in
parallel), `--retries` (2) and `--retry-delay` (30 s, doubling) for network errors,
`--skip-transform` (no dbt afterwards), `--full-refresh` (dbt drop + recreate), `--keep-staging`
(do not truncate staging after dbt) and `--notify-success` (webhook on success too, not only
failure). `backfill` takes `--start` (default `NFL_START_SEASON`).

## Run history and alerts

Every `refresh`/`backfill` writes one row to `ops.runs` (command, status `running|success|failed`,
season, args, start/finish, error) and one per step to `ops.run_steps` (dataset or `dbt_build` /
`truncate_staging`, status `loaded|skipped|failed`, attempts, rows, seconds, error). The tables are
created on first use; the api's `/health` and `/ops/runs` read them (`../../api/README.md`).

```sql
select run_id, command, status, started_at, finished_at, error from ops.runs order by run_id desc limit 10;
select step, season, status, attempts, rows, seconds from ops.run_steps where run_id = 42 order by step_id;
```

Set `NFL_ALERT_WEBHOOK_URL` (Slack incoming webhook, Discord webhook, an <https://ntfy.sh> topic) to
get a short message when a run fails; `--notify-success` sends one on success too.
