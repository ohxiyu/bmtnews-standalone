"""Plan-then-send X delivery: schedule, receipts, and failure handling."""

import asyncio
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from rich.console import Console

from src import x_queue
from src.daily_feed import DailyFeedState, item_identity
from src.models import ContentItem, SourceType, XDeliveryConfig
from src.services.x_delivery import (
    PostOutcome,
    XEditionPublisher,
    unsupported_figures,
)

UTC = timezone.utc
DAY = "2026-08-09"
# 07:30 Asia/Shanghai on DAY: an on-time edition.
ON_TIME = datetime(2026, 8, 8, 23, 30, tzinfo=UTC)


def item(n: int, summary: str = "") -> ContentItem:
    return ContentItem(
        id=f"story-{n}",
        source_type=SourceType.RSS,
        title=f"第{n}条",
        url=f"https://example.com/story-{n}",
        published_at=datetime(2026, 8, 9, tzinfo=UTC),
        ai_score=9.0,
        metadata={
            "title_zh": f"第{n}条",
            "detailed_summary_zh": summary or f"第{n}条的摘要。",
        },
    )


class FakePublisher:
    """Returns scripted outcome kinds, then ``sent``."""

    def __init__(self, *kinds: str, ready: str = "") -> None:
        self.kinds = list(kinds)
        self.posts: list[str] = []
        self.ready = ready

    def not_ready_reason(self) -> str:
        return self.ready

    async def publish_post(self, text: str) -> PostOutcome:
        self.posts.append(text)
        kind = self.kinds.pop(0) if self.kinds else "sent"
        tweet_id = str(1000 + len(self.posts)) if kind == "sent" else ""
        return PostOutcome(kind, f"scripted {kind}", tweet_id)


def orchestrator_for(publisher, **x_overrides):
    from src.orchestrator import BMTNewsOrchestrator

    orchestrator = BMTNewsOrchestrator.__new__(BMTNewsOrchestrator)
    orchestrator.console = Console(record=True)
    settings = {"enabled": True, "mode": "drip", "compose": "template"}
    settings.update(x_overrides)
    orchestrator.config = SimpleNamespace(
        x_delivery=XDeliveryConfig(**settings),
        filtering=SimpleNamespace(daily_timezone="Asia/Shanghai"),
        ai=None,
    )
    orchestrator.x_publisher = publisher
    return orchestrator


def run(monkeypatch, orchestrator, items, path, *, now, updated_at=ON_TIME):
    import src.orchestrator as module

    feed = DailyFeedState(
        date=DAY, timezone="Asia/Shanghai", updated_at=updated_at, items=items
    )
    monkeypatch.setattr(
        module,
        "load_daily_feed_state",
        lambda day, tz: feed if day == DAY else DailyFeedState(
            date=day, timezone=tz, updated_at=updated_at
        ),
    )
    monkeypatch.setattr(module, "save_run_report", lambda report: None)
    asyncio.run(orchestrator.run_x_slot(now=now, state_path=path))


def jobs(path: Path, day: str = DAY) -> list[dict]:
    return json.loads(path.read_text())["editions"][day]["jobs"]


def test_top1_on_publication_then_top2_after_the_seeded_gap(monkeypatch, tmp_path):
    publisher = FakePublisher()
    orchestrator = orchestrator_for(publisher)
    items = [item(n) for n in range(1, 6)]
    path = tmp_path / "q.json"

    run(monkeypatch, orchestrator, items, path, now=ON_TIME + timedelta(minutes=5))
    assert len(publisher.posts) == 1 and "第1条" in publisher.posts[0]
    top1, top2 = jobs(path)
    assert top1["status"] == "sent" and top1["tweet_id"] == "1001"
    assert top2["status"] == "planned" and "第2条" in top2["text"]
    gap = top2["gap_minutes"]
    assert 180 <= gap <= 360

    sent_at = ON_TIME + timedelta(minutes=5)
    run(monkeypatch, orchestrator, items, path, now=sent_at + timedelta(minutes=gap - 1))
    assert len(publisher.posts) == 1
    assert jobs(path)[1]["due_at"] == (sent_at + timedelta(minutes=gap)).isoformat()

    run(monkeypatch, orchestrator, items, path, now=sent_at + timedelta(minutes=gap + 1))
    assert len(publisher.posts) == 2 and publisher.posts[1] == top2["text"]

    for hours in (1, 3, 6):
        run(monkeypatch, orchestrator, items, path, now=sent_at + timedelta(hours=8 + hours))
    assert len(publisher.posts) == 2  # Two a day, never a third.
    assert [job["status"] for job in jobs(path)] == ["sent", "sent"]


