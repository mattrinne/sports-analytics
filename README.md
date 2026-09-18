# sports-analytics

NFL data warehouse. [nflverse](https://github.com/nflverse) data is pulled once via
[`nflreadpy`](https://github.com/nflverse/nflreadpy) into Postgres by a small CLI that runs as a
scheduled container, so it can be analyzed forever without re-downloading. It is the data layer for
**The Hook**, a sports-betting analysis UI (see `docs/`).

```
nflverse parquet (GitHub releases)
        │  nflreadpy.load_*()           polars DataFrame
        ▼
 src/nfl_pipeline  ──COPY──▶  Postgres  staging.*  (landing zone: 1:1 mirror of the files, truncatable)
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
docker compose build pipeline                          # the nfl-pipeline image
docker compose run --rm pipeline backfill --start 2010 # every dataset 2010→now into staging.*, then dbt build
```

- Warehouse: `postgresql://nfl:nfl@localhost:5432/nfl` (works with `psql`, DBeaver, pandas, DuckDB…)
- Run history: `select * from ops.runs order by run_id desc;`

The backfill loads every dataset from `NFL_START_SEASON` (2010) through the current season into
`staging.*`, then runs `dbt build` to upsert `clean.*` and the `nfl.*` marts. Afterwards
`docker compose run --rm pipeline refresh` keeps the current season fresh; deployed, an Azure
Container Apps Job runs that same command on a schedule (see [Deploying](#deploying-to-azure)).
Narrow either to some datasets with `-d pbp -d schedules`.

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
[dbt](https://docs.getdbt.com/) from the project in `dbt/` at the end of every `refresh`/`backfill`
run and is a **column-for-column copy of staging with the types fixed**: same twelve
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
  dropped on a normal run, which is why every `refresh`/`backfill` ends by truncating the staging
  tables it loaded once dbt is green (`--keep-staging` opts out; `nfl-pipeline staging truncate`
  does it by hand). The next load lands only the seasons it fetches and dbt merges them into the
  full history in clean.
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
  fail`) when a model's columns changed. Both cases want `--full-refresh`. A full refresh rebuilds
  from whatever is in staging, and staging is normally empty, so use `backfill --full-refresh`
  (optionally `-d <table>`): it loads the seasons, rebuilds, then truncates again. A standalone
  `transform --full-refresh` only makes sense after a `backfill --keep-staging`.
- **`reference.*` owns identity.** `reference.reference_mappings` is the curated reference data
  (RDM): spelling and code equivalences per domain, seeded from `data/seeds/reference_mappings.csv`
  (`domain`, `source_system`, `source_value`, `canonical_value`, optional season range, note).
  Only exceptions are listed; anything without a row passes through unchanged. On top of it sit
  the master-data tables, one per entity: `reference.coach_identities`,
  `reference.referee_identities`, `reference.team_identities`, `reference.stadium_identities` and
  `reference.game_identities`, one row per spelling or code seen anywhere (`alias`: Wikipedia
  staff names, nflverse per-game head-coach and referee names, officials crew names, team codes,
  nflverse venue codes, nflverse and GSIS game ids), resolved to the canonical value and the key
  (`coach_id`, `referee_id`, `team_id`, `stadium_id`, `game_id`), with `source` = canonical or reference_mappings and
  `created_at`/`updated_at`. Ids are minted here: `coach_id` and `referee_id` from a sequence in
  order of first appearance and never reused (nflverse's `official_id` cannot serve: it was
  renumbered in 2023 and does not exist before 2015); the integer `game_id` likewise, with both
  the nflverse string (`2024_06_JAX_CHI`, used by pbp and the stats tables) and the GSIS
  `old_game_id` (`2024101300`, used by officials) as aliases; and `stadium_id` from the nflverse
  venue code (`JAX00`); `team_id` is nflverse's numeric franchise
  id, which a franchise keeps through relocations (OAK and LV are one team). To key any table on a
  coach, referee or team, join its name/code column to `alias`.
- **`nfl.*` holds persisted dimensions derived from `reference`.** `nfl.coaches`
  (`coach_id`, canonical `coach_name`, timestamps: every coach in the Wikipedia staff data and every
  head coach in the nflverse game log) and `nfl.teams` (exactly the 32 current
  franchises: `team_id`, canonical code with `LAR` for the Rams, name, nickname, conference,
  division, timestamps that move only when an attribute changes). "Current" is data-driven: the
  home teams of the latest season in `clean.schedules`. `nfl.referees` (`referee_id`, canonical
  `referee_name`, timestamps) covers every crew chief in the game log 1999+, replacement officials
  included. `nfl.stadiums` (integer `stadium_id`, nflverse venue code `stadium_code` such as
  `JAX00`, stable through naming-rights changes and present on every game and play, latest
  `stadium_name`, `roof` (dome / outdoors / retractable), latest `surface`, `first_season`,
  `last_season`); season-bounded `stadium` mapping rows correct names (the 2026 schedule still
  says Reliant Stadium). Analysis queries go straight against `clean.*` and join through `reference` to these
  keys.
- **`nfl.schedules`**: one row per game 1999+, played and scheduled, keyed by the integer
  `game_id`, with teams, head coaches, referee and venue as warehouse keys, scores and result,
  winner/loser id and side, the external ids (GSIS, PFR, PFF, ESPN, FTN), rest days, closing
  lines, weather, and `time_of_day` (kickoff in US Central: morning before 12:00, noon to 13:59,
  afternoon to 16:59, night from 17:00; `gametime` itself stays US Eastern as nflverse gives it).
  Incremental, so `updated_at` moves when a score lands, a kickoff is flexed or a line changes.
- **`nfl.coaching_tenures`**: one row per continuous stint of a coach in a role with a franchise
  (`coach_id`, `team_id`, `role_id`, `is_interim`, `first_season`, `last_season`, `start_date`,
  `end_date`, `start_source`, `end_source`, timestamps). Roles come from `reference.coach_roles`
  (1 HC, 2 OC, 3 DC; special teams is not tracked) via `reference_mappings` domain `coach_role`.
  Head coaches are built from the nflverse game log in `clean.schedules`, which names the head
  coach of every played game (1999+) and so catches coaches Wikipedia's end-of-season staff block
  omits (e.g. Nathaniel Hackett, fired in week 16 of 2022); Wikipedia adds the interim flag and
  any recorded change dates. Coordinators come from `clean.coaching_staff` (2010+). The source
  columns name the table each date came from: `coaching_staff` (a recorded date, exact) or
  `schedules` (the game log: first/last game coached around a mid-season head-coach change, or the
  season calendar as a proxy for an undated season-long stint: the day after the franchise's
  previous season ended, or its last game). A NULL date with a NULL source is unknown (an undated
  interim change and the coach it replaced); `end_source` = `ongoing` marks a current tenure.
  Incremental: only tenures whose dates,
  sources or last season changed are rewritten. `nfl.coaching_tenures_detail` is a view over it
  with `coach_name`, `team_abbr`/`team_name` and `role_abbr` joined in and the source/audit columns
  left out, for reading; the only views
  in `nfl` are presentation views like this one over persisted marts.
- **Maintaining the mappings.** Spelling variants (`Billy Davis` / `Bill Davis`, nflverse's
  `Klint Kubliak`; referee typos such as `Bill Carolo`, `Adrian Hall`, `John Perry`, verified
  against the officials crew data) and code variants (the warehouse uses 41 codes for 32 teams: era codes
  `STL`/`SD`/`OAK`, nflverse's `LA`, GSIS club codes `ARZ`/`BLT`/`CLV`/`HST`/`SL` in 2010–2015
  rosters) are fixed by adding a CSV row, never automatically: `uv run python
  scripts/alias_candidates.py coach|referee` prints look-alike pairs not yet mapped and a person
  decides (relatives such as the Harbaughs, Shanahans, Hochulis and Careys score high and must
  stay separate). On the next build the alias row takes the canonical's id and the retired id
  disappears from `nfl.coaches`. A dbt test fails the build if any table uses a team code that
  `team_identities` cannot resolve. Parser artifacts (footnote daggers, `, Jr.` punctuation) are
  fixed in the Wikipedia parser instead of being mapped.

Typical queries go straight at `clean.*` (typed, all history):

```sql
select posteam, avg(epa) from clean.pbp where season = 2024 and pass group by 1 order by 2 desc;
-- coverage charted by NGS participation (2016+, lags a season)
select pa.defense_coverage_type, count(*), avg(p.epa)
from clean.pbp p join clean.participation pa on pa.nflverse_game_id = p.game_id and pa.play_id = p.play_id
where p.season = 2024 and p.pass_attempt group by 1;
-- head-coach tenures, longest first
select coach_name, team_abbr, start_date, end_date, first_season, last_season
from nfl.coaching_tenures_detail
where role_abbr = 'HC' and not is_interim
order by last_season - first_season desc;
-- franchise wins 2010+, Raiders in Oakland and Las Vegas as one team
select t.team_abbr, count(*) as wins
from nfl.schedules g join nfl.teams t on t.team_id = g.winning_team_id
where g.season >= 2010 group by 1 order by 2 desc;
-- EPA per play keyed to the integer game id
select g.game_id, g.time_of_day, avg(p.epa)
from clean.pbp p join reference.game_identities gi on gi.alias = p.game_id
join nfl.schedules g on g.game_id = gi.game_id
where g.season = 2024 group by 1, 2;
```

```bash
uv run nfl-pipeline transform            # = dbt build (incremental upsert), connection from NFL_DATABASE_URL
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

The rebuild is its own command, not part of `refresh`, so loads have no dependency on
`data/metadata/`. Run it after adding a dataset, changing the rules, or when a load adds columns;
`lint` tells you what still needs a description or category.

## How loading works

`src/nfl_pipeline/` is the loader. `refresh` and `backfill` build a plan of (dataset, season) steps
from the registry and hand it to `runner.run_plan`; `ingest.load_dataset` does one step; dbt takes
it from staging to clean.

- **Schema-on-write.** Tables are created from the Polars dtypes of the first file loaded. Later
  files that add columns get `ALTER TABLE ADD COLUMN`; a column whose type changes is widened
  (int → double → text). No hand-written DDL for 370-column pbp.
- **Idempotent partitions.** Seasonal datasets are `DELETE WHERE season = X` + `COPY` in one
  transaction. Re-running a season is safe. Non-seasonal datasets are `TRUNCATE` + `COPY`.
- **Fast.** Polars → CSV → `COPY FROM STDIN`. A full pbp season loads in ~3 s.
- **Cached downloads.** nflreadpy caches parquet files on a Docker volume (`NFLREADPY_CACHE_DIR`), 24 h TTL.
- **Parallel across datasets, serial within one.** Up to `--workers` (4) datasets load at once;
  a dataset's seasons run one after another so the per-table lock never contends and memory stays
  bounded (one pbp season is ~0.5 GB at peak). Network and connection errors are retried
  (`--retries 2`, 30 s then 60 s); a season nflverse has not published yet (`participation` lags a
  year) is a *skip*, not a failure. dbt runs only when nothing failed; skips are fine.
- **Staging is disposable, and emptied by default.** After dbt has run, `staging.*` duplicates
  `clean.*`, so every `refresh`/`backfill` truncates the tables it loaded once dbt is green
  (`--keep-staging` to opt out; `nfl-pipeline staging truncate` by hand). Loads are unaffected: the
  tables stay, only the rows go.

### Run history and alerts

Every `refresh`/`backfill` writes one row to `ops.runs` (command, status `running|success|failed`,
season, args, start/finish, error) and one per step to `ops.run_steps` (dataset or `dbt_build` /
`truncate_staging`, status `loaded|skipped|failed`, attempts, rows, seconds, error). The tables are
created on first use; the future UI's data-health page reads them.

```sql
select run_id, command, status, started_at, finished_at, error from ops.runs order by run_id desc limit 10;
select step, season, status, attempts, rows, seconds from ops.run_steps where run_id = 42 order by step_id;
```

Set `NFL_ALERT_WEBHOOK_URL` (Slack incoming webhook, Discord webhook, an <https://ntfy.sh> topic) to
get a short message when a run fails; `--notify-success` sends one on success too. Exit code is 0
when everything loaded or skipped and dbt passed, 1 otherwise, 2 for a usage error.

### Adding a dataset

Add one `Dataset(...)` entry to `REGISTRY` in `src/nfl_pipeline/datasets.py` (any `nflreadpy.load_*`
function, or a dotted path to a loader in this package, works). `refresh`, `backfill` and `list`
pick it up automatically. Candidates:
`load_injuries`, `load_snap_counts`, `load_nextgen_stats`, `load_participation`, `load_ftn_charting`.

## Local development

```bash
uv sync                                  # creates .venv with the package + dev tools (dbt included)
uv run nfl-pipeline list
uv run nfl-pipeline load pbp --season 2024
uv run nfl-pipeline refresh -d schedules -d teams
uv run nfl-pipeline backfill --start 2010 -d team_stats_week -d player_stats_week
uv run nfl-pipeline transform            # dbt build: upsert clean.* and nfl.* marts
uv run nfl-pipeline staging truncate -d pbp   # by hand; refresh/backfill already do it
uv run pytest && uv run ruff check src tests scripts
```

The CLI reads `NFL_DATABASE_URL` (defaults to the Docker Postgres on localhost) and the
`NFLREADPY_CACHE*` variables; dbt gets the same connection as `NFL_DB_*` parts, derived from the
URL unless you set them yourself (`dbt/profiles.yml`). The same commands work inside the image:
`docker compose run --rm pipeline <command>`.

## Deploying to Azure

The warehouse runs on the cheapest serverless shape Azure offers: **Azure Database for PostgreSQL
Flexible Server** (burstable B1ms, the one always-on cost, ~$17/month with storage) and an
**Azure Container Apps Job** that starts the pipeline image on a cron trigger (`refresh`, Tue+Wed),
runs for a few minutes and exits, inside the free monthly grant. A
second, manually triggered job runs backfills. The image is pushed to GitHub Container Registry
(`ghcr.io/<owner>/nfl-pipeline`) by hand for now; a CI build is a later step.

The runbook and idempotent `az` scripts are in [`deploy/azure/`](deploy/azure/README.md).

## Layout

```
src/nfl_pipeline/     cli.py, datasets.py (registry), ingest.py + db.py (one load), runner.py (plan, parallel, retry),
                      pipeline.py (load → dbt → truncate), runs.py (ops.* history), alerts.py (webhook), transform.py (dbt), metadata.py
dbt/                  dbt project: models/clean (typed copies), models/reference (mappings + identities), models/marts (nfl.* dimensions, tenures)
scripts/              gen_clean_models.py (typed SELECT per staging table), gen_dbt_columns.py (column yml), alias_candidates.py
data/                 curated inputs: metadata/*.yaml (labels, rules, overrides, table docs), coaching_staff_overrides.csv, seeds/reference_mappings.csv
docker/postgres/init  creates the `nfl` database and the staging/clean/reference/nfl/metadata/ops schemas on first boot
docker-compose.yaml   postgres + the `pipeline` image (run on demand); Dockerfile builds the image with uv
deploy/azure/         runbook + az scripts: Flexible Server, Container Apps environment, scheduled + manual jobs
docs/                 The Hook: UI brainstorm, theme tokens
```

The image contains the installed package, `dbt/` and `data/`; rebuild it after changing any
of those (`docker compose build pipeline`). dbt writes `target/` and logs to `/tmp` inside the
container and nflreadpy's cache is off there (a named volume holds it locally); nothing downloaded
at runtime is written to disk.

## Roadmap

- **Current betting lines.** Historical closing lines are already in `clean.schedules`. For live/opening
  lines the plan is an append-only `staging.odds_snapshots` table (upserted into clean like everything else) fed by
  [The Odds API](https://the-odds-api.com/) (free tier: 500 credits/month) on a Thu/Sat/Sun
  cadence, as its own CLI command and scheduled job. `ODDS_API_KEY` is reserved in `.env.example`.
- Extend history: lower `NFL_START_SEASON` in `.env` or run `backfill --start 1999`. pbp/stats go
  back to 1999.
