import json

from nfl_pipeline.alerts import format_message, notify


class Opener:
    def __init__(self, error=None):
        self.requests = []
        self.error = error

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        if self.error:
            raise self.error
        return object()


def test_posts_json_with_both_keys():
    opener = Opener()
    assert notify("hello", "https://example.test/hook", opener=opener) is True
    request, timeout = opener.requests[0]
    assert request.full_url == "https://example.test/hook" and request.get_method() == "POST"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data) == {"text": "hello", "content": "hello"}
    assert timeout == 5.0


def test_no_url_is_a_noop(monkeypatch):
    monkeypatch.delenv("NFL_ALERT_WEBHOOK_URL", raising=False)
    opener = Opener()
    assert notify("hello", opener=opener) is False
    assert opener.requests == []


def test_env_url_used_and_errors_swallowed(monkeypatch):
    monkeypatch.setenv("NFL_ALERT_WEBHOOK_URL", "https://example.test/env")
    opener = Opener(error=OSError("unreachable"))
    assert notify("hello", opener=opener) is False
    assert opener.requests[0][0].full_url == "https://example.test/env"


def test_format_message():
    msg = format_message("refresh", "failed", {"loaded": 3, "skipped": 1, "failed": 2, "rows": 10, "seconds": 9},
                         run_id=5, error="dbt build exited 1")
    assert msg.splitlines()[0] == "nfl-pipeline refresh FAILED (run 5)"
    assert "loaded=3 skipped=1 failed=2 rows=10 seconds=9" in msg and msg.endswith("dbt build exited 1")
    assert format_message("refresh", "success", {}, None).startswith("nfl-pipeline refresh SUCCESS\n")
