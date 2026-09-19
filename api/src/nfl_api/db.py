"""Connection pool and the request-scoped repository dependency."""

from __future__ import annotations

from typing import Annotated

import psycopg
from fastapi import Depends, Request
from psycopg import IsolationLevel
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import Settings
from .repository import Repository


def _configure(conn: psycopg.Connection) -> None:
    # One snapshot per request: under READ COMMITTED each statement would see its own, so a
    # /games page and its count(*) could disagree if a dbt merge committed in between.
    conn.isolation_level = IsolationLevel.REPEATABLE_READ


def make_pool(s: Settings) -> ConnectionPool:
    """Closed pool; the app's lifespan opens it with wait=False so a slow Postgres does not stop
    the API from starting (/health reports the problem instead)."""
    return ConnectionPool(
        s.database_url,
        min_size=s.pool_min,
        max_size=s.pool_max,
        open=False,
        kwargs={"row_factory": dict_row},
        configure=_configure,
        check=ConnectionPool.check_connection,
        name="nfl-api",
    )


def get_repository(request: Request) -> Repository:
    return request.app.state.repository


Repo = Annotated[Repository, Depends(get_repository)]
