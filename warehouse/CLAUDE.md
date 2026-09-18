# warehouse — working notes for Claude

The data layer: nflverse + Wikipedia → Postgres via `nfl-pipeline` → dbt. This folder is its own uv
project; run `uv ...` from here and `docker compose ...` from the repo root. The root `CLAUDE.md`
has the purpose, repo map and cross-cutting rules; `README.md` here is the user-facing detail.

## Layers (schemas) and what may live in each

| schema | built by | contents | rules |
|---|---|---|---|
| `staging` | Python loader (`src/nfl_pipeline`) | 1:1 mirror of each nflverse file, schema-on-write, one partition per season, `_loaded_at` stamp | **Disposable and normally empty.** Every `refresh`/`backfill` truncates the tables it loaded after a green dbt build (`--keep-staging` opts out; `nfl-pipeline staging truncate` by hand). Never build anything that needs staging to be complete. |
| `clean` | dbt `models/clean/` | **Column-for-column copy of staging with types fixed.** Same 12 tables, same names. Incremental `merge` by primary key, filtered on `_loaded_at`. | No derived tables, no dropped columns, no renames, no FKs. PK only (natural key or `_row_id` md5). Generated code — do not hand-edit (see below). |
| `reference` | dbt `models/reference/` + seeds | RDM: `reference_mappings` seed (source spelling/code → canonical, per `domain`). MDM: `*_identities` tables for coaches, referees, teams, stadiums, games (one row per spelling/code = `alias` → key). Small lookups (`coach_roles`). | Identity flows **mappings → identities → dimensions**. Ids are minted in identities, never in a dimension. |
| `nfl` | dbt `models/marts/` | Persisted dimensions/facts derived from `reference` + `clean`: `coaches`, `referees`, `teams`, `stadiums`, `schedules`, `coaching_tenures`. Presentation views over them (`coaching_tenures_detail`) join names/abbreviations onto keys. | Anything holding data is a table (`table` or `incremental`) with a contract and a PK, `created_at`/`updated_at`. A view may only re-present persisted marts (joins to dimensions), never derive new facts. |
| `metadata` | Python (`nfl_pipeline.metadata`) | Data dictionary + label axes for `clean.*` (same column names as staging). Manual `nfl-pipeline metadata build`. | Curated inputs in `data/metadata/*.yaml`. `metadata lint` must be 0 errors. |
| `ops` | Python (`nfl_pipeline.runs`) | Run history: `runs` (one per `refresh`/`backfill`) and `run_steps` (one per dataset step, `dbt_build`, `truncate_staging`). Created with `IF NOT EXISTS` on first use. | Never a dbt model (dbt runs after it and may fail). Best-effort: a failure to record never fails a load. The only non-`nfl` schema the UI may read (data-health page). |

Analysis queries go against `clean.*`, joined to `nfl.*` keys through `reference.*_identities.alias`.

## Ingestion path

1. `nfl_pipeline.datasets.REGISTRY` lists datasets (nflreadpy loader or dotted path, min season,
   partitioned or full-replace). Adding a dataset = one `Dataset(...)` entry; `refresh`, `backfill`
   and `list` pick it up automatically. Keep the registry source-agnostic: other sports/sources
   will be added the same way.
2. `ingest.load_dataset(name, season)`: fetch → Polars → lowercase columns + `_loaded_at` →
   `ensure_table` (CREATE / ADD COLUMN / widen type) → `DELETE season` + `COPY` in one transaction,
   under a per-table `pg_advisory_xact_lock` (concurrent loads of one table deadlocked without it).
3. `refresh` (current season) and `backfill` (season range) build a plan of `Step(dataset, season)`
   (`runner.refresh_plan/backfill_plan`) and run it through `pipeline.run_pipeline`:
   `runner.run_plan` (one worker per dataset, seasons serial inside it, `--workers 4`, retries on
   `OSError`/`OperationalError` with 30 s → 60 s backoff, `SeasonUnavailable` → `skipped`) →
   `dbt build` only if no step failed (skips are fine) → truncate the loaded staging tables, only
   after a green dbt (default; `--keep-staging` opts out) → `ops.runs` row finished → webhook
   (`NFL_ALERT_WEBHOOK_URL`) on failure. Exit 0/1/2.
   Deployed, an Azure Container Apps Job runs `refresh` on `0 14 * * 2,3` UTC
   (`deploy/azure/`). Side jobs are their own CLI command (`metadata build`, `staging truncate`) —
   never add cross-cutting steps to `refresh`.
4. `coaching_staff` is not nflverse: Wikipedia season articles, batched MediaWiki API, 1 req/s,
   in memory only, corrections via `data/coaching_staff_overrides.csv`. Parser lives in
   `src/nfl_pipeline/sources/wikipedia_staff.py`; `normalize_name()` strips footnote daggers and
   unifies `Jr.` punctuation — fix parser artifacts there, never with a mapping row.

## dbt conventions

- Project in `dbt/`, profile `nfl` reads `NFL_DB_*` env vars; `transform.dbt_env` derives them
  (incl. `NFL_DB_SSLMODE` from `?sslmode=`) from `NFL_DATABASE_URL` when unset, so one URL serves
  Python and dbt. dbt is a runtime dependency of the package (it ships in the image).
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
  `--full-refresh`. A full refresh rebuilds from staging, which is normally empty: use
  `backfill --full-refresh [-d t]` (load → rebuild → truncate), never a bare `transform --full-refresh`
  unless a `backfill --keep-staging` just ran.
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
  (`SeasonUnavailable` → step `skipped`, dbt still runs). Coverage type exists on ~half of charted plays.
- Early-September runs before nflverse publishes week 1 fail on pbp after retries and send one
  alert; expected until the files appear.
- Postgres auth is plain user/password (`nfl`/`nfl`) locally; Azure uses the Flexible Server admin
  URL with `?sslmode=require` as the single `NFL_DATABASE_URL` secret.

## Commands

From `warehouse/` (uv) and the repo root (compose):

```bash
uv sync && uv run pytest && uv run ruff check src tests scripts
uv run nfl-pipeline list | load pbp --season 2024 | refresh [-d x] [--keep-staging] | backfill --start 2010 [--full-refresh] | transform [--select x]
uv run nfl-pipeline staging truncate -d pbp        # by hand; refresh/backfill already do it
uv run nfl-pipeline metadata build && uv run nfl-pipeline metadata lint
cd dbt && uv run dbt build --profiles-dir .        # same as transform
cd .. && docker compose up -d                      # postgres only (repo root)
docker compose build pipeline && docker compose run --rm pipeline refresh -d teams   # image = what Azure runs
docker compose exec -T postgres psql -U nfl -d nfl -c "select * from ops.runs order by run_id desc limit 5"
```

Verify a change end to end: `dbt build` green twice in a row (second run should `MERGE 0` on
untouched models), `pytest`, `ruff`, a `docker compose run --rm pipeline refresh -d <small dataset>`
that exits 0 with a `success` row in `ops.runs`, and a look at the affected table in psql.
Commit only when asked. Paths in this file are relative to `warehouse/`.
