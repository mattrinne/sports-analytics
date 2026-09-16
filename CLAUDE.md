# sports-analytics — working notes for Claude

Local NFL warehouse: nflverse data (via `nflreadpy`) + Wikipedia coaching staffs → Postgres in
Docker, orchestrated by Airflow 3 (LocalExecutor), transformed by dbt. One user, one laptop.
Data is pulled once and analyzed forever; there is no live data. `README.md` is the user-facing
doc; this file is the contributor's mental model and the rules that are easy to break.

## Layers (schemas) and what may live in each

| schema | built by | contents | rules |
|---|---|---|---|
| `staging` | Python loader (`src/nfl_pipeline`) | 1:1 mirror of each nflverse file, schema-on-write, one partition per season, `_loaded_at` stamp | **Disposable.** Truncated periodically (`nfl_staging_truncate` DAG / `nfl-pipeline staging truncate`). Never build anything that needs staging to be complete. |
| `clean` | dbt `models/clean/` | **Column-for-column copy of staging with types fixed.** Same 12 tables, same names. Incremental `merge` by primary key, filtered on `_loaded_at`. | No derived tables, no dropped columns, no renames, no FKs. PK only (natural key or `_row_id` md5). Generated code — do not hand-edit (see below). |
| `reference` | dbt `models/reference/` + seeds | RDM: `reference_mappings` seed (source spelling/code → canonical, per `domain`). MDM: `*_identities` tables for coaches, referees, teams, stadiums, games (one row per spelling/code = `alias` → key). Small lookups (`coach_roles`). | Identity flows **mappings → identities → dimensions**. Ids are minted in identities, never in a dimension. |
| `nfl` | dbt `models/marts/` | Persisted dimensions/facts derived from `reference` + `clean`: `coaches`, `referees`, `teams`, `stadiums`, `schedules`, `coaching_tenures`. Presentation views over them (`coaching_tenures_detail`) join names/abbreviations onto keys. | Anything holding data is a table (`table` or `incremental`) with a contract and a PK, `created_at`/`updated_at`. A view may only re-present persisted marts (joins to dimensions), never derive new facts. |
| `metadata` | Python (`nfl_pipeline.metadata`) | Data dictionary + label axes for `clean.*` (same column names as staging). Manual DAG `nfl_metadata_refresh`. | Curated inputs in `data/metadata/*.yaml`. `metadata lint` must be 0 errors. |

Analysis queries go against `clean.*`, joined to `nfl.*` keys through `reference.*_identities.alias`.

## Ingestion path

1. `nfl_pipeline.datasets.REGISTRY` lists datasets (nflreadpy loader or dotted path, min season,
   partitioned or full-replace). Adding a dataset = one `Dataset(...)` entry; both load DAGs grow a
   TaskGroup automatically.
2. `ingest.load_dataset(name, season)`: fetch → Polars → lowercase columns + `_loaded_at` →
   `ensure_table` (CREATE / ADD COLUMN / widen type) → `DELETE season` + `COPY` in one transaction,
   under a per-table `pg_advisory_xact_lock` (concurrent seasons deadlocked without it).
3. DAGs: `nfl_backfill` (manual, season range, `datasets`, `full_refresh` params) and
   `nfl_weekly_refresh` (Tue/Wed 08:00 America/Chicago, current season). Both end in one
   `dbt_build` BashOperator: `dbt build` on the whole project. Side jobs are their own manual DAG
   (`nfl_metadata_refresh`, `nfl_staging_truncate`) — never add cross-cutting tasks to the load DAGs.
4. `coaching_staff` is not nflverse: Wikipedia season articles, batched MediaWiki API, 1 req/s,
   in memory only, corrections via `data/coaching_staff_overrides.csv`. Parser lives in
   `src/nfl_pipeline/sources/wikipedia_staff.py`; `normalize_name()` strips footnote daggers and
   unifies `Jr.` punctuation — fix parser artifacts there, never with a mapping row.

