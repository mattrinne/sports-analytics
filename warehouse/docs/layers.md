# Layers: schemas, what may live in each, dbt conventions

One Postgres database, `nfl`, five schemas. `staging` is written by the Python loader
(`src/nfl_pipeline`), `clean`, `reference` and `nfl` by dbt (`dbt/`), `ops` by the loader's run
recorder. Paths are relative to `warehouse/`.

## Schemas

| schema | built by | contents | rules |
|---|---|---|---|
| `staging` | Python loader | 1:1 mirror of each nflverse file, schema-on-write, one partition per season, `_loaded_at` stamp | **Disposable and normally empty.** Every `refresh`/`backfill` truncates the tables it loaded after a green dbt build (`--keep-staging` opts out; `nfl-pipeline staging truncate` by hand). Never build anything that needs staging to be complete. Tables stay, only the rows go, so the database holds `clean.*` (~2.5 GB for 2010+) and the small schemas. |
| `clean` | dbt `models/clean/` | **Column-for-column copy of staging with types fixed.** Same 12 tables, same names. Incremental `merge` by primary key, filtered on `_loaded_at`. | No derived tables, no dropped columns, no renames, no FKs. PK only (natural key or `_row_id` md5). Generated code — do not hand-edit (see below). |
| `reference` | dbt `models/reference/` + seeds | RDM: `reference_mappings` seed (source spelling/code → canonical, per `domain`). MDM: `*_identities` tables for coaches, referees, teams, stadiums, games (one row per spelling/code = `alias` → key). Small lookups (`coach_roles`). | Identity flows **mappings → identities → dimensions**. Ids are minted in identities, never in a dimension. Details: `identity.md`. |
| `nfl` | dbt `models/marts/` | Persisted dimensions/facts derived from `reference` + `clean`: `coaches`, `referees`, `teams`, `stadiums`, `schedules`, `coaching_tenures`. Presentation views over them (`coaching_tenures_detail`) join names/abbreviations onto keys. | Anything holding data is a table (`table` or `incremental`) with a contract and a PK, `created_at`/`updated_at`. A view may only re-present persisted marts (joins to dimensions), never derive new facts. |
| `ops` | Python (`nfl_pipeline.runs`) | Run history: `runs` (one per `refresh`/`backfill`) and `run_steps` (one per dataset step, `dbt_build`, `truncate_staging`). Created with `IF NOT EXISTS` on first use. | Never a dbt model (dbt runs after it and may fail). Best-effort: a failure to record never fails a load. The only non-`nfl` schema the api reads (`/health`, `/ops/runs`). |

Analysis queries go against `clean.*` (typed, all history), joined to `nfl.*` keys through
`reference.*_identities.alias`; the api reads `nfl.*` and `ops.*` only.

## `clean`: staging with the types fixed

- **Types fixed.** nflverse's parquet files lose types on the way in: 0/1 doubles become
  `boolean` (82 pbp flags such as `shotgun`, `touchdown`, `pass`), whole-number doubles and
  bigints become `smallint`/`integer`, ISO text becomes `date`/`time`/`timestamptz`
  (`gameday`, `gametime`, `time_of_day`, `birth_date`), and nothing else changes. The casts are
  generated from the live staging schema by `scripts/gen_clean_models.py`, so a new column shows
  up typed on the next generation run.
- **Upserted, so staging is disposable.** Each clean table is a dbt incremental model with the
  `merge` strategy on a primary key. A run takes only source rows whose `_loaded_at` is newer
  than anything already in clean (macro `only_new`), and merges them by key. Nothing is ever
  dropped on a normal run, which is what allows staging to be emptied afterwards.
- **Keys.** Natural keys where the source has one: `schedules(game_id)`, `pbp(game_id, play_id)`,
  `participation(nflverse_game_id, play_id)`, `team_stats_week(season, week, team)`,
  `officials(game_id, official_id)`, `teams(team_abbr)`, `players(gsis_id)`. Where it does not
  (`player_stats_week` has team placeholder rows without a player id; a player can appear twice
  in one week of `rosters_weekly` with two statuses; `depth_charts` has two formats and exact
  duplicates; `coaching_staff` stints can lack a start date) the table gets an `_row_id` md5 of
  all its columns and exact duplicate rows collapse to one. Foreign keys are not declared: a copy
  of nflverse is not referentially complete (roster-only players are missing from `players`, for
  instance), so joins across clean are by convention, as in the source.
- **Documented.** Column descriptions in the model yml (mostly from the nflverse data
  dictionaries) are written as Postgres `COMMENT`s (`\d+ clean.pbp` in psql shows them).

## `nfl`: persisted marts

