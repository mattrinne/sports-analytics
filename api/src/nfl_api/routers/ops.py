"""Run history from ops.runs / ops.run_steps."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ..db import Repo
from ..schemas import Run

router = APIRouter()


@router.get("/ops/runs", response_model=list[Run])
def latest_runs(repo: Repo, limit: Annotated[int, Query(ge=1, le=100)] = 10):
    return repo.latest_runs(limit)