**Hard rule from the user:** nothing downloaded at runtime is written to disk (no vendored
dictionaries, no wikitext cache, dbt writes `target/`/logs to `/tmp` in containers). Curated,
human-owned inputs live under `data/` (`metadata/*.yaml`, `seeds/*.csv`, `coaching_staff_overrides.csv`).

## dbt conventions

- Project in `dbt/`, profile `nfl` reads `NFL_DB_*` env vars (compose sets `NFL_DB_HOST=postgres`).
  `threads: 1` (parallel FK/constraint DDL deadlocked). Custom `generate_schema_name` uses the
  configured schema verbatim.
- **Contracts enforced everywhere** (`clean`, `reference`, marts): every column declared with
  `data_type` in the model's `.yml`; PK via `constraints`. Reserved column names (`desc`, `time`)
  need `quote: true`. FKs are not declared: a seed cannot carry one (seeds are truncated each
  load) and the nflverse copy is not referentially complete — use `relationships` tests instead.
- Generic tests must use the `arguments:` form (`accepted_values: {arguments: {values: [...]}}`).
- **Clean models are generated.** `scripts/gen_clean_models.py <table>` writes the typed SELECT
  from the live staging schema (flags = doubles whose values ⊂ {0,1}, whole-number doubles/bigints
  → smallint/integer, ISO text → date/timestamptz; PK / `_row_id` rules at the top of the script).
  `scripts/gen_dbt_columns.py <table>` (re)writes the column yml from the built table, keeping
  hand-written descriptions and pulling nflverse descriptions from `metadata.columns`. Workflow
  after nflverse adds/retypes a column: load → gen model → `transform --full-refresh --select t`
  → gen columns.
- Incremental pattern used everywhere: compute the full candidate set, `left join` the existing
  table on the natural key, and emit only rows that are new or whose mutable columns
  `is distinct from` the incoming values, with `merge_update_columns` limited to those mutable
  columns + `updated_at`. That is what makes `updated_at` meaningful. Clean models instead filter
  on `_loaded_at > max(_loaded_at)` via the `only_new()` macro.
- Upserts never delete. A source row that disappears or changes key lingers until
  `--full-refresh` (DAG param `full_refresh`, or `nfl-pipeline transform --full-refresh`). A full
  refresh rebuilds from staging, so run it while staging holds the seasons you care about.
- `on_schema_change: fail` on incremental models: a column/type/order change must be a deliberate
  full refresh of that model.
- Deleting a model does **not** drop its table/view — drop it in Postgres too.

## Identity (reference) pattern — follow it for every new entity

1. Spellings/codes for the entity are collected from every source that mentions it (plus every
   `reference_mappings` row for its domain).
2. Each resolves to a canonical value through `reference_mappings` (`coalesce(canonical, alias)`).
3. `reference.<entity>_identities` (incremental merge on `alias`): `alias`, key, canonical value,
   `source` ∈ {canonical, reference_mappings} (games: {canonical, old_game_id}), timestamps. Keys:
   `coach_id`/`referee_id`/`stadium_id`/`game_id` from sequence `reference.<entity>_id_seq` (never reused; `full_refresh=false`; a merged name keeps
   the canonical's id, a new canonical inherits an alias's id only if nobody else holds it);
   `team_id` = nflverse franchise id (`clean.teams.team_id::int`, stable across relocations).
   Every warehouse key is an integer (user preference), even when the source has a stable code:
   `stadium_identities` maps nflverse venue codes (`JAX00`, kept as `nfl.stadiums.stadium_code`)
   to a minted id. nflverse `official_id` is not usable as a key: renumbered in 2023, absent
   before 2015.
4. `nfl.<entity>` dimension is *derived* from the identities table.
5. Mappings are curated by hand in `data/seeds/reference_mappings.csv` — **never auto-merge**.
   `scripts/alias_candidates.py coach|referee` lists look-alike names; relatives (Harbaugh,
   Shanahan, Gruden, Ryan, Kubiak, Phillips…; Hochuli, Carey, Steratore) score high and must stay
   separate. Verify a suspected referee typo against the crew in `clean.officials` (join
   `officials.game_id = schedules.old_game_id`; jersey numbers are stable per official).
   Canonical spelling = the most frequent form in the source. Rams canonical code is `LAR`
   (user decision; nflverse uses `LA`).

