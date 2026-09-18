from typer.testing import CliRunner

from nfl_pipeline import cli

runner = CliRunner()


def test_refresh_help():
    result = runner.invoke(cli.app, ["refresh", "--help"])
    assert result.exit_code == 0 and "--truncate-staging" in result.output


def test_unknown_dataset_is_a_usage_error():
    result = runner.invoke(cli.app, ["refresh", "-d", "nope"])
    assert result.exit_code == 2 and "unknown dataset" in result.output


def test_refresh_exit_code_comes_from_pipeline(monkeypatch):
    from nfl_pipeline import pipeline

    captured = {}

    def fake_run_pipeline(command, plan, **kw):
        captured.update(command=command, plan=plan, opts=kw["opts"], season=kw["season"])
        return 1

    monkeypatch.setattr(pipeline, "run_pipeline", fake_run_pipeline)
    result = runner.invoke(cli.app, ["refresh", "-d", "teams", "-d", "pbp", "--workers", "2", "--keep-staging"])
    assert result.exit_code == 1
    assert captured["command"] == "refresh"
    assert [s.dataset for s in captured["plan"]] == ["teams", "pbp"]
    assert captured["plan"][1].season == captured["season"]
    assert captured["opts"].workers == 2 and captured["opts"].truncate_staging is False


def test_truncate_is_the_default(monkeypatch):
    from nfl_pipeline import pipeline

    captured = {}
    monkeypatch.setattr(pipeline, "run_pipeline", lambda c, plan, **kw: captured.update(opts=kw["opts"]) or 0)
    assert runner.invoke(cli.app, ["refresh", "-d", "teams"]).exit_code == 0
    assert captured["opts"].truncate_staging is True


def test_backfill_plan_range(monkeypatch):
    from nfl_pipeline import pipeline

    captured = {}
    monkeypatch.setattr(pipeline, "run_pipeline", lambda c, plan, **kw: captured.update(plan=plan) or 0)
    result = runner.invoke(cli.app, ["backfill", "--start", "2015", "--end", "2016", "-d", "participation", "-d", "teams"])
    assert result.exit_code == 0
    assert [(s.dataset, s.season) for s in captured["plan"]] == [("participation", 2016), ("teams", None)]
