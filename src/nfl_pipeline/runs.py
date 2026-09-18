"""Run history in the `ops` schema: one row per pipeline run, one per step.

Replaces the orchestrator UI as the place to see what happened. Best-effort by design: if `ops`
cannot be written the run still proceeds and the problem is logged. The recorder holds its own
autocommit connection, so `running` rows are visible while loads are in flight.
"""

from __future__ import annotations

import logging
import socket
import threading
from collections.abc import Callable

import psycopg
from psycopg.types.json import Jsonb

from .config import settings
from .runner import StepResult

log = logging.getLogger(__name__)

SCHEMA = "ops"

DDL = (
    f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}",
    f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.runs (
        run_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        command     text        NOT NULL,
        status      text        NOT NULL,
        season      integer,
        args        jsonb       NOT NULL DEFAULT '{{}}',
        hostname    text,
        started_at  timestamptz NOT NULL DEFAULT now(),
        finished_at timestamptz,
        error       text
    )""",
    f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.run_steps (
        step_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        run_id      bigint      NOT NULL REFERENCES {SCHEMA}.runs (run_id) ON DELETE CASCADE,
        step        text        NOT NULL,
        season      integer,
        status      text        NOT NULL,
        attempts    smallint    NOT NULL DEFAULT 1,
        rows        bigint,
        seconds     double precision,
        finished_at timestamptz NOT NULL DEFAULT now(),
        error       text
    )""",
    f"CREATE INDEX IF NOT EXISTS ix_runs_started_at ON {SCHEMA}.runs (started_at DESC)",
    f"CREATE INDEX IF NOT EXISTS ix_run_steps_run_id ON {SCHEMA}.run_steps (run_id)",
)


def _connect() -> psycopg.Connection:
    return psycopg.connect(settings().database_url, autocommit=True)


class NullRecorder:
    """Stands in when run history is unavailable; every call is a no-op."""

    run_id: int | None = None

    def record(self, step: str, season: int | None, status: str, **_: object) -> None:
        return None

    def record_step(self, result: StepResult) -> None:
        return None

    def finish(self, status: str, error: str | None = None) -> None:
        return None


class RunRecorder(NullRecorder):
    def __init__(self, conn: psycopg.Connection, run_id: int):
        self._conn = conn
        self._lock = threading.Lock()
        self.run_id = run_id

    @classmethod
    def start(
        cls,
        command: str,
        season: int | None,
        args: dict,
        connect: Callable[[], psycopg.Connection] = _connect,
    ) -> NullRecorder:
        try:
            conn = connect()
            for statement in DDL:
                conn.execute(statement)
            row = conn.execute(
                f"INSERT INTO {SCHEMA}.runs (command, status, season, args, hostname) "
                "VALUES (%s, 'running', %s, %s, %s) RETURNING run_id",
                (command, season, Jsonb(args), socket.gethostname()),
            ).fetchone()
            return cls(conn, int(row[0]))
        except Exception as exc:  # noqa: BLE001 - history must never block a load
            log.error("run history unavailable, continuing without it: %s", exc)
            return NullRecorder()

    def record(
        self,
        step: str,
        season: int | None,
        status: str,
        *,
        attempts: int = 1,
        rows: int | None = None,
        seconds: float | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    f"INSERT INTO {SCHEMA}.run_steps "
                    "(run_id, step, season, status, attempts, rows, seconds, error) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (self.run_id, step, season, status, attempts, rows, seconds, error),
                )
            except Exception as exc:  # noqa: BLE001
                log.error("could not record step %s: %s", step, exc)

    def record_step(self, result: StepResult) -> None:
        self.record(
            result.step.dataset,
            result.step.season,
            result.status,
            attempts=result.attempts,
            rows=result.rows,
            seconds=result.seconds,
            error=result.error,
        )

    def finish(self, status: str, error: str | None = None) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    f"UPDATE {SCHEMA}.runs SET status = %s, finished_at = now(), error = %s "
                    "WHERE run_id = %s",
                    (status, error, self.run_id),
                )
                self._conn.close()
            except Exception as exc:  # noqa: BLE001
                log.error("could not finish run %s: %s", self.run_id, exc)
