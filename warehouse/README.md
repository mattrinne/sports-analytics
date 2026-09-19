# warehouse

The data layer of sports-analytics: nflverse data (plus Wikipedia coaching staffs) loaded into
Postgres by the `nfl-pipeline` CLI, transformed by dbt into typed copies, identity tables and
persisted marts. The [root README](../README.md) has the system overview; this file lists what is
loaded and where the detail lives.

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
| participation | `staging.participation` | play | by season (2016+) | NGS charting: `offense_formation`, `offense_personnel`, `defense_personnel`, `defenders_in_box`, `number_of_pass_rushers`, `defense_man_zone_type`, `defense_coverage_type`, players on the field. Published after the season ends, so the current season is skipped until nflverse releases it; coverage type exists on about half of charted plays. |
| coaching_staff | `staging.coaching_staff` | coach-role × team-season | by season (2010+) | **Not nflverse.** Head coach, OC, DC with mid-season change dates, parsed from the Staff section of Wikipedia season articles (one batched API request per season, held in memory only; the current season falls back to each team's live `Template:<Team> staff`). Interim holders are separate rows; `flags` marks rows the parser wasn't sure about. Corrections go in `data/coaching_staff_overrides.csv`, which replaces parsed rows for the same season/team/role. |
| officials | `staging.officials` | game × official | by season (2015+) | |

Every staging table also has `_loaded_at timestamptz`; clean keeps it and uses it to find new rows.

## Documentation

| topic | file |
|---|---|
| schemas, what may live in each, the `clean` and `nfl` tables, dbt conventions | [`docs/layers.md`](docs/layers.md) |
| names, codes and ids: the `reference` layer, mappings, known quirks | [`docs/identity.md`](docs/identity.md) |
| `refresh` / `backfill`: code path, behaviour, options, run history, alerts | [`docs/loading.md`](docs/loading.md) |
| running the CLI, connection variables, verifying a change | [`docs/commands.md`](docs/commands.md) |

## Example queries

Typical queries go straight at `clean.*` (typed, all history) and join through `reference` to the
`nfl.*` keys:

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

## Layout

```
src/nfl_pipeline/     cli.py, datasets.py (registry), ingest.py + db.py (one load), runner.py (plan, parallel, retry),
                      pipeline.py (load → dbt → truncate), runs.py (ops.* history), alerts.py (webhook), transform.py (dbt)
dbt/                  dbt project: models/clean (typed copies), models/reference (mappings + identities), models/marts (nfl.* marts)
scripts/              gen_clean_models.py (typed SELECT per staging table), gen_dbt_columns.py (column yml), alias_candidates.py
data/                 curated inputs: coaching_staff_overrides.csv, seeds/reference_mappings.csv, seeds/coach_roles.csv
tests/                DB-free unit tests (runner, pipeline, run history, alerts, dbt env, CLI, parsers)
docs/                 layers.md, identity.md, loading.md, commands.md (the detail; README and CLAUDE.md point here)
Dockerfile            the pipeline image (python:3.12-slim + uv); built by the root compose file as `pipeline`
pyproject.toml        the `nfl-pipeline` package, dbt as a runtime dependency
```

The image contains the installed package, `dbt/` and `data/`; rebuild it after changing any
of those (`docker compose build pipeline` from the repo root).
