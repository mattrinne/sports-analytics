import os

import psycopg
import pytest

from nfl_pipeline.runner import Step, StepResult
from nfl_pipeline.runs import DDL, NullRecorder, RunRecorder


class FakeCursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class FakeConn:
    def __init__(self, fail=False):
        self.executed = []
        self.closed = False
        self.fail = fail

    def execute(self, sql, params=None):
        if self.fail:
            raise psycopg.OperationalError("down")
        self.executed.append((sql, params))
        return FakeCursor((42,))

    def close(self):
        self.closed = True


def test_start_creates_schema_and_run_row():
    conn = FakeConn()
    rec = RunRecorder.start("refresh", 2026, {"datasets": None}, connect=lambda: conn)
    assert isinstance(rec, RunRecorder) and rec.run_id == 42
    ddl = [sql for sql, _ in conn.executed[: len(DDL)]]
    assert all("IF NOT EXISTS" in s for s in ddl)
    insert_sql, params = conn.executed[len(DDL)]
    assert "INSERT INTO ops.runs" in insert_sql and params[0] == "refresh" and params[1] == 2026


def test_record_and_finish():
    conn = FakeConn()
    rec = RunRecorder.start("refresh", 2026, {}, connect=lambda: conn)
    rec.record_step(StepResult(Step("pbp", 2026), "failed", 3, error="ConnectionError: x"))
    rec.record("dbt_build", None, "loaded", seconds=12.5)
    rec.finish("failed", "dbt build exited 1")
    inserts = [p for s, p in conn.executed if "INSERT INTO ops.run_steps" in s]
    assert inserts[0] == (42, "pbp", 2026, "failed", 3, None, None, "ConnectionError: x")
    assert inserts[1] == (42, "dbt_build", None, "loaded", 1, None, 12.5, None)
    update_sql, params = conn.executed[-1]
    assert "UPDATE ops.runs" in update_sql and params == ("failed", "dbt build exited 1", 42)
    assert conn.closed


def test_unavailable_database_falls_back_to_null_recorder():
    rec = RunRecorder.start("refresh", 2026, {}, connect=lambda: FakeConn(fail=True))
    assert isinstance(rec, NullRecorder) and rec.run_id is None
    rec.record("x", None, "loaded")
    rec.finish("success")


def test_record_error_is_swallowed():
    conn = FakeConn()
    rec = RunRecorder.start("refresh", 2026, {}, connect=lambda: conn)
    conn.fail = True
    rec.record("teams", None, "loaded")  # must not raise
    rec.finish("success")


@pytest.mark.skipif(not os.environ.get("NFL_TEST_DATABASE_URL"), reason="needs NFL_TEST_DATABASE_URL")
def test_integration_round_trip():
    url = os.environ["NFL_TEST_DATABASE_URL"]
    rec = RunRecorder.start("test", 2026, {"k": 1}, connect=lambda: psycopg.connect(url, autocommit=True))
    rec.record("teams", None, "loaded", rows=32, seconds=0.1)
    rec.finish("success")
    with psycopg.connect(url) as conn:
        status = conn.execute("select status from ops.runs where run_id = %s", (rec.run_id,)).fetchone()[0]
        steps = conn.execute("select count(*) from ops.run_steps where run_id = %s", (rec.run_id,)).fetchone()[0]
        conn.execute("delete from ops.runs where run_id = %s", (rec.run_id,))
        conn.commit()
    assert status == "success" and steps == 1
