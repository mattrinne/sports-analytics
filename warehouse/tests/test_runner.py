import threading

import pytest

from nfl_pipeline.ingest import SeasonUnavailable
from nfl_pipeline.runner import (
    Step,
    any_failed,
    backfill_plan,
    is_retryable,
    refresh_plan,
    run_plan,
    summarize,
)


class FakeLoader:
    """Scripted loader: outcomes[(dataset, season)] is a list consumed one attempt at a time."""

    def __init__(self, outcomes):
        self.outcomes = {k: list(v) for k, v in outcomes.items()}
        self.calls = []
        self.in_flight = {}
        self.max_in_flight = {}
        self.lock = threading.Lock()

    def __call__(self, dataset, season):
        with self.lock:
            self.calls.append((dataset, season))
            self.in_flight[dataset] = self.in_flight.get(dataset, 0) + 1
            self.max_in_flight[dataset] = max(self.max_in_flight.get(dataset, 0), self.in_flight[dataset])
        try:
            outcome = self.outcomes[(dataset, season)].pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        finally:
            with self.lock:
                self.in_flight[dataset] -= 1


def run(loader, plan, **kw):
    sleeps = []
    results = run_plan(plan, load=loader, sleep=sleeps.append, retry_delay=30.0, **kw)
    return results, sleeps


def test_success_and_skip_and_nonretryable_failure():
    loader = FakeLoader({
        ("teams", None): [{"rows": 32, "seconds": 1.5}],
        ("participation", 2026): [SeasonUnavailable("participation 2026: not yet")],
        ("pbp", 2026): [ValueError("bad column")],
    })
    results, sleeps = run(loader, [Step("teams", None), Step("participation", 2026), Step("pbp", 2026)])
    by = {r.step.dataset: r for r in results}
    assert by["teams"].status == "loaded" and by["teams"].rows == 32 and by["teams"].attempts == 1
    assert by["participation"].status == "skipped" and by["participation"].attempts == 1
    assert by["pbp"].status == "failed" and by["pbp"].attempts == 1
    assert by["pbp"].error.startswith("ValueError: bad column")
    assert sleeps == []
    assert any_failed(results)
    assert summarize(results) == {"loaded": 1, "skipped": 1, "failed": 1, "rows": 32}


def test_retry_then_success_with_exponential_backoff():
    loader = FakeLoader({("pbp", 2026): [ConnectionError("reset"), ConnectionError("reset"), {"rows": 5}]})
    results, sleeps = run(loader, [Step("pbp", 2026)])
    assert results[0].status == "loaded" and results[0].attempts == 3
    assert sleeps == [30.0, 60.0]


def test_retries_exhausted_marks_failed():
    loader = FakeLoader({("pbp", 2026): [ConnectionError("a"), ConnectionError("b"), ConnectionError("c")]})
    results, sleeps = run(loader, [Step("pbp", 2026)])
    assert results[0].status == "failed" and results[0].attempts == 3
    assert sleeps == [30.0, 60.0]
    assert not any_failed([]) and summarize([]) == {"loaded": 0, "skipped": 0, "failed": 0, "rows": 0}


def test_seasons_of_one_dataset_run_serially_and_in_order():
    seasons = list(range(2010, 2020))
    loader = FakeLoader({("rosters", s): [{"rows": 1}] for s in seasons} | {("teams", None): [{"rows": 1}]})
    plan = [Step("rosters", s) for s in seasons] + [Step("teams", None)]
    results, _ = run(loader, plan, workers=4)
    assert [r.step for r in results] == plan  # plan order preserved
    assert loader.max_in_flight["rosters"] == 1
    assert [s for d, s in loader.calls if d == "rosters"] == seasons


def test_on_result_called_per_step_and_workers_one_works():
    seen = []
    loader = FakeLoader({("teams", None): [{"rows": 1}], ("players", None): [{"rows": 2}]})
    run_plan([Step("teams", None), Step("players", None)], load=loader, on_result=seen.append, workers=1)
    assert sorted(r.step.dataset for r in seen) == ["players", "teams"]


def test_plans():
    plan = refresh_plan(2026, ["schedules", "pbp"])
    assert plan == [Step("schedules", None), Step("pbp", 2026)]
    plan = backfill_plan(2014, 2016, ["participation", "teams"])
    assert plan == [Step("participation", 2016), Step("teams", None)]  # clipped to min_season 2016
    assert len(refresh_plan(2026)) == 12
    with pytest.raises(KeyError):
        refresh_plan(2026, ["nope"])


def test_is_retryable():
    import psycopg

    assert is_retryable(ConnectionError("reset"))
    assert is_retryable(TimeoutError())
    assert is_retryable(psycopg.OperationalError("server closed the connection"))
    assert not is_retryable(PermissionError(13, "denied"))
    assert not is_retryable(FileNotFoundError())
    assert not is_retryable(ValueError("bad"))
    assert not is_retryable(psycopg.ProgrammingError("syntax"))
    assert not is_retryable(SeasonUnavailable("later"))
