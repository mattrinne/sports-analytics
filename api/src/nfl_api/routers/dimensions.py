"""Dimension reads: complete lists (32-450 rows) and lookup by integer key."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from ..db import get_repository
from ..repository import Repository
from ..schemas import Coach, CoachingTenure, Referee, Stadium, Team

router = APIRouter()
Repo = Annotated[Repository, Depends(get_repository)]


def _or_404[T](row: T | None, what: str, key: int) -> T:
    if row is None:
        raise HTTPException(404, f"{what} {key} not found")
    return row


@router.get("/teams", response_model=list[Team])
def list_teams(repo: Repo):
    return repo.list_teams()


@router.get("/teams/{team_id}", response_model=Team)
def get_team(team_id: int, repo: Repo):
    return _or_404(repo.get_team(team_id), "team", team_id)


@router.get("/coaches", response_model=list[Coach])
def list_coaches(repo: Repo):
    return repo.list_coaches()


@router.get("/coaches/{coach_id}", response_model=Coach)
def get_coach(coach_id: int, repo: Repo):
    return _or_404(repo.get_coach(coach_id), "coach", coach_id)


@router.get("/coaches/{coach_id}/tenures", response_model=list[CoachingTenure])
def coach_tenures(coach_id: int, repo: Repo):
    _or_404(repo.get_coach(coach_id), "coach", coach_id)
    return repo.coach_tenures(coach_id)


@router.get("/referees", response_model=list[Referee])
def list_referees(repo: Repo):
    return repo.list_referees()


@router.get("/referees/{referee_id}", response_model=Referee)
def get_referee(referee_id: int, repo: Repo):
    return _or_404(repo.get_referee(referee_id), "referee", referee_id)


@router.get("/stadiums", response_model=list[Stadium])
def list_stadiums(repo: Repo):
    return repo.list_stadiums()


@router.get("/stadiums/{stadium_id}", response_model=Stadium)
def get_stadium(stadium_id: int, repo: Repo):
    return _or_404(repo.get_stadium(stadium_id), "stadium", stadium_id)