def test_gap_is_reproducible_for_a_day():
    settings = x_queue.Settings()
    first = x_queue._gap_minutes(DAY, "zh", 2, settings)
    assert first == x_queue._gap_minutes(DAY, "zh", 2, settings)
    assert 180 <= first <= 360


def test_edition_published_over_six_hours_late_is_not_posted(monkeypatch, tmp_path):
    publisher = FakePublisher()
    orchestrator = orchestrator_for(publisher)
    late = datetime(2026, 8, 9, 5, 30, tzinfo=UTC)  # 13:30 Shanghai
    path = tmp_path / "q.json"
    run(monkeypatch, orchestrator, [item(1), item(2)], path, now=late, updated_at=late)
    assert publisher.posts == []
    edition = json.loads(path.read_text())["editions"][DAY]
    assert edition["status"] == "skipped_late" and edition["jobs"] == []
    assert any(a.code == "x_edition_late" for a in orchestrator.last_run_report.alerts)

    # A later republish never revives it.
    run(monkeypatch, orchestrator, [item(1), item(2)], path,
        now=late + timedelta(hours=1), updated_at=late + timedelta(hours=1))
    assert publisher.posts == []


def test_just_inside_the_publish_window_still_posts(monkeypatch, tmp_path):
    publisher = FakePublisher()
    orchestrator = orchestrator_for(publisher)
    edge = datetime(2026, 8, 9, 5, 26, tzinfo=UTC)  # 13:26 Shanghai
    run(monkeypatch, orchestrator, [item(1), item(2)], tmp_path / "q.json",
        now=edge, updated_at=edge)
    assert len(publisher.posts) == 1


def test_unsent_post_expires_six_hours_after_due(monkeypatch, tmp_path):
    publisher = FakePublisher(ready="credentials missing")
    orchestrator = orchestrator_for(publisher)
    path = tmp_path / "q.json"
    run(monkeypatch, orchestrator, [item(1), item(2)], path, now=ON_TIME)
    assert jobs(path)[0]["status"] == "planned"

    publisher.ready = ""
    run(monkeypatch, orchestrator, [item(1), item(2)], path,
        now=ON_TIME + timedelta(hours=6, minutes=1))
    assert publisher.posts == []
    assert jobs(path)[0]["status"] == "expired"
    assert jobs(path)[0]["detail"] == "missed_deadline"


def test_deadline_never_passes_the_evening_cutoff():
    settings = x_queue.Settings()
    due = datetime.fromisoformat(f"{DAY}T21:00:00+08:00")
    assert x_queue._deadline(due, DAY, settings).isoformat() == f"{DAY}T23:30:00+08:00"


def test_unknown_is_never_retried_and_top2_still_goes(monkeypatch, tmp_path):
    publisher = FakePublisher("unknown")
    orchestrator = orchestrator_for(publisher)
    items = [item(1), item(2), item(3)]
    path = tmp_path / "q.json"
    with pytest.raises(RuntimeError, match="needs a person"):
        run(monkeypatch, orchestrator, items, path, now=ON_TIME)
    assert jobs(path)[0]["status"] == "unknown"

    gap = jobs(path)[1]["gap_minutes"]
    for minutes in (20, 40, gap + 1):
        run(monkeypatch, orchestrator, items, path, now=ON_TIME + timedelta(minutes=minutes))
    assert len(publisher.posts) == 2
    assert "第2条" in publisher.posts[1]
    assert jobs(path)[0]["status"] == "unknown"


def test_a_run_that_died_mid_send_is_recorded_as_unknown(monkeypatch, tmp_path):
    publisher = FakePublisher()
    orchestrator = orchestrator_for(publisher)
    items = [item(1), item(2)]
    path = tmp_path / "q.json"
    run(monkeypatch, orchestrator, items, path, now=ON_TIME - timedelta(minutes=1))
    state = json.loads(path.read_text())
    state["editions"][DAY]["jobs"][0]["status"] = "pending"
    path.write_text(json.dumps(state))

    with pytest.raises(RuntimeError, match="needs a person"):
        run(monkeypatch, orchestrator, items, path, now=ON_TIME + timedelta(minutes=20))
    assert publisher.posts == []
    assert jobs(path)[0]["detail"] == "interrupted_before_result"


