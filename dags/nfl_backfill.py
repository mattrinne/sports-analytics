"""Manual backfill: load a range of seasons for every (or selected) dataset, then rebuild clean/nfl with dbt.

Trigger from the UI with params. Re-running is idempotent: each (dataset, season) is a delete +
insert of that partition, and each is its own mapped task so one can be cleared and re-run alone.
"""

from __future__ import annotations

import pendulum
from airflow.sdk import Param, dag
from common import DEFAULT_ARGS, TAGS, backfill_group, dbt_build

from nfl_pipeline.config import settings
from nfl_pipeline.datasets import REGISTRY


@dag(
    dag_id="nfl_backfill",
    description="Backfill nflverse datasets into staging.* for a season range, then upsert clean.* and the nfl.* marts with dbt.",
    schedule=None,
    start_date=pendulum.datetime(2025, 1, 1, tz="America/Chicago"),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=TAGS,
    params={
        "start_season": Param(
            settings().start_season, type="integer", minimum=1920, title="First season"
        ),
        "end_season": Param(
            None, type=["null", "integer"], title="Last season (blank = current season)"
        ),
        "datasets": Param(
            [],
            type="array",
            items={"type": "string", "enum": sorted(REGISTRY)},
            title="Datasets (empty = all)",
        ),
        "full_refresh": Param(
            False, type="boolean", title="dbt --full-refresh (drop + recreate clean.*)"
        ),
    },
)
def nfl_backfill():
    dbt = dbt_build()
    for ds in REGISTRY.values():
        backfill_group(ds) >> dbt


nfl_backfill()