- **Dimensions derived from `reference`.** `nfl.coaches` (`coach_id`, canonical `coach_name`,
  timestamps: every coach in the Wikipedia staff data and every head coach in the nflverse game
  log). `nfl.teams` (exactly the 32 current franchises: `team_id`, canonical code with `LAR` for
  the Rams, name, nickname, conference, division, timestamps that move only when an attribute
  changes); "current" is data-driven: the home teams of the latest season in `clean.schedules`.
  `nfl.referees` (`referee_id`, canonical `referee_name`, timestamps) covers every crew chief in
  the game log 1999+, replacement officials included. `nfl.stadiums` (integer `stadium_id`,
  nflverse venue code `stadium_code` such as `JAX00`, stable through naming-rights changes and
  present on every game and play, latest `stadium_name`, `roof` (dome / outdoors / retractable),
  latest `surface`, `first_season`, `last_season`); season-bounded `stadium` mapping rows correct
  names (the 2026 schedule still says Reliant Stadium).
- **`nfl.schedules`**: one row per game 1999+, played and scheduled, keyed by the integer
  `game_id`, with teams, head coaches, referee and venue as warehouse keys, scores and result,
  winner/loser id and side, the external ids (GSIS, PFR, PFF, ESPN, FTN), rest days, closing
  lines, weather, and `time_of_day` (kickoff in US Central: morning before 12:00, noon to 13:59,
  afternoon to 16:59, night from 17:00; `gametime` itself stays US Eastern as nflverse gives it).
  Incremental, so `updated_at` moves when a score lands, a kickoff is flexed or a line changes.
- **`nfl.coaching_tenures`**: one row per continuous stint of a coach in a role with a franchise
  (`coach_id`, `team_id`, `role_id`, `is_interim`, `first_season`, `last_season`, `start_date`,
  `end_date`, `start_source`, `end_source`, timestamps). Roles come from `reference.coach_roles`
  (1 HC, 2 OC, 3 DC; special teams is not pulled) via `reference_mappings` domain `coach_role`.
  Head coaches are built from the nflverse game log in `clean.schedules`, which names the head
  coach of every played game (1999+) and so catches coaches Wikipedia's end-of-season staff block
  omits (e.g. Nathaniel Hackett, fired in week 16 of 2022); Wikipedia adds the interim flag and
  any recorded change dates. Coordinators come from `clean.coaching_staff` (2010+). The source
  columns name the table each date came from: `coaching_staff` (a recorded date, exact) or
  `schedules` (the game log: first/last game coached around a mid-season head-coach change, or the
  season calendar as a proxy for an undated season-long stint: the day after the franchise's
  previous season ended, or its last game). A NULL date with a NULL source is unknown (an undated
  interim change and the coach it replaced); `end_source` = `ongoing` marks a current tenure.
  Incremental: only tenures whose dates, sources or last season changed are rewritten.
  `nfl.coaching_tenures_detail` is a view over it with `coach_name`, `team_abbr`/`team_name` and
  `role_abbr` joined in and the source/audit columns left out; the only views in `nfl` are
  presentation views like this one over persisted marts.

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
- **Clean models are generated.** `models/clean/<table>.sql` is the typed SELECT written by
  `scripts/gen_clean_models.py` from the live staging schema (flags = doubles whose values ⊂
  {0,1}, whole-number doubles/bigints → smallint/integer, ISO text → date/timestamptz; PK /
  `_row_id` rules at the top of the script). `models/clean/<table>.yml` declares every column with
  its type, description and primary-key constraint, written by `scripts/gen_dbt_columns.py` from
  the built table (hand-written descriptions are kept). Regenerate both after nflverse adds or
  retypes a column: run the loads, then

  ```bash
  uv run python scripts/gen_clean_models.py <table>                # rewrite the SELECT from staging
  uv run nfl-pipeline transform --full-refresh --select <table>    # recreate with the new shape (staging still loaded)
  uv run python scripts/gen_dbt_columns.py <table>                 # refresh the yml (keeps hand edits)
  ```

- Incremental pattern used everywhere: compute the full candidate set, `left join` the existing
  table on the natural key, and emit only rows that are new or whose mutable columns
  `is distinct from` the incoming values, with `merge_update_columns` limited to those mutable
  columns + `updated_at`. That is what makes `updated_at` meaningful. Clean models instead filter
  on `_loaded_at > max(_loaded_at)` via the `only_new()` macro.
- **Upserts never delete.** A source row that disappears or changes key lingers until
  `--full-refresh`; a normal build also cannot see rows nflverse *deleted* from a re-published
  season. A full refresh rebuilds from staging, which is normally empty: use
  `backfill --full-refresh [-d t]` (load → rebuild → truncate), never a bare
  `transform --full-refresh` unless a `backfill --keep-staging` just ran.
- `on_schema_change: fail` on incremental models: a column/type/order change must be a deliberate
  full refresh of that model.
- Deleting a model does **not** drop its table/view — drop it in Postgres too.