def test_failed_checkpoint_means_nothing_is_sent(monkeypatch, tmp_path):
    import src.orchestrator as module

    publisher = FakePublisher()
    orchestrator = orchestrator_for(publisher)
    queue_dir = tmp_path / "x-state"

    def checkpoint(directory, state):
        if any(
            job["status"] == "pending"
            for edition in state["editions"].values()
            for job in edition["jobs"]
        ):
            raise subprocess.CalledProcessError(1, ["git", "push"])
        x_queue.save(state, directory / x_queue.QUEUE_RELATIVE_PATH)

    monkeypatch.setattr(x_queue, "git_checkpoint", checkpoint)
    feed = DailyFeedState(
        date=DAY, timezone="Asia/Shanghai", updated_at=ON_TIME, items=[item(1)]
    )
    monkeypatch.setattr(module, "load_daily_feed_state", lambda *a: feed)
    monkeypatch.setattr(module, "save_run_report", lambda report: None)
    with pytest.raises(subprocess.CalledProcessError):
        asyncio.run(orchestrator.run_x_slot(now=ON_TIME, queue_dir=queue_dir))
    assert publisher.posts == []
    assert jobs(queue_dir / "data/x-queue.json")[0]["status"] == "planned"


def test_auth_rejection_stops_the_language_for_the_day(monkeypatch, tmp_path):
    publisher = FakePublisher("failed")
    orchestrator = orchestrator_for(publisher)
    items = [item(1), item(2)]
    path = tmp_path / "q.json"
    with pytest.raises(RuntimeError):
        run(monkeypatch, orchestrator, items, path, now=ON_TIME)
    run(monkeypatch, orchestrator, items, path, now=ON_TIME + timedelta(hours=7))
    assert len(publisher.posts) == 1
    assert [job["status"] for job in jobs(path)] == ["failed", "planned"]


def test_rate_limit_retries_the_same_text_before_the_deadline(monkeypatch, tmp_path):
    publisher = FakePublisher("rate_limited", "not_sent")
    orchestrator = orchestrator_for(publisher)
    items = [item(1), item(2)]
    path = tmp_path / "q.json"
    for minutes in (0, 20, 40):
        run(monkeypatch, orchestrator, items, path, now=ON_TIME + timedelta(minutes=minutes))
    assert len(publisher.posts) == 3
    assert len(set(publisher.posts)) == 1
    top1 = jobs(path)[0]
    assert top1["status"] == "sent"
    assert top1["attempted_at"] == (ON_TIME + timedelta(minutes=40)).isoformat()


def test_republish_replans_only_unattempted_posts(monkeypatch, tmp_path):
    publisher = FakePublisher()
    orchestrator = orchestrator_for(publisher)
    path = tmp_path / "q.json"
    items = [item(1), item(2), item(3)]
    run(monkeypatch, orchestrator, items, path, now=ON_TIME)
    gap = jobs(path)[1]["gap_minutes"]

    # The edition is republished with story 1 dropped and story 3 on top.
    republished = [item(3), item(2)]
    run(monkeypatch, orchestrator, republished, path,
        now=ON_TIME + timedelta(hours=1), updated_at=ON_TIME + timedelta(hours=1))
    top1, top2 = jobs(path)
    assert top1["status"] == "sent" and "第1条" in top1["text"]
    assert "第3条" in top2["text"] and top2["detail"] == "replanned"
    assert top2["gap_minutes"] == gap

    run(monkeypatch, orchestrator, republished, path,
        now=ON_TIME + timedelta(minutes=gap + 1), updated_at=ON_TIME + timedelta(hours=1))
    assert ["第1条" in publisher.posts[0], "第3条" in publisher.posts[1]] == [True, True]


def test_story_posted_in_the_last_week_is_not_posted_again(monkeypatch, tmp_path):
    path = tmp_path / "q.json"
    state = x_queue.empty_state()
    yesterday = x_queue._blank_job(
        "zh", 1, x_queue.story_key_for_identity(item_identity(item(1)))
    )
    yesterday.update(status="sent", tweet_id="9")
    state["editions"]["2026-08-08"] = {
        "status": "active",
        "published_at": "2026-08-08T07:30:00+08:00",
        "state_updated_at": "",
        "planned_at": "2026-08-08T07:30:00+08:00",
        "jobs": [yesterday],
    }
    x_queue.save(state, path)

    publisher = FakePublisher()
    run(monkeypatch, orchestrator_for(publisher), [item(1), item(2), item(3)], path, now=ON_TIME)
    assert "第2条" in publisher.posts[0]
    assert "第3条" in jobs(path)[1]["text"]


