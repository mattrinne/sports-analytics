"""Weekly refresh of the current season.

Runs Tuesday and Wednesday mornings (America/Chicago). Tuesday picks up Monday night's game once
nflverse has processed it; Wednesday catches stat corrections. nflverse updates pbp/stats nightly
during the season. Off-season runs are cheap no-ops that re-replace the current season's files.
"""

from __future__ import annotations

import pendulum
from airflow.sdk import Param, dag, task
from common import DEFAULT_ARGS, TAGS, dbt_build, refresh_group

from nfl_pipeline.datasets import REGISTRY


@task
def current_season() -> int:
    import nflreadpy

    return int(nflreadpy.get_current_season())


@dag(
    dag_id="nfl_weekly_refresh",
    description="Reload the current season of every nflverse dataset into staging, then upsert clean.* and rebuild nfl.* with dbt.",
    schedule="0 8 * * 2,3",
    start_date=pendulum.datetime(2025, 1, 1, tz="America/Chicago"),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=TAGS,
    params={
        "datasets": [],
        "full_refresh": Param(
            False, type="boolean", title="dbt --full-refresh (drop + recreate clean.*)"
        ),
    },
)
def nfl_weekly_refresh():
    season = current_season()
    dbt = dbt_build()
    for ds in REGISTRY.values():
        refresh_group(ds, season) >> dbt


nfl_weekly_refresh()
