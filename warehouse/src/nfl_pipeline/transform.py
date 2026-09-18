"""Run `dbt build` on the project. dbt-postgres wants the connection as parts (dbt/profiles.yml
reads NFL_DB_*); derive them from NFL_DATABASE_URL so one secret serves both Python and dbt."""

from __future__ import annotations

import logging
import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .config import settings

log = logging.getLogger(__name__)


def dbt_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Environment for the dbt subprocess: NFL_DB_* filled in from NFL_DATABASE_URL when unset."""
    env = dict(os.environ if base is None else base)
    url = env.get("NFL_DATABASE_URL")
    if not url:
        return env
    parts = urlsplit(url)
    derived = {
        "NFL_DB_HOST": parts.hostname or "localhost",
        "NFL_DB_PORT": str(parts.port or 5432),
        "NFL_DB_NAME": parts.path.lstrip("/") or "nfl",
    }
    if parts.username:
        derived["NFL_DB_USER"] = unquote(parts.username)
    if parts.password:
        derived["NFL_DB_PASSWORD"] = unquote(parts.password)
    sslmode = parse_qs(parts.query).get("sslmode")
    if sslmode:
        derived["NFL_DB_SSLMODE"] = sslmode[0]
    for key, value in derived.items():
        env.setdefault(key, value)
    return env


def dbt_command(dbt_dir: Path, full_refresh: bool = False, extra: Sequence[str] = ()) -> list[str]:
    cmd = ["dbt", "build", "--project-dir", str(dbt_dir), "--profiles-dir", str(dbt_dir)]
    if full_refresh:
        cmd.append("--full-refresh")
    cmd.extend(extra)
    return cmd


def dbt_build(full_refresh: bool = False, extra: Sequence[str] = (), run=subprocess.run) -> int:
    """`dbt build` the whole project (or `extra` selection). Returns the dbt exit code."""
    cmd = dbt_command(settings().dbt_dir, full_refresh, extra)
    log.info("running: %s", " ".join(cmd))
    return run(cmd, env=dbt_env(), check=False).returncode
