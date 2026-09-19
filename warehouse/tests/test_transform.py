from pathlib import Path

from nfl_pipeline.transform import dbt_command, dbt_env


def test_dbt_env_derives_parts_from_url():
    env = dbt_env({"NFL_DATABASE_URL": "postgresql://admin:p%40ss@nfl-pg.example.com:5432/nfl?sslmode=require"})
    assert env["NFL_DB_HOST"] == "nfl-pg.example.com"
    assert env["NFL_DB_PORT"] == "5432"
    assert env["NFL_DB_USER"] == "admin"
    assert env["NFL_DB_PASSWORD"] == "p@ss"
    assert env["NFL_DB_NAME"] == "nfl"
    assert env["NFL_DB_SSLMODE"] == "require"


def test_dbt_env_does_not_override_explicit_parts_or_missing_url():
    env = dbt_env({"NFL_DATABASE_URL": "postgresql://nfl:nfl@postgres/nfl", "NFL_DB_HOST": "override"})
    assert env["NFL_DB_HOST"] == "override" and env["NFL_DB_PORT"] == "5432"
    assert "NFL_DB_SSLMODE" not in env
    assert dbt_env({"OTHER": "1"}) == {"OTHER": "1"}


def test_dbt_command():
    base = ["dbt", "build", "--project-dir", "/x/dbt", "--profiles-dir", "/x/dbt"]
    assert dbt_command(Path("/x/dbt")) == base
    assert dbt_command(Path("/x/dbt"), full_refresh=True, extra=["--select", "teams"]) == [
        *base, "--full-refresh", "--select", "teams"]


def test_dbt_build_runs_command_with_dbt_env_and_returns_exit_code(monkeypatch):
    from types import SimpleNamespace

    from nfl_pipeline.transform import dbt_build

    monkeypatch.setenv("NFL_DATABASE_URL", "postgresql://nfl:nfl@db.example/nfl")
    calls = []

    def fake_run(cmd, env, check):
        calls.append((cmd, env, check))
        return SimpleNamespace(returncode=3)

    assert dbt_build(full_refresh=True, extra=["--select", "x"], run=fake_run) == 3
    (cmd, env, check), = calls
    assert cmd[:2] == ["dbt", "build"] and "--full-refresh" in cmd and cmd[-2:] == ["--select", "x"]
    assert env["NFL_DB_HOST"] == "db.example" and check is False
