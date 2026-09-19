"""Opt-in: runs the real app (lifespan, pool, SQL) against a warehouse. Use the reader role so it
also proves the grants:
    NFL_TEST_DATABASE_URL=postgresql://nfl_reader:nfl_reader@localhost:5432/nfl uv run pytest tests/test_integration.py
"""

import os

import pytest
from fastapi.testclient import TestClient

from nfl_api.config import Settings
from nfl_api.main import create_app

pytestmark = pytest.mark.skipif(
    not os.environ.get("NFL_TEST_DATABASE_URL"), reason="needs NFL_TEST_DATABASE_URL"
)


@pytest.fixture(scope="module")
def client():
    app = create_app(Settings(database_url=os.environ["NFL_TEST_DATABASE_URL"]))
    with TestClient(app) as c:
        yield c


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["database"] == "ok"


def test_dimensions(client):
    teams = client.get("/teams").json()
    assert len(teams) == 32 and len({t["team_abbr"] for t in teams}) == 32
    team = client.get(f"/teams/{teams[0]['team_id']}").json()
    assert team == teams[0]
    coaches = client.get("/coaches").json()
    tenures = client.get(f"/coaches/{coaches[0]['coach_id']}/tenures").json()
    assert isinstance(tenures, list)  # view join to reference.coach_roles works under owner rights
    assert client.get("/referees").status_code == 200
    assert client.get("/stadiums").status_code == 200


def test_games(client):
    page = client.get("/games?season=2024&game_type=REG&limit=3").json()
    assert page["total"] == 272 and len(page["items"]) == 3
    first = page["items"][0]
    assert first["home_team_abbr"] and first["away_team_abbr"]
    assert client.get(f"/games/{first['game_id']}").json() == first
    dal = next(t["team_id"] for t in client.get("/teams").json() if t["team_abbr"] == "DAL")
    both = client.get(f"/games?season=2024&game_type=REG&team_id={dal}").json()["total"]
    home = client.get(f"/games?season=2024&game_type=REG&home_team_id={dal}").json()["total"]
    away = client.get(f"/games?season=2024&game_type=REG&away_team_id={dal}").json()["total"]
    assert both == home + away == 17
    spreads = client.get("/games?spread_min=7&sort=spread_line&order=desc&limit=5").json()
    values = [g["spread_line"] for g in spreads["items"]]
    assert values == sorted(values, reverse=True) and min(values) >= 7
    empty = client.get("/games?season=2024&offset=10000").json()
    assert empty["items"] == [] and empty["total"] > 0


def test_ops_runs(client):
    runs = client.get("/ops/runs?limit=2").json()
    assert runs and "steps" in runs[0]
