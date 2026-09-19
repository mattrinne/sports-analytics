from datetime import date

from nfl_api.schemas import GameQuery
from tests.conftest import FakeRepository, make_client


def test_dimension_lists_and_lookups(client):
    teams = client.get("/teams").json()
    assert [t["team_abbr"] for t in teams] == ["ATL", "DAL"]
    assert client.get("/teams/6").json()["team_name"] == "Dallas Cowboys"
    assert client.get("/teams/999").status_code == 404
    assert client.get("/coaches").json()[0]["coach_name"] == "Mike McCarthy"
    assert client.get("/coaches/1").status_code == 200
    assert client.get("/referees/3").json()["referee_name"] == "Clete Blakeman"
    assert client.get("/stadiums/9").json()["stadium_code"] == "DAL00"
    assert client.get("/stadiums/1").status_code == 404
    assert client.get("/teams/abc").status_code == 422


def test_coach_tenures(client):
    rows = client.get("/coaches/1/tenures").json()
    assert rows[0]["role_abbr"] == "HC" and rows[0]["start_date"] == "2020-01-07"
    assert client.get("/coaches/999/tenures").status_code == 404


def test_games_page_shape(client):
    body = client.get("/games").json()
    assert set(body) == {"items", "total", "limit", "offset"}
    assert body["total"] == 1 and body["limit"] == 100 and body["offset"] == 0
    g = body["items"][0]
    assert g["away_team_abbr"] == "DAL" and g["home_team_abbr"] == "ATL"
    assert g["spread_line"] == -3.0 and g["gametime"] == "13:00:00"


def test_games_query_parsed_and_passed_through(client, fake):
    r = client.get(
        "/games?season=2024&team_id=6&played=true&gameday_from=2024-09-01"
        "&sort=spread_line&order=asc&limit=5&offset=10"
    )
    assert r.status_code == 200
    assert fake.last_games_query == GameQuery(
        season=2024, team_id=6, played=True, gameday_from=date(2024, 9, 1),
        sort="spread_line", order="asc", limit=5, offset=10,
    )
    assert r.json()["limit"] == 5 and r.json()["offset"] == 10


def test_games_rejects_bad_params(client):
    for qs in ("sort=bogus", "seson=2024", "limit=0", "limit=5000", "offset=-1",
               "roof=indoors", "game_type=PRE", "season=abc"):
        assert client.get(f"/games?{qs}").status_code == 422, qs


def test_game_by_id(client):
    assert client.get("/games/7001").json()["game_id"] == 7001
    assert client.get("/games/1").status_code == 404


def test_ops_runs(client):
    runs = client.get("/ops/runs?limit=1").json()
    assert runs[0]["command"] == "refresh" and runs[0]["steps"][0]["step"] == "teams"
    assert client.get("/ops/runs?limit=0").status_code == 422


def test_health_ok_and_degraded():
    ok = make_client(FakeRepository()).get("/health")
    assert ok.status_code == 200 and ok.json()["latest_success"]["run_id"] == 12
    bad = make_client(FakeRepository(healthy=False)).get("/health")
    assert bad.status_code == 503 and bad.json() == {
        "status": "degraded", "database": "unavailable", "latest_run": None, "latest_success": None,
    }
