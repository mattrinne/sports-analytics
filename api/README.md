# api

Read-only HTTP API over the warehouse: the `nfl.*` marts and `ops.*` run history, as JSON.
FastAPI + psycopg 3, served by uvicorn on port 8000. Interactive docs at `/docs`.

| route | returns |
|---|---|
| `GET /health` | database status plus the latest run and latest successful run from `ops.runs` (503 when the database is unreachable) |
| `GET /teams`, `/teams/{team_id}` | `nfl.teams` |
| `GET /coaches`, `/coaches/{coach_id}` | `nfl.coaches` |
| `GET /coaches/{coach_id}/tenures` | `nfl.coaching_tenures_detail` for one coach |
| `GET /referees`, `/referees/{referee_id}` | `nfl.referees` |
| `GET /stadiums`, `/stadiums/{stadium_id}` | `nfl.stadiums` |
| `GET /games` | `nfl.schedules` (every column, plus `home_team_abbr`/`away_team_abbr`), filtered, sorted and paginated: `{items, total, limit, offset}` |
| `GET /games/{game_id}` | one game |
| `GET /ops/runs?limit=10` | latest pipeline runs with their steps |

`/games` filters: `season`, `season_from`, `season_to`, `week`, `game_type` (REG/WC/DIV/CON/SB),
`team_id` (either side), `home_team_id`, `away_team_id`, `coach_id` (either side), `referee_id`,
`stadium_id`, `roof`, `surface`, `div_game`, `overtime`, `gameday_from`, `gameday_to`,
`spread_min`, `spread_max` (closing spread, positive = home favoured), `total_line_min`,
`total_line_max`, `played`. Sorting: `sort` (gameday, season, week, game_id, spread_line,
total_line, result, total) and `order` (asc/desc, default `gameday desc`). Paging: `limit`
(default 100, max 1000) and `offset`. Unknown or invalid parameters return 422.

```bash
curl -s 'localhost:8000/games?season=2024&game_type=REG&team_id=6&played=true&sort=spread_line&order=desc&limit=5'
```

## Running

In compose (repo root) the `api` service starts with `docker compose up -d`, listens on
`localhost:8000` and connects as the read-only role `nfl_reader` (created by
`docker/postgres/init/02-reader-role.sh`). Running on the laptop, rebuilding the image, tests and
applying the role to an older volume: [`docs/commands.md`](docs/commands.md).

Environment (read from the process environment; compose passes them from `.env`):

| variable | default | meaning |
|---|---|---|
| `NFL_DATABASE_URL` | `postgresql://nfl:nfl@localhost:5432/nfl` | warehouse connection |
| `NFL_API_KEY` | empty | when set, every data route requires the `X-API-Key` header with this value; `/health` and the `/docs` schema stay open |
| `NFL_API_CORS_ORIGINS` | empty | comma-separated origins allowed by CORS (GET only) |
| `NFL_API_POOL_MIN` / `NFL_API_POOL_MAX` | 1 / 10 | Postgres connection pool size; the max also caps concurrent requests |
