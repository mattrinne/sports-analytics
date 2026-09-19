"""SQL for GET /games, composed with psycopg.sql and nothing else. Column names come only from the
tables below (through sql.Identifier), operators only from literals here, and every user value
travels as a named placeholder bound by psycopg. Pure functions: no connection, testable by
rendering with .as_string()."""

from __future__ import annotations

from psycopg import sql

from .schemas import GameQuery

# query field -> schedules column, compared with =
_EQ = {
    "season": "season",
    "week": "week",
    "game_type": "game_type",
    "home_team_id": "home_team_id",
    "away_team_id": "away_team_id",
    "referee_id": "referee_id",
    "stadium_id": "stadium_id",
    "roof": "roof",
    "surface": "surface",
    "div_game": "div_game",
    "overtime": "overtime",
}
# query field -> (column, operator)
_RANGE = {
    "season_from": ("season", ">="),
    "season_to": ("season", "<="),
    "gameday_from": ("gameday", ">="),
    "gameday_to": ("gameday", "<="),
    "spread_min": ("spread_line", ">="),
    "spread_max": ("spread_line", "<="),
    "total_line_min": ("total_line", ">="),
    "total_line_max": ("total_line", "<="),
}
# query field -> the two columns either of which may match
_EITHER = {
    "team_id": ("home_team_id", "away_team_id"),
    "coach_id": ("home_coach_id", "away_coach_id"),
}
# fields of GameQuery that are not filters
PAGING_FIELDS = frozenset({"sort", "order", "limit", "offset"})
FILTER_FIELDS = frozenset(_EQ) | frozenset(_RANGE) | frozenset(_EITHER) | {"played"}

_SELECT = sql.SQL(
    "SELECT s.*, th.team_abbr AS home_team_abbr, ta.team_abbr AS away_team_abbr "
    "FROM nfl.schedules s "
    "LEFT JOIN nfl.teams th ON th.team_id = s.home_team_id "
    "LEFT JOIN nfl.teams ta ON ta.team_id = s.away_team_id "
    "WHERE "
)
_SELECT_ONE = _SELECT + sql.SQL("s.game_id = %(game_id)s")
_COUNT = sql.SQL("SELECT count(*) AS total FROM nfl.schedules s WHERE ")


def games_where(q: GameQuery) -> tuple[sql.Composable, dict[str, object]]:
    """WHERE body (without the keyword) and its named parameters. `TRUE` when unfiltered."""
    clauses: list[sql.Composable] = []
    params: dict[str, object] = {}
    for field, value in q.model_dump(exclude_none=True).items():
        if field in PAGING_FIELDS:
            continue
        if field == "played":
            clauses.append(sql.SQL("s.result IS NOT NULL" if value else "s.result IS NULL"))
            continue
        if field in _EQ:
            clauses.append(
                sql.SQL("s.{} = {}").format(sql.Identifier(_EQ[field]), sql.Placeholder(field))
            )
        elif field in _RANGE:
            col, op = _RANGE[field]
            clauses.append(
                sql.SQL("s.{} {} {}").format(sql.Identifier(col), sql.SQL(op), sql.Placeholder(field))
            )
        elif field in _EITHER:
            a, b = _EITHER[field]
            clauses.append(
                sql.SQL("(s.{a} = {v} OR s.{b} = {v})").format(
                    a=sql.Identifier(a), b=sql.Identifier(b), v=sql.Placeholder(field)
                )
            )
        else:
            raise ValueError(f"no SQL mapping for GameQuery field {field!r}")
        params[field] = value
    where = sql.SQL(" AND ").join(clauses) if clauses else sql.SQL("TRUE")
    return where, params


def games_page_query(q: GameQuery) -> tuple[sql.Composed, dict[str, object]]:
    """The page of games: filters, whitelisted sort with game_id tiebreaker, limit/offset."""
    where, params = games_where(q)
    direction = sql.SQL("DESC" if q.order == "desc" else "ASC")
    order_by = sql.SQL(" ORDER BY s.{col} {d} NULLS LAST, s.game_id {d}").format(
        col=sql.Identifier(q.sort), d=direction
    )
    tail = sql.SQL(" LIMIT %(limit)s OFFSET %(offset)s")
    return _SELECT + where + order_by + tail, {**params, "limit": q.limit, "offset": q.offset}


def games_count_query(q: GameQuery) -> tuple[sql.Composed, dict[str, object]]:
    """count(*) over the same filters (no sort, no paging)."""
    where, params = games_where(q)
    return _COUNT + where, params


def game_by_id_query() -> sql.Composed:
    return _SELECT_ONE
