"""The whole job: load steps → dbt build (only if nothing failed) → truncate the staging tables
that were loaded (default),
recorded in ops.runs and reported through the webhook. `refresh` and `backfill` both run this."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from . import alerts, ingest, transform
from .runner import Loader, Step, any_failed, describe, run_plan, summarize
from .runs import NullRecorder, RunRecorder

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineOptions:
    workers: int = 4
    retries: int = 2
    retry_delay: float = 30.0
    skip_transform: bool = False
    full_refresh: bool = False
    truncate_staging: bool = True  # staging is a landing zone; clean.* is the durable copy
    notify_success: bool = False


def run_pipeline(
    command: str,
    plan: Sequence[Step],
    *,
    season: int | None,
    args: dict,
    opts: PipelineOptions,
    load: Loader | None = None,
    build: Callable[..., int] | None = None,
    truncate: Callable[[list[str] | None], list[str]] | None = None,
    recorder_factory: Callable[..., NullRecorder] | None = None,
    notify: Callable[[str], bool] | None = None,
) -> int:
    """Returns the process exit code: 0 on success, 1 if any step, dbt or the truncate failed."""
    build = build or transform.dbt_build
    truncate = truncate or ingest.truncate_staging
    recorder_factory = recorder_factory or RunRecorder.start
    notify = notify or alerts.notify

    t0 = time.monotonic()
    recorder = recorder_factory(command, season, args)
    log.info("%s started: %d step(s), %d worker(s), run_id=%s",
             command, len(plan), opts.workers, recorder.run_id)

    results = run_plan(
        plan,
        workers=opts.workers,
        retries=opts.retries,
        retry_delay=opts.retry_delay,
        load=load,
        on_result=recorder.record_step,
    )
    summary = summarize(results)
    status, error, dbt_status = "success", None, "skipped"

    if any_failed(results):
        status = "failed"
        error = f"{summary['failed']} dataset step(s) failed; dbt not run"
        dbt_status = "not run"
    elif not opts.skip_transform:
        t1 = time.monotonic()
        rc = build(full_refresh=opts.full_refresh)
        seconds = round(time.monotonic() - t1, 1)
        if rc == 0:
            dbt_status = "ok"
            recorder.record("dbt_build", None, "loaded", seconds=seconds)
        else:
            status, error, dbt_status = "failed", f"dbt build exited {rc}", f"exit {rc}"
            recorder.record("dbt_build", None, "failed", seconds=seconds, error=error)

    if opts.truncate_staging:
        loaded = [r.step.dataset for r in results if r.status == "loaded"]
        loaded = list(dict.fromkeys(loaded))  # one entry per dataset, plan order
        if dbt_status != "ok":
            log.warning("staging not truncated: dbt did not run successfully")
        elif not loaded:
            log.info("staging not truncated: nothing was loaded")
        else:
            try:
                truncated = truncate(loaded)
                recorder.record("truncate_staging", None, "loaded", rows=len(truncated))
            except Exception as exc:  # noqa: BLE001
                status, error = "failed", describe(exc)
                recorder.record("truncate_staging", None, "failed", error=error)

    recorder.finish(status, error)
    summary["seconds"] = round(time.monotonic() - t0, 1)
    log.info(
        "%s finished run_id=%s status=%s loaded=%d skipped=%d failed=%d dbt=%s seconds=%.0f",
        command, recorder.run_id, status, summary["loaded"], summary["skipped"],
        summary["failed"], dbt_status, summary["seconds"],
    )
    if status == "failed" or opts.notify_success:
        notify(alerts.format_message(command, status, summary, recorder.run_id, error))
    return 0 if status == "success" else 1
