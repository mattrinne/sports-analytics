"""Optional webhook notification (Slack, Discord, ntfy…). Standard library only; never raises."""

from __future__ import annotations

import json
import logging
import os
import urllib.request

log = logging.getLogger(__name__)

ENV_VAR = "NFL_ALERT_WEBHOOK_URL"


def format_message(
    command: str, status: str, summary: dict, run_id: int | None, error: str | None = None
) -> str:
    head = f"nfl-pipeline {command} {status.upper()}"
    if run_id is not None:
        head += f" (run {run_id})"
    body = (
        f"loaded={summary.get('loaded', 0)} skipped={summary.get('skipped', 0)} "
        f"failed={summary.get('failed', 0)} rows={summary.get('rows', 0)} "
        f"seconds={summary.get('seconds', 0)}"
    )
    if error:
        body += f"\n{error[:500]}"
    return f"{head}\n{body}"


def notify(text: str, url: str | None = None, *, timeout: float = 5.0, opener=None) -> bool:
    """POST {"text", "content"} JSON to the webhook. Returns True when delivered."""
    url = url or os.environ.get(ENV_VAR)
    if not url:
        return False
    opener = opener or urllib.request.urlopen
    request = urllib.request.Request(
        url,
        data=json.dumps({"text": text, "content": text}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "nfl-pipeline"},
        method="POST",
    )
    try:
        response = opener(request, timeout=timeout)
        close = getattr(response, "close", None)
        if close:
            close()
        return True
    except Exception as exc:  # noqa: BLE001 - alerting must never fail the run
        log.warning("webhook notification failed: %s", exc)
        return False
