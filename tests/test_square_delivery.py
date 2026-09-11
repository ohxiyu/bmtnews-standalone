import copy
import json
import subprocess
from datetime import datetime

import httpx
import pytest

from src.square_delivery import SHANGHAI, compose, distribute, git_checkpoint, read_state, send, story_key


def edition(count=14):
    return {"date": "2026-09-11", "items": [
        {"rank": i + 1, "url": f"https://example.com/{i}", "title": {"zh": f"新闻{i}"},
         "summary": {"zh": "已确认的事件。\n\n背景与影响，尚未批准。"}} for i in range(count)]}


def run(payload, state, hour=9, checkpoint=None, handler=None):
    with httpx.Client(transport=httpx.MockTransport(handler or (lambda r: httpx.Response(200,
            json={"code": "000000", "data": {"id": "123"}})))) as client:
        return distribute(payload, state, now=datetime(2026, 9, 11, hour, 17, tzinfo=SHANGHAI),
            client=client, key="test-secret", checkpoint=checkpoint or (lambda s: None))


def test_full_day_covers_every_selected_story_once():
    state = {"version": 1, "editions": {}}
    sent = []
    def handler(request):
        assert request.url.host == "www.binance.com"
        assert request.headers["X-Square-OpenAPI-Key"] == "test-secret"
        assert request.headers["clienttype"] == "binanceSkill"
        sent.append(json.loads(request.content)["bodyTextOnly"])
        return httpx.Response(200, json={"code": "000000", "data": {"id": "123"}})
    for hour in range(9, 24):
        report = run(edition(), state, hour=hour, handler=handler)
    assert len(sent) == len(set(sent)) == 14
    assert report["remaining"] == 0


def test_final_slot_catches_up_without_truncating_selection():
    report = run(edition(17), {"version": 1, "editions": {}}, hour=23)
    assert report["sent"] == 17


def test_stale_edition_is_never_automatically_sent():
    payload = edition()
    payload["date"] = "2026-09-10"
    assert run(payload, {"editions": {}})["reason"] == "edition_date_mismatch"


def test_remote_checkpoint_precedes_send_and_failure_prevents_post():
    checkpoints = []
    def checkpoint(state):
        checkpoints.append(copy.deepcopy(state))
    def handler(request):
        assert next(iter(checkpoints[-1]["editions"]["2026-09-11"].values()))["status"] == "pending"
        return httpx.Response(200, json={"code": "000000", "data": {"id": "456"}})
    run(edition(1), {"editions": {}}, checkpoint=checkpoint, handler=handler)
    assert len(checkpoints) == 2
    def fail(state):
        raise OSError("checkpoint rejected")
    with pytest.raises(OSError):
        run(edition(1), {"editions": {}}, checkpoint=fail,
            handler=lambda r: pytest.fail("must not post before checkpoint"))


@pytest.mark.parametrize("status,body", [(504, ""), (502, "bad"), (200, "html"), (302, "")])
def test_ambiguous_result_is_not_retried(status, body):
    state = {"editions": {}}
    run(edition(1), state, handler=lambda r: httpx.Response(status, text=body))
    assert run(edition(1), state)["unknown"] == 1
    assert run(edition(1), state)["attempted"] == 0


def test_crashed_pending_and_reordered_stories_are_not_resent():
    payload = edition(1)
    state = {"editions": {payload["date"]: {story_key(payload["items"][0]): {"status": "pending"}}}}
    payload["items"][0]["rank"] = 12
    payload["items"][0]["title"]["zh"] = "更新标题"
    assert run(payload, state)["attempted"] == 0


def test_rejection_is_sanitized_and_stops_batch():
    report = run(edition(5), {"editions": {}}, hour=23,
        handler=lambda r: httpx.Response(200, json={"code": "220003", "message": "test-secret"}))
    assert report["attempted"] == 1
    assert report["rejected"] == 1
    assert "test-secret" not in json.dumps(report)


def test_text_keeps_paragraphs_and_qualifications():
    item = edition(1)["items"][0]
    assert item["summary"]["zh"] in compose(item, "2026-09-11")
    item["summary"]["zh"] = "字" * 10001
    with pytest.raises(ValueError):
        compose(item, "2026-09-11")


def test_invalid_content_blocked_without_losing_other_items():
    payload = edition(2)
    payload["items"][0]["summary"] = {}
    report = run(payload, {"editions": {}}, hour=23)
    assert report["blocked"] == 1 and report["sent"] == 1


def test_corrupt_state_fails_closed(tmp_path):
    path = tmp_path / "queue.json"
    path.write_text('{"version":1,"editions":{"2026-09-11":{"x":{"status":"oops"}}}}')
    with pytest.raises(ValueError):
        read_state(path)
    path.write_text("broken")
    with pytest.raises(ValueError):
        read_state(path)


def test_transport_failure_remains_uncertain():
    def handler(request):
        raise httpx.ReadTimeout("secret must not leak", request=request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert send(client, "test", "body") == {"status": "unknown", "detail": "transport_or_response_error"}


def test_duplicate_urls_are_sent_once():
    payload = edition(1)
    payload["items"] *= 2
    assert run(payload, {"editions": {}}, hour=23)["sent"] == 1


def test_checkpoint_is_recoverable_from_remote_git(tmp_path):
    remote, local = tmp_path / "remote.git", tmp_path / "queue"
    def git(*args):
        return subprocess.run(["git", *map(str, args)], check=True, capture_output=True, text=True).stdout
    git("init", "--bare", remote)
    git("init", local)
    git("-C", local, "config", "user.name", "test")
    git("-C", local, "config", "user.email", "test@example.com")
    git("-C", local, "remote", "add", "origin", remote)
    state = {"version": 1, "editions": {}}
    run(edition(1), state, checkpoint=lambda s: git_checkpoint(local, s))
    saved = json.loads(git("--git-dir", remote, "show", "square-queue:queue.json"))
    assert list(saved["editions"]["2026-09-11"].values())[0]["status"] == "sent"
    pending = json.loads(git("--git-dir", remote, "show", "square-queue~1:queue.json"))
    assert list(pending["editions"]["2026-09-11"].values())[0]["status"] == "pending"
