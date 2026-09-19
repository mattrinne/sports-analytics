"""Shared fixtures: sample rows shaped like the marts, an in-memory Repository, and app clients.
TestClient(app) without `with` never runs the lifespan, so no pool is ever opened here."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

import pytest
from fastapi.testclient import TestClient

from nfl_api.config import Settings
from nfl_api.db import get_repository
from nfl_api.main import create_app
from nfl_api.schemas import (
    Coach,
    CoachingTenure,
    Game,
    GameQuery,
    Health,
    Referee,
    Run,
    RunStep,
    RunSummary,
    Stadium,
    Team,
)

TS = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

SAMPLE_ROWS: dict[str, dict] = {
    "team": {"team_id": 6, "team_abbr": "DAL", "team_name": "Dallas Cowboys", "team_nick": "Cowboys",
                 "team_conf": "NFC", "team_division": "NFC East", "created_at": TS, "updated_at": TS},
    "team2": {"team_id": 1, "team_abbr": "ATL", "team_name": "Atlanta Falcons", "team_nick": "Falcons",
                  "team_conf": "NFC", "team_division": "NFC South", "created_at": TS, "updated_at": TS},
    "coach": {"coach_id": 1, "coach_name": "Mike McCarthy", "created_at": TS, "updated_at": TS},
    "referee": {"referee_id": 3, "referee_name": "Clete Blakeman", "created_at": TS, "updated_at": TS},
    "stadium": {"stadium_id": 9, "stadium_code": "DAL00", "stadium_name": "AT&T Stadium",
                    "roof": "retractable", "surface": "fieldturf", "first_season": 2009,
                    "last_season": 2026, "created_at": TS, "updated_at": TS},
    "tenure": {"coach_id": 1, "coach_name": "Mike McCarthy", "team_id": 6, "team_abbr": "DAL",
                   "team_name": "Dallas Cowboys", "role_id": 1, "role_abbr": "HC", "is_interim": False,
                   "first_season": 2020, "last_season": 2024, "start_date": date(2020, 1, 7),
                   "end_date": date(2025, 1, 13)},
    "game": {
        "game_id": 7001, "season": 2024, "game_type": "REG", "week": 1, "gameday": date(2024, 9, 8),
        "weekday": "Sunday", "gametime": time(13, 0), "time_of_day": "noon",
        "away_team_id": 6, "home_team_id": 1, "away_team_abbr": "DAL", "home_team_abbr": "ATL",
        "away_score": 27, "home_score": 20, "result": -7, "total": 47,
        "winning_team_id": 6, "winning_team_location": "away", "losing_team_id": 1,
        "losing_team_location": "home", "overtime": False, "location": "Home", "div_game": False,
        "gsis_id": 2024090800, "nfl_detail_id": None, "pfr_id": "202409080atl", "pff_id": None,
        "espn_id": 401671700, "ftn_id": None, "away_rest": 7, "home_rest": 7,
        "away_moneyline": -150, "home_moneyline": 130, "spread_line": -3.0, "away_spread_odds": -110,
        "home_spread_odds": -110, "total_line": 44.5, "over_odds": -105, "under_odds": -115,
        "roof": "outdoors", "surface": "grass", "temp": 78, "wind": 5,
        "away_coach_id": 1, "home_coach_id": 2, "referee_id": 3, "stadium_id": 9,
        "created_at": TS, "updated_at": TS,
    },
    "run_step": {"step_id": 1, "run_id": 12, "step": "teams", "season": 2026, "status": "loaded",
                     "attempts": 1, "rows": 32, "seconds": 0.4, "finished_at": TS, "error": None},
    "run": {"run_id": 12, "command": "refresh", "status": "success", "season": 2026, "args": {},
                "hostname": "laptop", "started_at": TS, "finished_at": TS, "error": None},
}


class FakeRepository:
    """In-memory Repository. Records the GameQuery it received so route tests can assert it."""

    def __init__(self, healthy: bool = True):
        self.teams = [Team.model_validate(SAMPLE_ROWS["team2"]), Team.model_validate(SAMPLE_ROWS["team"])]
        self.coaches = [Coach.model_validate(SAMPLE_ROWS["coach"])]
        self.referees = [Referee.model_validate(SAMPLE_ROWS["referee"])]
        self.stadiums = [Stadium.model_validate(SAMPLE_ROWS["stadium"])]
        self.tenures = [CoachingTenure.model_validate(SAMPLE_ROWS["tenure"])]
        self.games = [Game.model_validate(SAMPLE_ROWS["game"])]
        step = RunStep.model_validate(SAMPLE_ROWS["run_step"])
        self.runs = [Run.model_validate({**SAMPLE_ROWS["run"], "steps": [step]})]
        self.healthy = healthy
        self.last_games_query: GameQuery | None = None

    @staticmethod
    def _find(rows, key, value):
        return next((r for r in rows if getattr(r, key) == value), None)

    def list_teams(self): return self.teams
    def get_team(self, team_id): return self._find(self.teams, "team_id", team_id)
    def list_coaches(self): return self.coaches
    def get_coach(self, coach_id): return self._find(self.coaches, "coach_id", coach_id)
    def coach_tenures(self, coach_id): return [t for t in self.tenures if t.coach_id == coach_id]
    def list_referees(self): return self.referees
    def get_referee(self, referee_id): return self._find(self.referees, "referee_id", referee_id)
    def list_stadiums(self): return self.stadiums
    def get_stadium(self, stadium_id): return self._find(self.stadiums, "stadium_id", stadium_id)

    def list_games(self, q: GameQuery):
        self.last_games_query = q
        return self.games[q.offset : q.offset + q.limit], len(self.games)

    def get_game(self, game_id): return self._find(self.games, "game_id", game_id)
    def latest_runs(self, limit): return self.runs[:limit]

    def health(self):
        if not self.healthy:
            return Health(status="degraded", database="connection refused")
        latest = RunSummary.model_validate(SAMPLE_ROWS["run"])
        return Health(status="ok", database="ok", latest_run=latest, latest_success=latest)


def make_client(fake: FakeRepository, api_key: str | None = None) -> TestClient:
    app = create_app(Settings(database_url="postgresql://unused", api_key=api_key))
    app.dependency_overrides[get_repository] = lambda: fake
    return TestClient(app)


@pytest.fixture
def fake() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def client(fake) -> TestClient:
    return make_client(fake)
