import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import random
import subprocess
import sys

import httpx
import pytest

from src.square_delivery import compose, story_key, send, git_checkpoint, read_state
from src.square_plan import TZ, sync_plan, drain, gate, load, schedule

NOW = datetime(2026, 9, 12, 8, 35, tzinfo=TZ)


def edition(n=14):
    return {"date": NOW.date().isoformat(), "items": [
        {"rank": i+1, "url": f"https://example.com/{i}", "title": {"zh": f"新闻{i}"},
         "summary": {"zh": "已确认的事件。\n\n背景与影响，尚未批准。"}} for i in range(n)]}


def setup(n=14, state=None, now=NOW):
    state = state if state is not None else {"version": 1, "editions": {}}
    sync_plan(edition(n), state, now, compose, story_key, lambda s: None, rng=random.Random(5))
    return state


def run(state, now, checkpoint=lambda s: None, handler=None):
    with httpx.Client(transport=httpx.MockTransport(handler or (lambda r: httpx.Response(200,
            json={"code": "000000", "data": {"id": "123"}})))) as client:
        return drain(state, now, client, "test-secret", checkpoint, send)


def test_random_schedule_is_stable_and_spread():
    state = setup()
    original = copy.deepcopy(state)
    sync_plan(edition(), state, NOW, compose, story_key, lambda s: pytest.fail("must not rewrite unchanged edition"))
    assert state == original
    times = [datetime.fromisoformat(j["due_at"]) for j in state["plans"]["2026-09-12"]["jobs"]]
    assert len(set(t.minute for t in times)) > 3
    assert all(b-a >= timedelta(minutes=5) for a, b in zip(times, times[1:]))
    assert times[0].hour >= 9 and times[-1] <= NOW.replace(hour=23, minute=25)