def test_ai_post_with_an_unsupported_figure_falls_back_to_the_template(
    monkeypatch, tmp_path
):
    import src.orchestrator as module

    invented = (
        "8月9日，交易所第1条公告称遭攻击，损失约 2.3 亿美元。\n\n"
        "目前平台已经暂停提款，并表示会在调查完成后公布细节与赔付方案，用户资产暂未受到进一步影响，"
        "监管机构也已介入调查。"
    )

    class Client:
        async def complete(self, **kwargs):
            return invented

    monkeypatch.setattr(module, "create_ai_client", lambda config: Client())
    publisher = FakePublisher()
    orchestrator = orchestrator_for(publisher, compose="ai")
    path = tmp_path / "q.json"
    run(monkeypatch, orchestrator, [item(1, "交易所遭攻击，损失约 1.46 亿美元。")], path, now=ON_TIME)
    assert "2.3 亿" not in publisher.posts[0]
    assert jobs(path)[0]["compose"] == "template"
    assert jobs(path)[0]["fallback_reason"] == "unsupported_figures"


def test_only_todays_edition_is_posted(monkeypatch, tmp_path):
    publisher = FakePublisher()
    orchestrator = orchestrator_for(publisher)
    path = tmp_path / "q.json"
    run(monkeypatch, orchestrator, [item(1)], path, now=ON_TIME + timedelta(days=1))
    assert publisher.posts == []


def test_unsupported_figures_accepts_unit_changes_and_rounding():
    sources = ["约 $1.46 billion 被盗，涉及 401,347 枚 ETH；比特币下跌 2.6%，发生在 2 月 21 日。"]
    assert unsupported_figures("被盗约 14.6 亿美元，40.1 万枚 ETH，跌 2.6%。", sources) == []
    assert unsupported_figures("被盗约 15 亿美元。", sources) == []
    assert unsupported_figures("9月26日，2026年，3 家机构回应。", sources) == []
    assert unsupported_figures("被盗 14.7 亿美元，跌 3%。", sources) == ["14.7 亿"]
    assert unsupported_figures("涨 2.6 亿", ["涨 2.6%"]) == ["2.6 亿"]


def test_v1_queue_migrates_without_losing_receipts(tmp_path):
    path = tmp_path / "q.json"
    path.write_text(json.dumps({
        "version": 1,
        "date": DAY,
        "posted": {"zh": [1, 3]},
        "selection_keys": ["https://example.com/story-1"],
    }))
    state = x_queue.load(path, ON_TIME)
    first, second = state["editions"][DAY]["jobs"]
    assert first["status"] == "sent"
    assert first["story_key"] == x_queue.story_key_for_identity("https://example.com/story-1")
    assert second["status"] == "unknown"
    assert second["detail"] == "migrated_v1_unidentified"


@pytest.mark.parametrize(
    "payload", ["{oops", "{}", '{"version": 999}', '{"version": 2, "editions": []}']
)
def test_unreadable_queue_refuses_to_reset_history(tmp_path, payload):
    path = tmp_path / "q.json"
    path.write_text(payload)
    with pytest.raises(x_queue.QueueError):
        x_queue.load(path)
    assert x_queue.load(tmp_path / "missing.json") == x_queue.empty_state()


def _gate(tmp_path, capsys, *, feed: dict | None, now: datetime, queue: dict | None = None):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "filtering": {"daily_timezone": "Asia/Shanghai"},
        "x_delivery": {"enabled": True, "mode": "drip"},
    }))
    feed_path = tmp_path / "feed.json"
    if feed is not None:
        feed_path.write_text(json.dumps(feed))
    queue_path = tmp_path / "queue.json"
    if queue is not None:
        queue_path.write_text(json.dumps(queue))
    x_queue.main([
        "--queue", str(queue_path), "--feed-state", str(feed_path),
        "--config", str(config), "--now", now.isoformat(),
    ])
    return dict(line.split("=") for line in capsys.readouterr().out.split())


def test_gate_wakes_for_a_new_edition_and_sleeps_after_planning(tmp_path, capsys):
    feed = {"date": DAY, "timezone": "Asia/Shanghai", "updated_at": "2026-08-08T23:30:00Z"}
    assert _gate(tmp_path, capsys, feed=None, now=ON_TIME)["work"] == "false"
    assert _gate(tmp_path, capsys, feed=feed, now=ON_TIME)["work"] == "true"

    state = x_queue.empty_state()
    state["editions"][DAY] = {
        "status": "active",
        "published_at": ON_TIME.isoformat(),
        # The pipeline stores the parsed form; the gate reads the raw "Z" form.
        "state_updated_at": x_queue.normalize_stamp(ON_TIME),
        "planned_at": ON_TIME.isoformat(),
        "jobs": [],
    }
    result = _gate(tmp_path, capsys, feed=feed, now=ON_TIME, queue=state)
    assert result == {"work": "false", "attention": "0"}


