"""Pure SQL composition for /games, rendered without a connection."""

from datetime import date

import pytest

from nfl_api import games_query as gq
from nfl_api.schemas import GameQuery


def render(q: GameQuery):
    stmt, params = gq.games_page_query(q)
    return stmt.as_string(), params


def test_unfiltered():
    text, params = render(GameQuery())
    assert "WHERE TRUE ORDER BY s.\"gameday\" DESC NULLS LAST, s.game_id DESC" in text
    assert text.endswith("LIMIT %(limit)s OFFSET %(offset)s")
    assert params == {"limit": 100, "offset": 0}
    assert "LEFT JOIN nfl.teams th" in text and "LEFT JOIN nfl.teams ta" in text


def test_eq_range_either_and_played():
    text, params = render(GameQuery(season=2024, team_id=6, spread_min=3.5, played=True, limit=5))
    assert 's."season" = %(season)s' in text
    assert '(s."home_team_id" = %(team_id)s OR s."away_team_id" = %(team_id)s)' in text
    assert 's."spread_line" >= %(spread_min)s' in text
    assert "s.result IS NOT NULL" in text
    assert params == {"season": 2024, "team_id": 6, "spread_min": 3.5, "limit": 5, "offset": 0}


def test_played_false():
    text, params = render(GameQuery(played=False))
    assert "s.result IS NULL" in text and "played" not in params


@pytest.mark.parametrize("field,col", list(gq._EQ.items()))
def test_every_eq_filter(field, col):
    sample = {"game_type": "REG", "roof": "dome", "surface": "grass", "div_game": True, "overtime": False}
    value = sample.get(field, 7)
    text, params = render(GameQuery(**{field: value}))
    assert f's."{col}" = %({field})s' in text and params[field] == value


@pytest.mark.parametrize("field,col_op", list(gq._RANGE.items()))
def test_every_range_filter(field, col_op):
    col, op = col_op
    value = date(2024, 1, 1) if field.startswith("gameday") else 2020
    text, params = render(GameQuery(**{field: value}))
    assert f's."{col}" {op} %({field})s' in text and params[field] == value


@pytest.mark.parametrize("field,cols", list(gq._EITHER.items()))
def test_every_either_filter(field, cols):
    a, b = cols
    text, params = render(GameQuery(**{field: 3}))
    assert f'(s."{a}" = %({field})s OR s."{b}" = %({field})s)' in text and params[field] == 3


def test_every_query_field_is_mapped():
    """Adding a field to GameQuery without a SQL mapping fails here, not in production."""
    assert set(GameQuery.model_fields) == gq.FILTER_FIELDS | gq.PAGING_FIELDS


def test_sort_asc_with_tiebreaker():
    text, _ = render(GameQuery(sort="spread_line", order="asc"))
    assert 'ORDER BY s."spread_line" ASC NULLS LAST, s.game_id ASC' in text


def test_count_shares_where_without_paging():
    q = GameQuery(season=2024, week=3, sort="week", limit=10, offset=20)
    text, params = gq.games_count_query(q)
    text = text.as_string()
    assert text.startswith("SELECT count(*) AS total FROM nfl.schedules s WHERE ")
    assert 's."season" = %(season)s AND s."week" = %(week)s' in text
    assert "ORDER BY" not in text and "LIMIT" not in text
    assert params == {"season": 2024, "week": 3}


def test_game_by_id():
    assert gq.game_by_id_query().as_string().endswith("WHERE s.game_id = %(game_id)s")
