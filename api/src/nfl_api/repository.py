"""The only code that talks to Postgres. Routers see the Repository protocol; tests use an
in-memory fake. All SQL is schema-qualified and composed with psycopg.sql."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Protocol, TypeVar

import psycopg
from psycopg import sql
from psycopg_pool import ConnectionPool, PoolTimeout

from . import games_query
from .schemas import (
    Coach,
    CoachingTenure,
    Game,
    GameQuery,
    Health,
    MartModel,
    Referee,
    Run,
    RunStep,
    RunSummary,
    Stadium,
    Team,
)

M = TypeVar("M", bound=MartModel)


class Repository(Protocol):
    def list_teams(self) -> list[Team]: ...
    def get_team(self, team_id: int) -> Team | None: ...
    def list_coaches(self) -> list[Coach]: ...
    def get_coach(self, coach_id: int) -> Coach | None: ...
    def coach_tenures(self, coach_id: int) -> list[CoachingTenure]: ...
    def list_referees(self) -> list[Referee]: ...
    def get_referee(self, referee_id: int) -> Referee | None: ...
    def list_stadiums(self) -> list[Stadium]: ...
    def get_stadium(self, stadium_id: int) -> Stadium | None: ...
    def list_games(self, q: GameQuery) -> tuple[list[Game], int]: ...
    def get_game(self, game_id: int) -> Game | None: ...
    def latest_runs(self, limit: int) -> list[Run]: ...
    def health(self) -> Health: ...


_RUN_SUMMARY = sql.SQL(
    "SELECT run_id, command, status, started_at, finished_at FROM ops.runs {} "
    "ORDER BY run_id DESC LIMIT 1"
)


class PostgresRepository:
    def __init__(self, pool: ConnectionPool, connect_timeout: float = 5.0):
        self._pool = pool
        self._timeout = connect_timeout

    @contextmanager
    def _conn(self) -> Iterator[psycopg.Connection]:
        # One transaction per request (read-only role); commit on exit is a no-op for reads.
        with self._pool.connection(timeout=self._timeout) as conn:
            yield conn

    # -- dimensions --------------------------------------------------------------------------

    def _all(self, table: str, order_col: str, model: type[M]) -> list[M]:
        stmt = sql.SQL("SELECT * FROM {} ORDER BY {}").format(
            sql.Identifier("nfl", table), sql.Identifier(order_col)
        )
        with self._conn() as conn:
            return [model.model_validate(r) for r in conn.execute(stmt)]

    def _one(self, table: str, key_col: str, key: int, model: type[M]) -> M | None:
        stmt = sql.SQL("SELECT * FROM {} WHERE {} = %s").format(
            sql.Identifier("nfl", table), sql.Identifier(key_col)
        )
        with self._conn() as conn:
            row = conn.execute(stmt, (key,)).fetchone()
        return model.model_validate(row) if row else None

    def list_teams(self) -> list[Team]:
        return self._all("teams", "team_abbr", Team)

    def get_team(self, team_id: int) -> Team | None:
        return self._one("teams", "team_id", team_id, Team)

    def list_coaches(self) -> list[Coach]:
        return self._all("coaches", "coach_name", Coach)

    def get_coach(self, coach_id: int) -> Coach | None:
        return self._one("coaches", "coach_id", coach_id, Coach)

    def coach_tenures(self, coach_id: int) -> list[CoachingTenure]:
        stmt = sql.SQL(
            "SELECT * FROM nfl.coaching_tenures_detail WHERE coach_id = %s "
            "ORDER BY first_season, role_id, team_id"
        )
        with self._conn() as conn:
            return [CoachingTenure.model_validate(r) for r in conn.execute(stmt, (coach_id,))]

    def list_referees(self) -> list[Referee]:
        return self._all("referees", "referee_name", Referee)

    def get_referee(self, referee_id: int) -> Referee | None:
        return self._one("referees", "referee_id", referee_id, Referee)

    def list_stadiums(self) -> list[Stadium]:
        return self._all("stadiums", "stadium_name", Stadium)

    def get_stadium(self, stadium_id: int) -> Stadium | None:
        return self._one("stadiums", "stadium_id", stadium_id, Stadium)

    # -- games -------------------------------------------------------------------------------

    def list_games(self, q: GameQuery) -> tuple[list[Game], int]:
        page_stmt, page_params = games_query.games_page_query(q)
        count_stmt, count_params = games_query.games_count_query(q)
        with self._conn() as conn:  # both statements in one transaction: consistent total
            rows = conn.execute(page_stmt, page_params).fetchall()
            total = conn.execute(count_stmt, count_params).fetchone()["total"]
        return [Game.model_validate(r) for r in rows], total

    def get_game(self, game_id: int) -> Game | None:
        with self._conn() as conn:
            row = conn.execute(games_query.game_by_id_query(), {"game_id": game_id}).fetchone()
        return Game.model_validate(row) if row else None

    # -- ops ---------------------------------------------------------------------------------

    def latest_runs(self, limit: int) -> list[Run]:
        with self._conn() as conn:
            runs = conn.execute(
                "SELECT * FROM ops.runs ORDER BY run_id DESC LIMIT %s", (limit,)
            ).fetchall()
            ids = [r["run_id"] for r in runs]
            steps = conn.execute(
                "SELECT * FROM ops.run_steps WHERE run_id = ANY(%s) ORDER BY step_id", (ids,)
            ).fetchall() if ids else []
        by_run: dict[int, list[RunStep]] = {i: [] for i in ids}
        for s in steps:
            by_run[s["run_id"]].append(RunStep.model_validate(s))
        return [Run.model_validate({**r, "steps": by_run[r["run_id"]]}) for r in runs]

    def health(self) -> Health:
        try:
            with self._conn() as conn:
                conn.execute("SELECT 1")
                exists = conn.execute("SELECT to_regclass('ops.runs') IS NOT NULL").fetchone()
                if not exists or not next(iter(exists.values())):
                    return Health(status="ok", database="ok")  # fresh volume: pipeline not run yet
                latest = conn.execute(_RUN_SUMMARY.format(sql.SQL(""))).fetchone()
                success = conn.execute(
                    _RUN_SUMMARY.format(sql.SQL("WHERE status = 'success'"))
                ).fetchone()
        except (psycopg.OperationalError, PoolTimeout) as e:
            return Health(status="degraded", database=str(e).strip().splitlines()[0])
        return Health(
            status="ok",
            database="ok",
            latest_run=RunSummary.model_validate(latest) if latest else None,
            latest_success=RunSummary.model_validate(success) if success else None,
        )
