"""Command-line entry point: `uv run nfl-pipeline --help`."""

from __future__ import annotations

import logging

import typer

from .config import settings
from .datasets import REGISTRY

app = typer.Typer(
    no_args_is_help=True, help="Load nflverse data into the Postgres warehouse and transform it with dbt."
)


@app.callback()
def _setup(verbose: bool = typer.Option(False, "--verbose", "-v")):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@app.command("list")
def list_datasets():
    """Show registered datasets."""
    for d in REGISTRY.values():
        mode = f"by season (>= {d.min_season})" if d.partitioned else "full replace"
        typer.echo(f"{d.name:20s} staging.{d.table:20s} {mode:22s} {d.description}")


@app.command()
def load(
    dataset: str = typer.Argument(..., help="Dataset name from `list`."),
    season: int | None = typer.Option(
        None, help="Season to load (required for seasonal datasets)."
    ),
):
    """Load one dataset (one season for seasonal datasets)."""
    from .ingest import load_dataset

    _check_datasets([dataset])
    summary = load_dataset(dataset, season)
    typer.echo(summary)


def _check_datasets(datasets: list[str] | None) -> list[str] | None:
    unknown = [d for d in datasets or [] if d not in REGISTRY]
    if unknown:
        raise typer.BadParameter(f"unknown dataset(s) {unknown}; see `nfl-pipeline list`")
    return datasets or None


def _run(command: str, plan, *, season: int | None, args: dict, **options) -> None:
    from .pipeline import PipelineOptions, run_pipeline

    opts = PipelineOptions(**options)
    raise typer.Exit(run_pipeline(command, plan, season=season, args=args, opts=opts))


_DATASETS = typer.Option(None, "--dataset", "-d", help="Subset of datasets (default: all).")
_WORKERS = typer.Option(4, help="Datasets loaded concurrently (seasons of one dataset run serially).")
_RETRIES = typer.Option(2, help="Retries per step on network / connection errors.")
_RETRY_DELAY = typer.Option(30.0, help="Seconds before the first retry; doubles each retry.")
_SKIP_TRANSFORM = typer.Option(False, help="Do not run dbt afterwards.")
_FULL_REFRESH = typer.Option(False, help="dbt --full-refresh (drop + recreate incremental models).")
_TRUNCATE = typer.Option(
    True,
    "--truncate-staging/--keep-staging",
    help="TRUNCATE the loaded staging tables after a successful dbt build (default). "
    "--keep-staging leaves them, e.g. before a standalone `transform --full-refresh`.",
)
_NOTIFY_SUCCESS = typer.Option(
    False, help="Also send the webhook (NFL_ALERT_WEBHOOK_URL) on success, not only on failure."
)


@app.command()
def refresh(
    datasets: list[str] | None = _DATASETS,
    workers: int = _WORKERS,
    retries: int = _RETRIES,
    retry_delay: float = _RETRY_DELAY,
    skip_transform: bool = _SKIP_TRANSFORM,
    full_refresh: bool = _FULL_REFRESH,
    truncate_staging: bool = _TRUNCATE,
    notify_success: bool = _NOTIFY_SUCCESS,
):
    """Load the current season of every dataset, dbt build, truncate staging. The scheduled job.

    Exit 0 when every step loaded or was skipped (dataset not yet published) and dbt passed;
    exit 1 otherwise. Every run is recorded in ops.runs / ops.run_steps.
    """
    import nflreadpy

    from .runner import refresh_plan

    datasets = _check_datasets(datasets)
    season = int(nflreadpy.get_current_season())
    _run(
        "refresh",
        refresh_plan(season, datasets),
        season=season,
        args={"datasets": datasets, "full_refresh": full_refresh, "truncate_staging": truncate_staging},
        workers=workers,
        retries=retries,
        retry_delay=retry_delay,
        skip_transform=skip_transform,
        full_refresh=full_refresh,
        truncate_staging=truncate_staging,
        notify_success=notify_success,
    )


@app.command()
def backfill(
    start: int | None = typer.Option(None, help="First season; defaults to NFL_START_SEASON."),
    end: int | None = typer.Option(None, help="Last season; defaults to the current season."),
    datasets: list[str] | None = _DATASETS,
    workers: int = _WORKERS,
    retries: int = _RETRIES,
    retry_delay: float = _RETRY_DELAY,
    skip_transform: bool = _SKIP_TRANSFORM,
    full_refresh: bool = _FULL_REFRESH,
    truncate_staging: bool = _TRUNCATE,
    notify_success: bool = _NOTIFY_SUCCESS,
):
    """Load every dataset for a range of seasons, dbt build, truncate staging. Safe to re-run."""
    import nflreadpy

    from .runner import backfill_plan

    datasets = _check_datasets(datasets)
    start = start or settings().start_season
    end = end or int(nflreadpy.get_current_season())
    _run(
        "backfill",
        backfill_plan(start, end, datasets),
        season=end,
        args={"start": start, "end": end, "datasets": datasets, "full_refresh": full_refresh},
        workers=workers,
        retries=retries,
        retry_delay=retry_delay,
        skip_transform=skip_transform,
        full_refresh=full_refresh,
        truncate_staging=truncate_staging,
        notify_success=notify_success,
    )


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def transform(dbt_args: list[str] = typer.Argument(None, help="Extra args passed to `dbt build`.")):
    """Rebuild the clean and nfl layers: `dbt build` on the whole project (see README.md, "Clean layer")."""
    from .transform import dbt_build

    raise typer.Exit(dbt_build(extra=dbt_args or []))


staging_app = typer.Typer(help="Landing-zone maintenance (staging schema).")
app.add_typer(staging_app, name="staging")


@staging_app.command("truncate")
def staging_truncate(
    datasets: list[str] | None = typer.Option(None, "--dataset", "-d", help="Subset of datasets."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
):
    """TRUNCATE staging tables to reclaim space. Run `transform` first so clean.* has everything."""
    from .ingest import truncate_staging

    if not yes:
        typer.confirm("Truncate staging tables? (clean.* is unaffected)", abort=True)
    typer.echo(truncate_staging(datasets))


@app.command()
def current_season():
    """Print the season nflverse considers current."""
    import nflreadpy

    typer.echo(f"{nflreadpy.get_current_season()} week {nflreadpy.get_current_week()}")


if __name__ == "__main__":
    app()