def test_entire_day_reads_only_queue_and_sends_every_item_once():
    state = setup()
    sent = []
    def handler(request):
        assert request.headers["X-Square-OpenAPI-Key"] == "test-secret"
        assert request.headers["clienttype"] == "binanceSkill"
        sent.append(json.loads(request.content)["bodyTextOnly"])
        return httpx.Response(200, json={"code": "000000", "data": {"id": "456"}})
    for minute in range(9*60, 23*60+31, 5):
        run(state, NOW.replace(hour=minute//60, minute=minute%60), handler=handler)
    assert len(sent) == len(set(sent)) == 14
    assert state["plans"]["2026-09-12"]["jobs"] == []
    assert gate(state, NOW.replace(hour=23, minute=30)) == {
        "sync": False, "due": False, "remaining": 0, "attention": 0, "unscheduled": 0}


def test_revision_updates_unsent_and_removes_withdrawn_without_rerandomizing():
    state = setup(3)
    date = "2026-09-12"
    first = state["plans"][date]["jobs"][0]
    second = copy.deepcopy(state["plans"][date]["jobs"][1])
    run(state, datetime.fromisoformat(first["due_at"]))
    payload = edition(2)
    payload["items"][1]["summary"]["zh"] = "修订正文。"
    sync_plan(payload, state, NOW, compose, story_key, lambda s: None)
    jobs = state["plans"][date]["jobs"]
    assert len(jobs) == 1 and jobs[0]["id"] == second["id"]
    assert jobs[0]["due_at"] == second["due_at"] and "修订正文" in jobs[0]["text"]
    assert state["editions"][date][first["id"]]["status"] == "sent"


def test_old_queue_migration_never_rearms_sent_or_uncertain():
    payload = edition(3)
    rows = {story_key(item): {"status": status} for item, status in zip(payload["items"], ["sent", "unknown", "pending"])}
    state = setup(4, {"version": 1, "editions": {"2026-09-12": rows}})
    assert len(state["plans"]["2026-09-12"]["jobs"]) == 1
    assert len(rows) == 3


def test_pending_checkpoint_precedes_post():
    state = setup(1)
    snapshots = []
    def checkpoint(s):
        snapshots.append(copy.deepcopy(s))
    def handler(request):
        assert list(snapshots[-1]["editions"]["2026-09-12"].values())[0]["status"] == "pending"
        return httpx.Response(200, json={"code": "000000", "data": {"id": "123"}})
    due = datetime.fromisoformat(state["plans"]["2026-09-12"]["jobs"][0]["due_at"])
    run(state, due, checkpoint, handler)
    assert len(snapshots) == 2
    assert run(state, due)["attempted"] == 0


def test_checkpoint_failure_prevents_publication():
    state = setup(1)
    def fail(s):
        raise OSError("remote unavailable")
    with pytest.raises(OSError):
        run(state, NOW.replace(hour=23, minute=25), fail, lambda r: pytest.fail("must not post"))


@pytest.mark.parametrize("status,body", [(504, ""), (502, "oops"), (200, "html"), (302, "")])
def test_unknown_never_retried(status, body):
    state = setup(1)
    now = NOW.replace(hour=23, minute=25)
    report = run(state, now, handler=lambda r: httpx.Response(status, text=body))
    assert report["attention"] == 1
    assert run(state, now+timedelta(minutes=5))["attempted"] == 0


def test_delay_never_bursts_and_trigger_types_share_minimum_gap():
    state = setup()
    now = NOW.replace(hour=22, minute=0)
    assert run(state, now)["attempted"] == 1
    assert run(state, now+timedelta(minutes=1))["attempted"] == 0
    assert run(state, now+timedelta(minutes=5))["attempted"] == 1


def test_no_overnight_or_yesterday_automatic_posts():
    state = setup(1)
    assert run(state, NOW.replace(hour=23, minute=31))["attempted"] == 0
    assert run(state, NOW+timedelta(days=1))["attempted"] == 0
    assert not sync_plan(edition(), state, NOW+timedelta(days=1), compose, story_key, lambda s: pytest.fail("stale"))


def test_saturated_window_is_visible_not_silently_lost():
    values = schedule(15, NOW.replace(hour=23, minute=24), [], random.Random(1))
    assert any(value is None for value in values)


@pytest.mark.parametrize("raw", ["bad", "[]", '{"version":2}', '{"version":1,"editions":{"x":{"y":{"status":"oops"}}}}'])
def test_corruption_fails_closed(tmp_path, raw):
    path = tmp_path / "queue.json"
    path.write_text(raw)
    with pytest.raises(ValueError):
        load(path)


def test_text_keeps_qualifications_and_never_truncates():
    item = edition(1)["items"][0]
    assert item["summary"]["zh"] in compose(item, "2026-09-12")
    item["summary"]["zh"] = "字" * 10001
    with pytest.raises(ValueError):
        compose(item, "2026-09-12")


def test_transport_error_is_sanitized():
    def handler(request):
        raise httpx.ReadTimeout("secret", request=request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert send(client, "test", "body") == {"status": "unknown", "detail": "transport_or_response_error"}


def test_git_remote_recovers_exact_plan_and_attempt(tmp_path):
    remote, local = tmp_path / "remote.git", tmp_path / "queue"
    def git(*args):
        return subprocess.run(["git", *map(str, args)], check=True, capture_output=True, text=True).stdout
    git("init", "--bare", remote)
    git("init", local)
    git("-C", local, "config", "user.name", "test")
    git("-C", local, "config", "user.email", "test@example.com")
    git("-C", local, "remote", "add", "origin", remote)
    state = {"version": 1, "editions": {}}
    checkpoint = lambda s: git_checkpoint(local, s)
    sync_plan(edition(1), state, NOW, compose, story_key, checkpoint)
    run(state, NOW.replace(hour=23, minute=25), checkpoint)
    saved = json.loads(git("--git-dir", remote, "show", "square-queue:queue.json"))
    assert saved == read_state(local / "queue.json") == state
    pending = json.loads(git("--git-dir", remote, "show", "square-queue~1:queue.json"))
    assert list(pending["editions"]["2026-09-12"].values())[0]["status"] == "pending"


def test_workflow_fast_gate_precedes_edition_read_and_install():
    workflow = (Path(__file__).parents[1] / ".github/workflows/square-distribution.yml").read_text()
    assert workflow.index("id: gate") < workflow.index("git fetch --depth=1 origin gh-pages") < workflow.index("uv sync --frozen")
    assert "if: steps.gate.outputs.sync == 'true'" in workflow
    assert "cron: '*/5 1-14 * * *'" in workflow
    assert 'QUEUE_ONLY: ${{ inputs.queue_only }}' in workflow
    assert '[ "$QUEUE_ONLY" != true ]' in workflow
    assert "head_repository.full_name == github.repository" in workflow
    assert "ref: main" in workflow and "branches: [main]" in workflow
    assert "'Deploy Docs'" in workflow and "'BMTNews Feed Collection'" in workflow


def test_idle_gate_needs_no_installed_dependencies(tmp_path):
    queue = tmp_path / "queue.json"
    queue.write_text(json.dumps(setup()))
    result = subprocess.run([sys.executable, "-S", "-m", "src.square_plan", "--queue", str(queue),
                             "--date", "2026-09-12"], capture_output=True, text=True, check=True)
    assert "sync=false" in result.stdout


def test_revision_adds_new_job_without_moving_existing_times():
    state = setup(2)
    previous = copy.deepcopy(state["plans"]["2026-09-12"]["jobs"])
    sync_plan(edition(3), state, NOW, compose, story_key, lambda s: None, rng=random.Random(99))
    jobs = state["plans"]["2026-09-12"]["jobs"]
    assert jobs[:2] == previous and jobs[2]["due_at"] is not None


def test_failed_platform_response_preserves_history_and_never_echoes_key():
    state = setup(1)
    result = run(state, NOW.replace(hour=23, minute=25), handler=lambda r: httpx.Response(200,
        json={"code": "220003", "message": "test-secret"}))
    assert result["attention"] == 1
    assert "test-secret" not in json.dumps(state)


def test_only_current_plan_is_synced_and_legacy_dates_preserved():
    state = {"version": 1, "editions": {"2026-09-11": {"old": {"status": "sent"}}}}
    setup(1, state)
    assert state["editions"]["2026-09-11"] == {"old": {"status": "sent"}}
    assert gate(state, NOW, force_sync=True)["sync"] is True