def test_gate_reports_attention(tmp_path, capsys):
    state = x_queue.empty_state()
    job = x_queue._blank_job("zh", 1, "k")
    job.update(status="unknown")
    state["editions"][DAY] = {
        "status": "active", "published_at": None, "state_updated_at": "",
        "planned_at": None, "jobs": [job],
    }
    result = _gate(tmp_path, capsys, feed=None, now=ON_TIME, queue=state)
    assert result["attention"] == "1"


def test_git_checkpoint_pushes_without_force(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    for key, value in (("user.name", "t"), ("user.email", "t@example.com")):
        subprocess.run(["git", "-C", str(work), "config", key, value], check=True)
    subprocess.run(["git", "-C", str(work), "remote", "add", "origin", str(remote)], check=True)
    subprocess.run(["git", "-C", str(work), "checkout", "-q", "--orphan", "x-queue"], check=True)

    state = x_queue.empty_state()
    x_queue.git_checkpoint(work, state)
    x_queue.git_checkpoint(work, state)  # Unchanged: no empty commit.
    log = subprocess.run(
        ["git", "-C", str(remote), "log", "--oneline", "x-queue"],
        check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    assert len(log) == 1


def _publisher(monkeypatch, handler) -> XEditionPublisher:
    for name in ("X_CONSUMER_KEY", "X_CONSUMER_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"):
        monkeypatch.setenv(name, "value")
    return XEditionPublisher(
        XDeliveryConfig(enabled=True), transport=httpx.MockTransport(handler)
    )


@pytest.mark.parametrize(
    ("response", "kind"),
    [
        (httpx.Response(201, json={"data": {"id": "123", "text": "x"}}), "sent"),
        (httpx.Response(201, json={"data": {}}), "unknown"),
        (httpx.Response(200, text="not json"), "unknown"),
        (httpx.Response(429), "rate_limited"),
        (httpx.Response(503), "unknown"),
        (httpx.Response(401), "failed"),
        (httpx.Response(403, json={"detail": "duplicate content: secret text"}), "failed"),
    ],
)
def test_publish_post_classifies_responses(monkeypatch, response, kind):
    outcome = asyncio.run(_publisher(monkeypatch, lambda request: response).publish_post("hi"))
    assert outcome.kind == kind
    assert "secret text" not in outcome.detail
    assert outcome.tweet_id == ("123" if kind == "sent" else "")


@pytest.mark.parametrize(
    ("error", "kind"),
    [(httpx.ConnectError, "not_sent"), (httpx.ReadTimeout, "unknown")],
)
def test_publish_post_classifies_transport_errors(monkeypatch, error, kind):
    def handler(request):
        raise error("boom", request=request)

    outcome = asyncio.run(_publisher(monkeypatch, handler).publish_post("hi"))
    assert outcome.kind == kind


def test_production_config_posts_two_a_day():
    config = XDeliveryConfig.model_validate(json.loads(
        (Path(__file__).resolve().parents[1] / "data/config.github.json").read_text()
    )["x_delivery"])
    assert config.mode == "drip"
    assert config.drip_items == XDeliveryConfig().drip_items == 2
    assert (config.drip_gap_min_minutes, config.drip_gap_max_minutes) == (180, 360)
    settings = x_queue.Settings.from_mapping(config.model_dump(), "Asia/Shanghai")
    assert settings.items == 2 and settings.expire_after_minutes == 360


def test_invalid_gap_or_clock_is_rejected():
    with pytest.raises(ValueError):
        XDeliveryConfig(drip_gap_min_minutes=300, drip_gap_max_minutes=200)
    with pytest.raises(ValueError):
        XDeliveryConfig(window_end="25:00")


def test_workflow_restores_the_queue_fail_closed_and_never_force_pushes():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/x-distribution.yml"
    ).read_text()
    assert "push -f" not in workflow and "--force" not in workflow
    assert "git ls-remote --heads origin refs/heads/x-queue" in workflow
    assert "python3 -m src.x_queue" in workflow
    assert "--x-queue-dir" in workflow
    assert "steps.gate.outputs.attention != '0'" in workflow
