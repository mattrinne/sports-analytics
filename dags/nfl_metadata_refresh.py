"""Rebuild the metadata schema (data dictionary + column labels) for clean.*.

Manual trigger only. Reads the curated YAML under data/metadata/, downloads the nflverse data
dictionaries into memory (nothing is written to disk), introspects the live clean schema and
replaces metadata.tables / metadata.columns / metadata.labels. Independent of the load DAGs; run it
after adding a dataset, editing the label rules, or when a load reports new columns.
"""

from __future__ import annotations

import pendulum
from airflow.sdk import dag, task
from common import DEFAULT_ARGS, TAGS


@task
def build_metadata() -> dict:
    from nfl_pipeline.metadata import build_metadata as _build

    summary = _build()
    if summary["missing_description"] or summary["missing_category"]:
        import logging

        logging.getLogger(__name__).warning(
            "metadata has gaps: %s (run `nfl-pipeline metadata lint` for details)", summary
        )
    return summary


@dag(
    dag_id="nfl_metadata_refresh",
    description="Rebuild metadata.* (data dictionary + column labels) from clean.* and data/metadata/*.yaml.",
    schedule=None,
    start_date=pendulum.datetime(2025, 1, 1, tz="America/Chicago"),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=[*TAGS, "metadata"],
)
def nfl_metadata_refresh():
    build_metadata()


nfl_metadata_refresh()
