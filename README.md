# sports-analytics

Local NFL data warehouse. [nflverse](https://github.com/nflverse) data is pulled once via
[`nflreadpy`](https://github.com/nflverse/nflreadpy) into Postgres, orchestrated by Airflow 3, so it
can be analyzed forever without re-downloading.

```
nflverse parquet (GitHub releases)
        │  nflreadpy.load_*()           polars DataFrame
        ▼
 src/nfl_pipeline  ──COPY──▶  Postgres  staging.*  (landing zone: 1:1 mirror of the files, truncatable)
                                        clean.*    (dbt: same tables and columns, types fixed, upserted by key — the durable copy)
                                        nfl.*      (dbt: analysis views over clean — games, plays, coaches, box scores)
        ▲
 Airflow 3 (LocalExecutor)  dags/nfl_backfill  (manual, season range)
                            dags/nfl_weekly_refresh  (Tue+Wed 08:00 America/Chicago, current season)
```

## Quick start

Requirements: Docker Desktop, [`uv`](https://docs.astral.sh/uv/) (for the local CLI and tests).

```bash
cp .env.example .env               # edit passwords / AIRFLOW_JWT_SECRET if you like
docker compose up airflow-init     # migrates the Airflow DB, creates the admin user (once)
docker compose up -d --build       # postgres + api-server, scheduler, dag-processor, triggerer
```

- Airflow UI: <http://localhost:8080> (default `airflow` / `airflow`, from `.env`)
- Warehouse: `postgresql://nfl:nfl@localhost:5432/nfl` (works with `psql`, DBeaver, pandas, DuckDB…)

Then in the UI unpause **nfl_backfill** and trigger it. Defaults load every dataset from
`NFL_START_SEASON` (2010) through the current season into `staging.*`, then run `dbt build` to
upsert `clean.*` and rebuild the `nfl.*` views. Afterwards unpause
**nfl_weekly_refresh** and it keeps the current season fresh.

From the CLI instead of the UI:

```bash
docker compose exec airflow-scheduler airflow dags unpause nfl_backfill
docker compose exec airflow-scheduler airflow dags trigger nfl_backfill \
  --conf '{"start_season": 2023, "datasets": ["pbp", "schedules"]}'
```

## Datasets

| dataset | table | granularity | replace mode | notes |
|---|---|---|---|---|
| schedules | `staging.schedules` | game | full | results, head coaches, referee, stadium, closing spread/total/moneylines. All seasons in one file. |
| teams | `staging.teams` | team | full | abbreviations, colors, logos |
| players | `staging.players` | player | full | id crosswalk (gsis, espn, pfr, …) |
| rosters | `staging.rosters` | season × player | by season | |
| rosters_weekly | `staging.rosters_weekly` | week × player | by season (2002+) | who was on the roster each game week |
| depth_charts | `staging.depth_charts` | week × slot | by season (2001+) | nflverse changed the format in 2025: older seasons are weekly rows with `season/week/club_code`; 2025+ are daily snapshots with `dt/team` and no week. Both live in the same table with NULLs where a column doesn't apply. |
| team_stats_week | `staging.team_stats_week` | team-game | by season | post-game box score (nflfastR aggregation) |
| player_stats_week | `staging.player_stats_week` | player-game | by season | post-game box score |
| pbp | `staging.pbp` | play | by season | nflfastR play-by-play incl. EPA / WP, ~370 columns, ~50k rows per season |
| participation | `staging.participation` | play | by season (2016+) | NGS charting: `offense_formation`, `offense_personnel`, `defense_personnel`, `defenders_in_box`, `number_of_pass_rushers`, `defense_man_zone_type`, `defense_coverage_type`, players on the field. Published after the season ends, so the current season is skipped until nflverse releases it. |
| coaching_staff | `staging.coaching_staff` | coach-role × team-season | by season (2010+) | **Not nflverse.** Head coach, OC, DC, ST coordinator with mid-season change dates, parsed from the Staff section of Wikipedia season articles (one batched API request per season, held in memory only; the current season falls back to each team's live `Template:<Team> staff`). Interim holders are separate rows; `flags` marks rows the parser wasn't sure about. Corrections go in `data/coaching_staff_overrides.csv`, which replaces parsed rows for the same season/team/role. |
| officials | `staging.officials` | game × official | by season (2015+) | |

Every staging table also has `_loaded_at timestamptz`; clean keeps it and uses it to find new rows.

## Clean layer (dbt)

`staging.*` is where loads land; **`clean.*`** is what you keep and analyze. Clean is built by
[dbt](https://docs.getdbt.com/) from the project in `dbt/` at the end of every load DAG run (task
`dbt_build`) and is a **column-for-column copy of staging with the types fixed**: same twelve
tables, same names, nothing dropped, nothing derived.

- **Types fixed.** nflverse's parquet files lose types on the way in: 0/1 doubles become
  `boolean` (82 pbp flags such as `shotgun`, `touchdown`, `pass`), whole-number doubles and
  bigints become `smallint`/`integer`, ISO text becomes `date`/`time`/`timestamptz`
  (`gameday`, `gametime`, `time_of_day`, `birth_date`), and nothing else changes. The casts are
  generated from the live staging schema by `scripts/gen_clean_models.py`, so a new column shows
  up typed on the next generation run.
- **Upserted, so staging is disposable.** Each clean table is a dbt incremental model with the
  `merge` strategy on a primary key. A run takes only source rows whose `_loaded_at` is newer
  than anything already in clean (macro `only_new`), and merges them by key. Nothing is ever
  dropped on a normal run, which means you can empty staging whenever the volume gets big:
  trigger **nfl_staging_truncate** (or `uv run nfl-pipeline staging truncate`). The next load
  lands only the seasons it fetches and dbt merges them into the full history in clean.
- **Keys.** Natural keys where the source has one: `schedules(game_id)`, `pbp(game_id, play_id)`,
  `participation(nflverse_game_id, play_id)`, `team_stats_week(season, week, team)`,
  `officials(game_id, official_id)`, `teams(team_abbr)`, `players(gsis_id)`. Where it does not
  (`player_stats_week` has team placeholder rows without a player id; a player can appear twice
  in one week of `rosters_weekly` with two statuses; `depth_charts` has two formats and exact
  duplicates; `coaching_staff` stints can lack a start date) the table gets an `_row_id` md5 of
  its identifying columns and exact duplicate rows collapse to one. Foreign keys are not
  declared: a copy of nflverse is not referentially complete (roster-only players are missing
  from `players`, for instance), so joins across clean are by convention, as in the source.
- **Documented.** Every column's description from the metadata dictionary is written as a
  Postgres `COMMENT` (`\d+ clean.pbp` in psql shows them).

How it is maintained (`dbt/`):

- `models/clean/<table>.sql` is the typed SELECT, generated by `scripts/gen_clean_models.py`
  (type rules, primary keys and `_row_id` columns live at the top of that script);
  `models/clean/<table>.yml` declares every column with its type (dbt *contract*), the
  description and the primary-key constraint, generated by `scripts/gen_dbt_columns.py`.
  Regenerate both after nflverse adds or retypes a column: run the loads, then

  ```bash
  uv run python scripts/gen_clean_models.py <table>     # rewrite the SELECT from staging
  uv run nfl-pipeline transform --full-refresh --select <table>   # recreate with the new shape
  uv run python scripts/gen_dbt_columns.py <table>      # refresh the yml (keeps hand edits)
  ```

- **Incremental by default, full refresh on demand.** A normal `dbt build` upserts; it cannot see
  rows nflverse *deleted* from a re-published season, and it fails (by design, `on_schema_change:
  fail`) when a model's columns changed. Both cases want `--full-refresh`: tick **full_refresh**
  when triggering either DAG, or run `uv run nfl-pipeline transform --full-refresh`. A full refresh
  rebuilds from whatever is in staging, so run it while staging still holds the seasons you care
  about (a backfill first if you truncated).
- `nfl.*` views (`games`, `plays`, `coach_games`, `coach_stints`, `game_coordinators`,
  `player_game_stats`, `team_game_stats`) are dbt models in `dbt/models/marts/` and read only
  from `clean`.

```bash
uv run nfl-pipeline transform            # = dbt build (incremental upsert), against NFL_DB_* (localhost)
uv run nfl-pipeline transform --full-refresh                 # drop + recreate every clean table from staging
uv run dbt docs generate --project-dir dbt --profiles-dir dbt && uv run dbt docs serve --project-dir dbt
```

## Metadata: data dictionary and column labels

The `metadata` schema documents every `clean.*` column (same names as staging) and tags it so you
can find stats by kind instead of by name.

| object | contents |
|---|---|
| `metadata.tables` | one row per clean table: description, grain, source URL, partition key, row count, last load time |
| `metadata.columns` | one row per clean column: type, description (781 from nflverse dictionaries, 125 curated in `metadata/overrides.yaml`), four label axes, free-form tags, null fraction |
| `metadata.labels` | the controlled vocabulary for each axis |
| `metadata.column_labels` | unpivoted `(table, column, axis, label)` view |

Label axes (one value each; see `metadata/labels.yaml` for definitions):

- **role** – identifier, dimension, time, situation, flag, measure, derived, model, betting, text, media, system
- **side** – offense, defense, special_teams, neutral
- **entity** – player, team, game, play, drive, coach, official, venue
- **category** – passing, rushing, receiving, scoring, turnovers, first_downs, penalties, tackling, pass_rush, coverage, kicking, punting, kickoffs, returns, personnel, game_state, drive, series, expected_points, win_probability, passing_model, schedule, betting, weather, venue, officiating, coaching, roster, bio, identity, branding, fantasy, system
- **tags** – multi-valued extras such as `perspective:home`, `vegas_adjusted`, `bucket`, `lateral`, `legacy_depth_chart`

```sql
-- every defensive player measure in the box score
select column_name, description
from metadata.columns
where table_name = 'player_stats_week' and side = 'defense' and role = 'measure';

-- model outputs available in pbp
select column_name, category, tags from metadata.columns
where table_name = 'pbp' and role = 'model';
```

How it is maintained: the curated inputs live in `data/metadata/` and the tables are rebuilt from the
live schema. nflverse's own data dictionaries are downloaded from GitHub at build time, parsed in
memory and not stored.

- `data/metadata/tables.yaml` – table descriptions, per-table default entity, which nflverse dictionaries apply.
- `data/metadata/labels.yaml` – vocabulary. Builds fail on labels not listed here.
- `data/metadata/rules.yaml` – ordered regex rules; later rules override earlier ones for the axes they set, tags accumulate.
- `data/metadata/overrides.yaml` – per-column descriptions and label corrections; these win over everything.

```bash
uv run nfl-pipeline metadata lint    # unlabeled / undocumented columns, bad labels; exit 1 on errors
uv run nfl-pipeline metadata build   # rebuild metadata.* from clean.* + the yaml files
```

The rebuild runs as its own manually triggered DAG, **nfl_metadata_refresh**, so the load DAGs have no
dependency on `data/metadata/`. Trigger it after adding a dataset, changing the rules, or when a load
adds columns; `lint` tells you what still needs a description or category.

## How loading works

`src/nfl_pipeline/` is the loader; the DAGs are thin wrappers around `ingest.load_dataset`, and dbt takes it from staging to clean.

- **Schema-on-write.** Tables are created from the Polars dtypes of the first file loaded. Later
  files that add columns get `ALTER TABLE ADD COLUMN`; a column whose type changes is widened
  (int → double → text). No hand-written DDL for 370-column pbp.
- **Idempotent partitions.** Seasonal datasets are `DELETE WHERE season = X` + `COPY` in one
  transaction. Re-running a season is safe. Non-seasonal datasets are `TRUNCATE` + `COPY`.
- **Fast.** Polars → CSV → `COPY FROM STDIN`. A full pbp season loads in ~3 s.
- **Cached downloads.** nflreadpy caches parquet files on a Docker volume (`NFLREADPY_CACHE_DIR`), 24 h TTL.
- **Staging is disposable.** After `dbt_build` has run, `staging.*` duplicates `clean.*`; **nfl_staging_truncate** empties it (all datasets or a subset) to reclaim disk. Loads are unaffected: the tables stay, only the rows go.

### Adding a dataset

Add one `Dataset(...)` entry to `REGISTRY` in `src/nfl_pipeline/datasets.py` (any `nflreadpy.load_*`
function works). Both DAGs grow a task group for it automatically on the next parse. Candidates:
`load_injuries`, `load_snap_counts`, `load_nextgen_stats`, `load_participation`, `load_ftn_charting`.

## Local development (no Airflow)

```bash
uv sync                                  # creates .venv with the package + dev tools
uv run nfl-pipeline list
uv run nfl-pipeline load pbp --season 2024
uv run nfl-pipeline backfill --start 2010 -d team_stats_week -d player_stats_week
uv run nfl-pipeline transform            # dbt build: upsert clean.*, rebuild nfl.*
uv run nfl-pipeline staging truncate -d pbp   # reclaim space once clean has it
uv run pytest
```

The CLI reads `NFL_DATABASE_URL` (defaults to the Docker Postgres on localhost) and the
`NFLREADPY_CACHE*` variables; dbt reads the same connection as parts (`NFL_DB_HOST` etc., see
`dbt/profiles.yml`). Airflow DAGs can be parse-checked locally with
`PYTHONPATH=dags:src uv run python -c "import nfl_backfill, nfl_weekly_refresh"`.

## Layout

```
dags/                 nfl_backfill.py, nfl_weekly_refresh.py, nfl_metadata_refresh.py, nfl_staging_truncate.py, common.py
src/nfl_pipeline/     config.py, datasets.py (registry), db.py (DDL/COPY), ingest.py, cli.py
dbt/                  dbt project: models/clean (typed copies, contracts, primary keys), models/marts (nfl views)
scripts/              gen_clean_models.py (typed SELECT per staging table), gen_dbt_columns.py (column yml)
sql/metadata/         metadata.column_labels view
data/                 curated inputs: metadata/*.yaml (labels, rules, overrides, table docs), coaching_staff_overrides.csv
docker/postgres/init  creates the `airflow` and `nfl` databases and the staging/clean/nfl/metadata schemas on first boot
docker-compose.yaml   Airflow 3.3.1 LocalExecutor stack; Dockerfile adds requirements.txt to the image
```

Rebuild the image only when `requirements.txt` changes (`docker compose build`); `src/`, `dags/`,
`sql/`, `data/` and `dbt/` are bind-mounted (dbt writes its `target/` and logs to `/tmp` inside the
containers). Nothing downloaded at runtime is written to disk except
nflreadpy's own parquet cache, which lives on a named Docker volume.

## Roadmap

- **Current betting lines.** Historical closing lines are already in `nfl.games`. For live/opening
  lines the plan is an append-only `staging.odds_snapshots` table (upserted into clean like everything else) fed by
  [The Odds API](https://the-odds-api.com/) (free tier: 500 credits/month) on a Thu/Sat/Sun
  cadence. `ODDS_API_KEY` is reserved in `.env.example`.
- Extend history: lower `NFL_START_SEASON` in `.env` or trigger `nfl_backfill` with an earlier
  `start_season`. pbp/stats go back to 1999.
