"""Game reads over nfl.schedules: filtered, sorted, paginated list and lookup by game_id."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from ..db import Repo
from ..schemas import Game, GameQuery, Page

router = APIRouter()


@router.get("/games", response_model=Page[Game])
def list_games(q: Annotated[GameQuery, Query()], repo: Repo):
    items, total = repo.list_games(q)
    return Page(items=items, total=total, limit=q.limit, offset=q.offset)


@router.get("/games/{game_id}", response_model=Game)
def get_game(game_id: int, repo: Repo):
    game = repo.get_game(game_id)
    if game is None:
        raise HTTPException(404, f"game {game_id} not found")
    return game
