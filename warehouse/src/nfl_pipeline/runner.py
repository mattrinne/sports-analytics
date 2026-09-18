"""Plan and execute dataset loads: bounded parallelism, retries, skip semantics.

One worker per dataset. A dataset's seasons run serially inside its worker so the per-table
advisory lock never contends and at most `workers` frames are in memory at once. Transient errors
(network, Postgres connection) are retried with exponential backoff; `SeasonUnavailable` is a
skip, not a failure. The loader and sleep are injectable so the runner is testable without a
database or network.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Literal

import psycopg

from . import ingest
from .datasets import REGISTRY, Dataset, seasons_for

log = logging.getLogger(__name__)

Status = Literal["loaded", "skipped", "failed"]
Loader = Callable[[str, int | None], dict]


@dataclass(frozen=True)
class Step:
    """One unit of work: a dataset, and a season for partitioned datasets."""

    dataset: str
    season: int | None


@dataclass
class StepResult:
    step: Step
    status: Status
    attempts: int
    rows: int | None = None
    seconds: float | None = None
    error: str | None = None


def _select(datasets: Sequence[str] | None) -> list[Dataset]:
    if not datasets:
        return list(REGISTRY.values())
    return [REGISTRY[name] for name in datasets]  # KeyError on an unknown name


def refresh_plan(season: int, datasets: Sequence[str] | None = None) -> list[Step]:
    """Current-season refresh: one step per dataset (full-replace datasets have no season)."""
    return [Step(d.name, season if d.partitioned else None) for d in _select(datasets)]


def backfill_plan(start: int, end: int, datasets: Sequence[str] | None = None) -> list[Step]:
    """One step per (dataset, season) in the range, clipped to each dataset's min_season."""
    plan: list[Step] = []
    for d in _select(datasets):
        if d.partitioned:
            plan.extend(Step(d.name, s) for s in seasons_for(d, start, end))
        else:
            plan.append(Step(d.name, None))
    return plan


_LOCAL_FS_ERRORS = (
    PermissionError, FileNotFoundError, FileExistsError, IsADirectoryError, NotADirectoryError
)


def is_retryable(exc: BaseException) -> bool:
    """Network hiccups (requests/urllib errors are OSErrors) and lost Postgres connections are worth
    a retry; bad data and local filesystem problems are not."""
    if isinstance(exc, _LOCAL_FS_ERRORS):
        return False
    return isinstance(exc, (OSError, psycopg.OperationalError))


def describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:2000]


def run_step(
    step: Step,
    *,
    retries: int,
    retry_delay: float,
    load: Loader,
    sleep: Callable[[float], None],
) -> StepResult:
    attempt = 0
    while True:
        attempt += 1
        try:
            summary = load(step.dataset, step.season)
            return StepResult(
                step, "loaded", attempt, rows=summary.get("rows"), seconds=summary.get("seconds")
            )
        except ingest.SeasonUnavailable as exc:
            log.info("skipped: %s", exc)
            return StepResult(step, "skipped", attempt, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - every failure becomes a recorded result
            if is_retryable(exc) and attempt <= retries:
                delay = retry_delay * 2 ** (attempt - 1)
                log.warning(
                    "%s %s failed (attempt %d/%d), retrying in %.0fs: %s",
                    step.dataset, step.season, attempt, retries + 1, delay, describe(exc),
                )
                sleep(delay)
                continue
            log.error("%s %s failed after %d attempt(s): %s",
                      step.dataset, step.season, attempt, describe(exc))
            return StepResult(step, "failed", attempt, error=describe(exc))


def run_plan(
    plan: Sequence[Step],
    *,
    workers: int = 4,
    retries: int = 2,
    retry_delay: float = 30.0,
    load: Loader | None = None,
    on_result: Callable[[StepResult], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[StepResult]:
    """Run every step; results come back in plan order. `on_result` is called from worker threads."""
    load = load or ingest.load_dataset
    groups: dict[str, list[Step]] = {}
    for step in plan:
        groups.setdefault(step.dataset, []).append(step)

    def run_group(steps: list[Step]) -> list[StepResult]:
        out = []
        for step in steps:
            result = run_step(step, retries=retries, retry_delay=retry_delay, load=load, sleep=sleep)
            if on_result is not None:
                on_result(result)
            out.append(result)
        return out

    results: list[StepResult] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for group_results in pool.map(run_group, groups.values()):
            results.extend(group_results)
    return results


def summarize(results: Sequence[StepResult]) -> dict:
    return {
        "loaded": sum(r.status == "loaded" for r in results),
        "skipped": sum(r.status == "skipped" for r in results),
        "failed": sum(r.status == "failed" for r in results),
        "rows": sum(r.rows or 0 for r in results),
    }


def any_failed(results: Sequence[StepResult]) -> bool:
    return any(r.status == "failed" for r in results)
