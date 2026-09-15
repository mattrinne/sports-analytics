"""End-to-end load of one dataset (optionally one season) into the staging schema."""

from __future__ import annotations

import datetime as dt
import logging
import time

import polars as pl

from . import db
from .config import settings
from .datasets import REGISTRY, Dataset

log = logging.getLogger(__name__)


class SeasonUnavailable(Exception):
    """nflverse does not (yet) publish this dataset for the requested season.

    Some datasets lag a season behind (participation is published after the season ends), so the
    current season is a legitimate no-op rather than a failure.
    """


def fetch(dataset: Dataset, season: int | None = None) -> pl.DataFrame:
    if "." in dataset.loader:  # dotted path to a loader in this package (non-nflverse sources)
        import importlib

        mod_name, fn_name = dataset.loader.rsplit(".", 1)
        fn = getattr(importlib.import_module(mod_name), fn_name)
    else:
        import nflreadpy  # heavy import kept out of DAG parse path

        fn = getattr(nflreadpy, dataset.loader)
    kwargs = dict(dataset.loader_kwargs)
    if dataset.partitioned:
        if season is None:
            raise ValueError(f"{dataset.name} is partitioned by season; season is required")
        kwargs["seasons"] = season
    try:
        df = fn(**kwargs)
    except ValueError as exc:
        # nflreadpy validates the season range up front, e.g. "Season must be between 2016 and 2025"
        if "Season must be between" in str(exc):
            raise SeasonUnavailable(f"{dataset.name} {season}: {exc}") from exc
        raise
    return normalize(df)


def normalize(df: pl.DataFrame) -> pl.DataFrame:
    """Lowercase column names and stamp the load time."""
    df = df.rename({c: c.lower() for c in df.columns})
    return df.with_columns(
        pl.lit(dt.datetime.now(dt.UTC)).cast(pl.Datetime("us", "UTC")).alias("_loaded_at")
    )


def load_dataset(name: str, season: int | None = None) -> dict:
    """Fetch from nflverse and replace the matching rows in staging.<table>. Idempotent.

    Returns a small summary dict (safe to push as an Airflow XCom).
    """
    dataset = REGISTRY[name]
    cfg = settings()
    t0 = time.monotonic()
    df = fetch(dataset, season)
    if dataset.partitioned:
        if "season" not in df.columns:
            # Some newer nflverse files (e.g. 2025+ depth charts) drop the season column even
            # though the file itself is per-season. Stamp it so the partition key exists.
            df = df.with_columns(pl.lit(season, dtype=pl.Int64).alias("season"))
        # Defensive: a season file should only contain that season.
        df = df.filter(pl.col("season") == season)

    with db.connect() as conn:
        # Serialize loads of the same table (concurrent seasons in Airflow) so DDL, index creation
        # and the delete+COPY never deadlock. Different tables still load in parallel.
        db.lock_table(conn, cfg.staging_schema, dataset.table)
        db.ensure_schema(conn, cfg.staging_schema)
        db.ensure_table(conn, cfg.staging_schema, dataset.table, df)
        db.ensure_indexes(conn, cfg.staging_schema, dataset.table, dataset.indexes, dataset.unique)
        if dataset.partitioned:
            rows = db.replace_partition(
                conn, cfg.staging_schema, dataset.table, df, "season", season
            )
        else:
            rows = db.replace_all(conn, cfg.staging_schema, dataset.table, df)
        conn.commit()

    summary = {
        "dataset": name,
        "season": season,
        "table": f"{cfg.staging_schema}.{dataset.table}",
        "rows": rows,
        "columns": df.width,
        "seconds": round(time.monotonic() - t0, 1),
    }
    log.info("loaded %s", summary)
    return summary


def truncate_staging(datasets: list[str] | None = None) -> list[str]:
    """Empty staging tables to reclaim space. clean.* keeps the durable, upserted copy, so this is
    safe once dbt has run after the last load; the next load simply lands new partitions."""
    cfg = settings()
    tables = [REGISTRY[d].table for d in datasets] if datasets else None
    with db.connect() as conn:
        truncated = db.truncate_tables(conn, cfg.staging_schema, tables)
        conn.commit()
    log.info("truncated staging tables: %s", truncated)
    return truncated
