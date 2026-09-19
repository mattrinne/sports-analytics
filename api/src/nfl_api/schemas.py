"""Response models. Each mirrors a dbt contract in warehouse/dbt/models/marts/<model>.yml column
for column (tests/test_schemas.py checks that); nullable unless the contract says not_null or PK."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MartModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class Team(MartModel):
    team_id: int
    team_abbr: str
    team_name: str | None
    team_nick: str | None
    team_conf: str | None
    team_division: str | None
    created_at: datetime
    updated_at: datetime


class Coach(MartModel):
    coach_id: int
    coach_name: str
    created_at: datetime
    updated_at: datetime


class Referee(MartModel):
    referee_id: int
    referee_name: str
    created_at: datetime
    updated_at: datetime


class Stadium(MartModel):
    stadium_id: int
    stadium_code: str
    stadium_name: str
    roof: str | None
    surface: str | None
    first_season: int
    last_season: int
    created_at: datetime
    updated_at: datetime


class CoachingTenure(MartModel):
    """A row of the nfl.coaching_tenures_detail view."""

    coach_id: int
    coach_name: str
    team_id: int
    team_abbr: str
    team_name: str | None
    role_id: int
    role_abbr: str
    is_interim: bool
    first_season: int
    last_season: int
    start_date: date | None
    end_date: date | None


class Game(MartModel):
    """A row of nfl.schedules plus the two team abbreviations joined from nfl.teams."""

    game_id: int
    season: int
    game_type: str | None
    week: int
    gameday: date
    weekday: str | None
    gametime: time | None
    time_of_day: str | None
    away_team_id: int
    home_team_id: int
    away_team_abbr: str | None
    home_team_abbr: str | None
    away_score: int | None
    home_score: int | None
    result: int | None
    total: int | None
    winning_team_id: int | None
    winning_team_location: str | None
    losing_team_id: int | None
    losing_team_location: str | None
    overtime: bool | None
    location: str | None
    div_game: bool | None
    gsis_id: int | None
    nfl_detail_id: str | None
    pfr_id: str | None
    pff_id: int | None
    espn_id: int | None
    ftn_id: int | None
    away_rest: int | None
    home_rest: int | None
    away_moneyline: int | None
    home_moneyline: int | None
    spread_line: float | None
    away_spread_odds: int | None
    home_spread_odds: int | None
    total_line: float | None
    over_odds: int | None
    under_odds: int | None
    roof: str | None
    surface: str | None
    temp: int | None
    wind: int | None
    away_coach_id: int | None
    home_coach_id: int | None
    referee_id: int | None
    stadium_id: int | None
    created_at: datetime
    updated_at: datetime


GameSort = Literal[
    "gameday", "season", "week", "game_id", "spread_line", "total_line", "result", "total"
]
Order = Literal["asc", "desc"]


class GameQuery(BaseModel):
    """Query parameters of GET /games: filters plus sort and paging in one model. Unknown
    parameters are rejected (422) so a misspelt filter cannot silently return every game."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    season: int | None = None
    season_from: int | None = None
    season_to: int | None = None
    week: int | None = None
    game_type: Literal["REG", "WC", "DIV", "CON", "SB"] | None = None
    team_id: int | None = Field(None, description="Either side")
    home_team_id: int | None = None
    away_team_id: int | None = None
    coach_id: int | None = Field(None, description="Head coach on either side")
    referee_id: int | None = None
    stadium_id: int | None = None
    roof: Literal["outdoors", "open", "closed", "dome"] | None = None
    surface: str | None = None
    div_game: bool | None = None
    overtime: bool | None = None
    gameday_from: date | None = None
    gameday_to: date | None = None
    spread_min: float | None = Field(None, description="spread_line >= (positive = home favoured)")
    spread_max: float | None = Field(None, description="spread_line <=")
    total_line_min: float | None = None
    total_line_max: float | None = None
    played: bool | None = Field(None, description="true: result known; false: not yet played")
    sort: GameSort = "gameday"
    order: Order = "desc"
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class RunStep(MartModel):
    step_id: int
    run_id: int
    step: str
    season: int | None
    status: str
    attempts: int
    rows: int | None
    seconds: float | None
    finished_at: datetime
    error: str | None


class Run(MartModel):
    run_id: int
    command: str
    status: str
    season: int | None
    args: dict
    hostname: str | None
    started_at: datetime
    finished_at: datetime | None
    error: str | None
    steps: list[RunStep]


class RunSummary(MartModel):
    run_id: int
    command: str
    status: str
    started_at: datetime
    finished_at: datetime | None


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    database: str
    latest_run: RunSummary | None = None
    latest_success: RunSummary | None = None