## Facts worth knowing before touching data

- Seasons loaded: 2010+ (`NFL_START_SEASON=2010`); `schedules` covers 1999+ in one file. Head
  coaches per game exist in `schedules` (`home_coach`/`away_coach`), which is why
  `nfl.coaching_tenures` builds HC stints from the game log and only uses Wikipedia for
  interim flags and recorded dates (Wikipedia's staff block omits mid-season firings).
- Game ids: nflverse `game_id` (`2024_06_JAX_CHI`) on schedules/pbp/stats/participation; GSIS
  `old_game_id` (`2024101300`) on officials. `reference.game_identities` carries both as aliases of
  one integer `game_id`, except unscheduled future games whose placeholder old ids collide (2026
  weeks 16–17) and a handful of officials rows whose old id matches no schedule row.
  `schedules.gametime` is US Eastern; `nfl.schedules.time_of_day` converts to US Central.
- `schedules.referee` and the Referee row in `officials` disagree for ~30 games 2016–2025
  (reassigned crews; 2022 week 1 is shifted by one game). Both names are real referees, so the
  dimension is unaffected; for a game-level referee prefer `officials` where it exists.
  `schedules.stadium_id` is trustworthy, `stadium` names change with sponsors, `pbp.stadium` is
  polluted (a venue's current name or an unrelated one) — use `pbp.game_stadium`/`schedules`.
- Team codes: 41 codes for 32 franchises across three systems (current nflverse, era codes
  `STL/SD/OAK`, GSIS `ARZ/BLT/CLV/HST/SL` in 2010–2015 rosters). `tests/assert_all_team_codes_resolve`
  fails the build on an unmapped code. `assert_stadium_names_unique_per_venue` warns (not fails) on
  upstream mis-tags such as the 2026 Jaguars London game carrying `JAX00`.
- Not-unique sources: `player_stats_week` has NULL `player_id` placeholder rows; `rosters*` and
  `depth_charts` have exact duplicates and rows differing only in secondary columns → `_row_id`
  hashes all columns for those. `depth_charts` changed format in 2025 (weekly rows → `dt`
  snapshots with no week).
- `participation` (NGS charting) lags a season; the current season is skipped
  (`SeasonUnavailable` → Airflow skip). Coverage type exists on ~half of charted plays.
- Postgres auth is plain user/password (`nfl`/`nfl`) from env; Airflow's own DB is `airflow`.

## Commands

```bash
uv sync && uv run pytest && uv run ruff check src dags tests scripts
uv run nfl-pipeline list | load pbp --season 2024 | backfill --start 2010 | transform [--full-refresh] [--select x]
uv run nfl-pipeline staging truncate -d pbp        # after transform has run
uv run nfl-pipeline metadata build && uv run nfl-pipeline metadata lint
cd dbt && uv run dbt build --profiles-dir .        # same as transform
docker compose build && docker compose up -d       # rebuild image only when requirements.txt changes
docker compose exec -T postgres psql -U nfl -d nfl
PYTHONPATH=dags:src uv run python -c "import nfl_backfill, nfl_weekly_refresh, nfl_metadata_refresh, nfl_staging_truncate"
```

Verify a change end to end: `dbt build` green twice in a row (second run should `MERGE 0` on
untouched models), `pytest`, `ruff`, DAG import check, and a look at the affected table in psql.
Nothing has been committed yet; commit only when asked.

## How the user likes to work

Short what/why/cost before an infrastructure or design choice, then a clear recommendation; they
decide quickly and sometimes reverse earlier designs (aggressive pruning → faithful copy; views →
persisted marts). When asked for an opinion, give an honest one and stop; when told to build,
build the whole thing, verify it, and report plainly including what was changed from the literal
spec and why.
