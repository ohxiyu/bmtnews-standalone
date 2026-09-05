import io
import json
from urllib.error import HTTPError, URLError
from unittest.mock import Mock

import pytest

from src import schedule_watchdog as watchdog


def response(status, state):
    body = io.BytesIO(json.dumps({"status": state}).encode())
    body.code = status
    return body


@pytest.mark.parametrize("code,state,success,expected", [
    (200, "healthy", False, 0),
    (200, "not_due", False, 0),
    (200, "daily_dispatched", False, 1),
    (202, "daily_dispatched", True, 0),
    (202, "publication_active", False, 1),
    (503, "daily_retry_limit", True, 1),
    (503, "publication_stuck", True, 1),
])
def test_shared_coordinator(monkeypatch, code, state, success, expected):
    monkeypatch.setenv("RECOVERY_CHECK_TOKEN", "test-secret")
    opener = Mock(return_value=response(code, state))
    monkeypatch.setattr(watchdog, "urlopen", opener)
    direct = Mock()
    monkeypatch.setattr(watchdog, "dispatch_workflow", direct)
    args = ["--coordinator"] + (["--success-on-recovery"] if success else [])
    assert watchdog.main(args) == expected
    request = opener.call_args.args[0]
    assert request.method == "POST"
    assert request.get_header("Authorization") == "Bearer test-secret"
    assert "test-secret" not in request.full_url
    direct.assert_not_called()


@pytest.mark.parametrize("error", [
    URLError("unreachable"),
    HTTPError("https://example.test", 401, "Unauthorized", {}, io.BytesIO()),
    HTTPError("https://example.test", 503, "Unavailable", {},
              io.BytesIO(b'{"status":"check_failed"}')),
])
def test_coordinator_errors_never_fall_back_to_duplicate_dispatch(monkeypatch, error, capsys):
    monkeypatch.setenv("RECOVERY_CHECK_TOKEN", "test-secret")
    monkeypatch.setattr(watchdog, "urlopen", Mock(side_effect=error))
    direct = Mock()
    monkeypatch.setattr(watchdog, "dispatch_workflow", direct)
    assert watchdog.main(["--coordinator", "--success-on-recovery"]) == 1
    direct.assert_not_called()
    assert "test-secret" not in capsys.readouterr().out


def test_missing_coordinator_secret_is_fail_closed(monkeypatch):
    monkeypatch.delenv("RECOVERY_CHECK_TOKEN", raising=False)
    opener = Mock()
    monkeypatch.setattr(watchdog, "urlopen", opener)
    assert watchdog.main(["--coordinator"]) == 1
    opener.assert_not_called()
