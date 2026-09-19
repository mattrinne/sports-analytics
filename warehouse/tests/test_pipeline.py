from nfl_pipeline.ingest import SeasonUnavailable
from nfl_pipeline.pipeline import PipelineOptions, run_pipeline
from nfl_pipeline.runner import Step


class Recorder:
    def __init__(self):
        self.run_id = 7
        self.steps = []
        self.finished = None

    def record(self, step, season, status, **kw):
        self.steps.append((step, status))

    def record_step(self, result):
        self.steps.append((result.step.dataset, result.status))

    def finish(self, status, error=None):
        self.finished = (status, error)


class Harness:
    def __init__(self, outcomes, dbt_rc=0, truncate_error=None):
        self.outcomes = outcomes
        self.dbt_rc = dbt_rc
        self.truncate_error = truncate_error
        self.build_calls = []
        self.truncate_calls = []
        self.notified = []
        self.recorder = Recorder()

    def load(self, dataset, season):
        out = self.outcomes[dataset]
        if isinstance(out, BaseException):
            raise out
        return out

    def build(self, full_refresh=False):
        self.build_calls.append(full_refresh)
        return self.dbt_rc

    def truncate(self, datasets):
        self.truncate_calls.append(datasets)
        if self.truncate_error:
            raise self.truncate_error
        return ["teams"]

    def run(self, plan, **opts):
        return run_pipeline(
            "refresh", plan, season=2026, args={}, opts=PipelineOptions(retry_delay=0, **opts),
            load=self.load, build=self.build,
            truncate=self.truncate, recorder_factory=lambda *a: self.recorder,
            notify=lambda text: self.notified.append(text) or True,
        )


PLAN = [Step("teams", None), Step("participation", 2026)]


def test_success_runs_dbt_truncates_by_default_and_is_quiet():
    h = Harness({"teams": {"rows": 32}, "participation": {"rows": 1}})
    assert h.run(PLAN) == 0
    assert h.build_calls == [False]
    assert h.recorder.finished == ("success", None)
    assert ("dbt_build", "loaded") in h.recorder.steps
    assert ("truncate_staging", "loaded") in h.recorder.steps
    assert h.truncate_calls == [["teams", "participation"]]
    assert h.notified == []


def test_keep_staging_skips_truncate():
    h = Harness({"teams": {"rows": 32}, "participation": {"rows": 1}})
    assert h.run(PLAN, truncate_staging=False) == 0
    assert h.truncate_calls == []


def test_failed_step_skips_dbt_exits_one_and_notifies():
    h = Harness({"teams": ValueError("boom"), "participation": {"rows": 1}})
    assert h.run(PLAN) == 1
    assert h.build_calls == []
    assert h.recorder.finished[0] == "failed"
    assert len(h.notified) == 1 and "FAILED" in h.notified[0] and "ValueError" not in h.notified[0]
    assert "1 dataset step(s) failed" in h.notified[0]


def test_all_skipped_still_runs_dbt_but_truncates_nothing():
    h = Harness({"teams": SeasonUnavailable("x"), "participation": SeasonUnavailable("y")})
    assert h.run(PLAN) == 0
    assert h.build_calls == [False]
    assert h.truncate_calls == []


def test_truncate_only_covers_loaded_datasets():
    h = Harness({"teams": {"rows": 1}, "participation": SeasonUnavailable("later")})
    assert h.run(PLAN) == 0
    assert h.truncate_calls == [["teams"]]


def test_dbt_failure_exits_one_and_blocks_truncate():
    h = Harness({"teams": {"rows": 1}, "participation": {"rows": 1}}, dbt_rc=2)
    assert h.run(PLAN) == 1
    assert ("dbt_build", "failed") in h.recorder.steps
    assert h.truncate_calls == []
    assert h.recorder.finished == ("failed", "dbt build exited 2")


def test_truncate_after_success_and_full_refresh_passthrough():
    h = Harness({"teams": {"rows": 1}, "participation": {"rows": 1}})
    assert h.run(PLAN, full_refresh=True) == 0
    assert h.build_calls == [True]
    assert h.truncate_calls == [["teams", "participation"]]
    assert ("truncate_staging", "loaded") in h.recorder.steps


def test_skip_transform_never_truncates():
    h = Harness({"teams": {"rows": 1}, "participation": {"rows": 1}})
    assert h.run(PLAN, skip_transform=True) == 0
    assert h.build_calls == [] and h.truncate_calls == []


def test_notify_success_flag():
    h = Harness({"teams": {"rows": 1}, "participation": {"rows": 1}})
    assert h.run(PLAN, notify_success=True) == 0
    assert len(h.notified) == 1 and "SUCCESS" in h.notified[0]
