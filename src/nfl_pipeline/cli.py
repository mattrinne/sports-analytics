"""Command-line entry point: `uv run nfl-pipeline --help`."""

from __future__ import annotations

import logging

import typer

from .config import settings
from .datasets import REGISTRY, seasons_for

app = typer.Typer(
    no_args_is_help=True, help="Load nflverse data into the local Postgres warehouse."
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

    if dataset not in REGISTRY:
        raise typer.BadParameter(f"unknown dataset {dataset!r}; see `nfl-pipeline list`")
    summary = load_dataset(dataset, season)
    typer.echo(summary)


@app.command()
def backfill(
    start: int | None = typer.Option(None, help="First season; defaults to NFL_START_SEASON."),
    end: int | None = typer.Option(None, help="Last season; defaults to the current season."),
    datasets: list[str] | None = typer.Option(None, "--dataset", "-d", help="Subset of datasets."),
    skip_transform: bool = typer.Option(False, help="Do not run dbt afterwards."),
):
    """Load every dataset for a range of seasons, then rebuild clean/nfl with dbt. Safe to re-run."""
    import nflreadpy

    from .ingest import SeasonUnavailable, load_dataset

    start = start or settings().start_season
    end = end or nflreadpy.get_current_season()
    selected = [REGISTRY[n] for n in datasets] if datasets else list(REGISTRY.values())
    for d in selected:
        if d.partitioned:
            for season in seasons_for(d, start, end):
                try:
                    typer.echo(load_dataset(d.name, season))
                except SeasonUnavailable as exc:
                    typer.echo(f"skipped: {exc}", err=True)
        else:
            typer.echo(load_dataset(d.name))
    if not skip_transform:
        transform([])


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def transform(dbt_args: list[str] = typer.Argument(None, help="Extra args passed to `dbt build`.")):
    """Rebuild the clean and nfl layers: `dbt build` on the whole project (see dbt/README)."""
    import subprocess

    dbt_dir = settings().dbt_dir
    cmd = [
        "dbt",
        "build",
        "--project-dir",
        str(dbt_dir),
        "--profiles-dir",
        str(dbt_dir),
        *(dbt_args or []),
    ]
    typer.echo(" ".join(cmd), err=True)
    raise typer.Exit(subprocess.run(cmd, check=False).returncode)


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


metadata_app = typer.Typer(help="Data dictionary + column labels (metadata schema).")
app.add_typer(metadata_app, name="metadata")


@metadata_app.command("build")
def metadata_build():
    """Rebuild metadata.* from clean.* + data/metadata/*.yaml (nflverse dictionaries downloaded in memory)."""
    from .metadata import build_metadata

    typer.echo(build_metadata())


@metadata_app.command("lint")
def metadata_lint(
    show_warnings: bool = typer.Option(True, help="Print warnings (missing description/category)."),
):
    """Report unlabeled/undocumented columns and vocabulary errors. Exit 1 on errors."""
    from .metadata import lint_metadata

    errors, warnings = lint_metadata()
    if show_warnings:
        for w in warnings:
            typer.echo(f"warning: {w}")
    for e in errors:
        typer.echo(f"error: {e}", err=True)
    typer.echo(f"{len(errors)} errors, {len(warnings)} warnings")
    if errors:
        raise typer.Exit(1)


@app.command()
def current_season():
    """Print the season nflverse considers current."""
    import nflreadpy

    typer.echo(f"{nflreadpy.get_current_season()} week {nflreadpy.get_current_week()}")


if __name__ == "__main__":
    app()
