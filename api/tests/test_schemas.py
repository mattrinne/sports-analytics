"""Models round-trip sample rows, and each mirrors its dbt contract column for column."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from nfl_api import schemas
from nfl_api.schemas import Game, GameQuery
from tests.conftest import SAMPLE_ROWS

MARTS = Path(__file__).resolve().parents[2] / "warehouse" / "dbt" / "models" / "marts"

# model -> (contract yml, fields the model adds on top of the contract)
CONTRACTS = {
    schemas.Team: ("nfl_teams.yml", set()),
    schemas.Coach: ("nfl_coaches.yml", set()),
    schemas.Referee: ("nfl_referees.yml", set()),
    schemas.Stadium: ("nfl_stadiums.yml", set()),
    schemas.CoachingTenure: ("nfl_coaching_tenures_detail.yml", set()),
    schemas.Game: ("nfl_schedules.yml", {"home_team_abbr", "away_team_abbr"}),
}


@pytest.mark.parametrize("key", ["team", "coach", "referee", "stadium", "tenure", "game", "run_step"])
def test_sample_rows_validate(key):
    model = {
        "team": schemas.Team, "coach": schemas.Coach, "referee": schemas.Referee,
        "stadium": schemas.Stadium, "tenure": schemas.CoachingTenure, "game": schemas.Game,
        "run_step": schemas.RunStep,
    }[key]
    m = model.model_validate(SAMPLE_ROWS[key])
    assert m.model_dump(mode="json")  # serialisable


def test_game_json_types():
    g = Game.model_validate(SAMPLE_ROWS["game"])
    d = g.model_dump(mode="json")
    assert d["gametime"] == "13:00:00" and d["gameday"] == "2024-09-08"
    assert d["spread_line"] == -3.0 and d["total_line"] == 44.5


def test_game_extra_column_ignored_missing_key_rejected():
    Game.model_validate({**SAMPLE_ROWS["game"], "row_count": 1})
    with pytest.raises(ValidationError):
        Game.model_validate({k: v for k, v in SAMPLE_ROWS["game"].items() if k != "game_id"})


@pytest.mark.skipif(not MARTS.exists(), reason="warehouse dbt contracts not on this checkout")
@pytest.mark.parametrize("model", list(CONTRACTS))
def test_model_matches_contract(model):
    yml, extra = CONTRACTS[model]
    doc = yaml.safe_load((MARTS / yml).read_text())
    contract_cols = {c["name"] for c in doc["models"][0]["columns"]}
    assert set(model.model_fields) == contract_cols | extra


def test_game_query_defaults_and_validation():
    q = GameQuery()
    assert (q.sort, q.order, q.limit, q.offset) == ("gameday", "desc", 100, 0)
    with pytest.raises(ValidationError):
        GameQuery(sort="bogus")
    with pytest.raises(ValidationError):
        GameQuery(limit=0)
    with pytest.raises(ValidationError):
        GameQuery(seson=2024)  # extra=forbid
