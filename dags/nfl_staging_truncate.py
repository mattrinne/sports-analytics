"""Manual: empty the staging (landing) tables to reclaim disk space.

staging.* is only a landing zone: every load is upserted into clean.* by the dbt_build task at
the end of nfl_backfill / nfl_weekly_refresh, so once those have run the staging copy is
redundant. Trigger this whenever the Postgres volume grows; the next load recreates the
partitions it needs. Optionally restrict to some datasets via params.
"""

from __future__ import annotations

import pendulum
from airflow.sdk import Param, dag, task
from common import DEFAULT_ARGS, TAGS

from nfl_pipeline.datasets import REGISTRY


@task
def truncate(**context) -> list[str]:
    from nfl_pipeline.ingest import truncate_staging

    return truncate_staging(context["params"].get("datasets") or None)


@dag(
    dag_id="nfl_staging_truncate",
    description="TRUNCATE staging.* (landing zone) to reclaim space; clean.* keeps the data.",
    schedule=None,
    start_date=pendulum.datetime(2025, 1, 1, tz="America/Chicago"),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=[*TAGS, "maintenance"],
    params={
        "datasets": Param(
            [],
            type="array",
            items={"type": "string", "enum": sorted(REGISTRY)},
            title="Datasets (empty = all)",
        ),
    },
)
def nfl_staging_truncate():
    truncate()


nfl_staging_truncate()
