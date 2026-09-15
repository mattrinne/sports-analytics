"""Shared task definitions and group builder for the NFL DAGs.

Adding a dataset to `nfl_pipeline.datasets.REGISTRY` adds a TaskGroup to both DAGs automatically.
"""

from __future__ import annotations

import datetime as dt

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import TaskGroup, task
from airflow.sdk.exceptions import AirflowSkipException

from nfl_pipeline.config import settings
from nfl_pipeline.datasets import Dataset, seasons_for

DEFAULT_ARGS = {
    "owner": "nfl",
    "retries": 2,
    "retry_delay": dt.timedelta(minutes=10),
}
TAGS = ["nfl", "nflverse"]
# Cap concurrent downloads from the nflverse GitHub releases.
MAX_CONCURRENT_LOADS = 4


def _selected(params: dict, dataset: str) -> bool:
    wanted = params.get("datasets") or []
    return not wanted or dataset in wanted


@task(max_active_tis_per_dag=MAX_CONCURRENT_LOADS)
def load_season(dataset: str, season: int) -> dict:
    """Replace one season of one seasonal dataset in staging.<table>."""
    from nfl_pipeline.ingest import SeasonUnavailable, load_dataset

    try:
        return load_dataset(dataset, int(season))
    except SeasonUnavailable as exc:
        raise AirflowSkipException(str(exc)) from exc


@task(max_active_tis_per_dag=MAX_CONCURRENT_LOADS)
def load_full(dataset: str, **context) -> dict:
    """Fully replace a non-seasonal dataset (schedules, teams, players)."""
    if not _selected(context["params"], dataset):
        raise AirflowSkipException(f"{dataset} not in params.datasets")
    from nfl_pipeline.ingest import load_dataset

    return load_dataset(dataset)


@task
def plan_seasons(dataset: str, min_season: int, **context) -> list[int]:
    """Seasons this backfill run should load for a dataset, clipped to what nflverse publishes."""
    import nflreadpy

    params = context["params"]
    if not _selected(params, dataset):
        return []
    start = int(params["start_season"])
    end = int(params["end_season"] or nflreadpy.get_current_season())
    ds = Dataset(name=dataset, table=dataset, loader="", description="", min_season=min_season)
    return seasons_for(ds, start, end)


def dbt_build() -> BashOperator:
    """Upsert the clean layer and the nfl marts with dbt after every load group.

    Clean models are incremental merges by primary key, so a normal run only touches rows whose
    staging partition was reloaded. params.full_refresh drops and recreates every clean table (whole
    project, in dependency order, so foreign keys survive) — use it after a contract change or to
    drop rows nflverse deleted from a re-published season.
    """
    dbt_dir = settings().dbt_dir
    return BashOperator(
        task_id="dbt_build",
        bash_command=(
            f"dbt build --project-dir {dbt_dir} --profiles-dir {dbt_dir}"
            "{{ ' --full-refresh' if params.get('full_refresh') else '' }}"
        ),
        trigger_rule="none_failed",
    )


def backfill_group(ds: Dataset):
    """TaskGroup for a backfill: plan seasons -> one mapped load task per season."""
    with TaskGroup(group_id=ds.name, tooltip=ds.description) as group:
        if ds.partitioned:
            seasons = plan_seasons(dataset=ds.name, min_season=ds.min_season)
            load_season.partial(dataset=ds.name).expand(season=seasons)
        else:
            load_full(dataset=ds.name)
    return group


def refresh_group(ds: Dataset, season):
    """TaskGroup for the weekly refresh: load the current season (or full replace)."""
    with TaskGroup(group_id=ds.name, tooltip=ds.description) as group:
        if ds.partitioned:
            load_season(dataset=ds.name, season=season)
        else:
            load_full(dataset=ds.name)
    return group
