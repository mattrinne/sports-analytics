"""Run history from ops.runs / ops.run_steps."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ..db import get_repository
from ..repository import Repository
from ..schemas import Run

router = APIRouter()
Repo = Annotated[Repository, Depends(get_repository)]


@router.get("/ops/runs", response_model=list[Run])
def latest_runs(repo: Repo, limit: Annotated[int, Query(ge=1, le=100)] = 10):
    return repo.latest_runs(limit)
