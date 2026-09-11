"""Persisted Square publication plans; stdlib-only idle checks, no edition fetch."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import random
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Queue timestamps require timezone")
    return parsed.astimezone(TZ)


def load(path: Path) -> dict:
    state = json.loads(path.read_text()) if path.exists() else {"version": 1, "editions": {}}
    if not isinstance(state, dict) or state.get("version") != 1 or not isinstance(state.get("editions"), dict):
        raise ValueError("Invalid queue; never reset delivery history")
    for rows in state["editions"].values():
        if not isinstance(rows, dict):
            raise ValueError("Invalid edition history")
        for row in rows.values():
            if not isinstance(row, dict) or row.get("status") not in {"sent", "pending", "unknown", "rejected", "blocked"}:
                raise ValueError("Invalid delivery history")
            if row.get("attempted_at"):
                timestamp(row["attempted_at"])
    plans = state.get("plans", {})
    if not isinstance(plans, dict):
        raise ValueError("Invalid plans")
    for plan in plans.values():
        if not isinstance(plan, dict) or not isinstance(plan.get("jobs"), list) or not isinstance(plan.get("revision"), str):
            raise ValueError("Invalid plan")
        ids = set()
        for job in plan["jobs"]:
            if not isinstance(job, dict) or not isinstance(job.get("id"), str) or job["id"] in ids:
                raise ValueError("Invalid plan identity")
            ids.add(job["id"])
            if not isinstance(job.get("text"), str) or len(job["text"]) > 10000:
                raise ValueError("Invalid plan text")
            if job.get("due_at") is not None:
                timestamp(job["due_at"])
    return state


def gate(state: dict, now: datetime, date: str = "", force_sync: bool = False) -> dict:
    now = now.astimezone(TZ)
    date = date or now.date().isoformat()
    plan = state.get("plans", {}).get(date)
    rows = state["editions"].get(date, {})
    jobs = [] if plan is None else [job for job in plan["jobs"] if job["id"] not in rows]
    window = 9 <= now.hour and (now.hour < 23 or now.minute <= 30)
    recent = any(row.get("attempted_at") and now - timestamp(row["attempted_at"]) < timedelta(minutes=5)
                 for row in rows.values())
    due = window and not recent and any(job.get("due_at") and timestamp(job["due_at"]) <= now for job in jobs)
    return {"sync": force_sync or plan is None, "due": due, "remaining": len(jobs),
        "attention": sum(row["status"] != "sent" for row in rows.values()),
        "unscheduled": sum(job.get("due_at") is None for job in jobs)}


def schedule(count: int, now: datetime, reserved: list[str], rng=None) -> list[str | None]:
    rng = rng or random.SystemRandom()
    now = now.astimezone(TZ)
    start = max(now.replace(hour=9, minute=0, second=0, microsecond=0),
                now.replace(second=0, microsecond=0) + timedelta(minutes=1))
    end = now.replace(hour=23, minute=25, second=0, microsecond=0)  # Last poll before 23:30.
    occupied = [timestamp(value) for value in reserved]
    minutes = [start + timedelta(minutes=i) for i in range(max(0, int((end-start).total_seconds()//60)+1))]
    minutes = [value for value in minutes if all(abs((value-other).total_seconds()) >= 300 for other in occupied)]
    result = []
    previous = None
    for index in range(count):
        # Stratified randomness: spread posts across the remaining reading window.
        bucket = minutes[index*len(minutes)//count:(index+1)*len(minutes)//count]
        bucket = [value for value in bucket if previous is None or value-previous >= timedelta(minutes=5)]
        value = rng.choice(bucket) if bucket else None
        result.append(value.isoformat() if value else None)
        if value:
            previous = value
    return result


def sync_plan(edition: dict, state: dict, now: datetime, compose, identity, checkpoint,
              explicit_date: str = "", rng=None) -> bool:
    date = edition.get("date")
    if date != (explicit_date or now.astimezone(TZ).date().isoformat()):
        return False  # Never label yesterday as today.
    items = edition.get("items")
    if not isinstance(items, list) or len(items) > 100 or any(not isinstance(item, dict) for item in items):
        raise ValueError("Invalid edition")
    rows = state["editions"].get(date, {})
    selected = []
    seen = set()
    for item in items:
        key = identity(item)
        if key in seen:
            continue
        seen.add(key)
        try:
            text = compose(item, date)
        except (ValueError, TypeError, AttributeError):
            text = ""  # Explicit blocked job, not silently dropped content.
        selected.append({"id": key, "text": text, "rank": item.get("rank")})
    if len(set(rows) | seen) > 100:
        raise ValueError("Daily attempt safety cap exceeded")
    revision = hashlib.sha256(json.dumps(selected, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    plans = state.setdefault("plans", {})
    old = plans.get(date, {})
    if old.get("revision") == revision:
        return False
    previous = {job["id"]: job for job in old.get("jobs", [])}
    jobs = []
    for job in selected:
        if job["id"] in rows:
            continue  # Preserve all sent and uncertain history, never re-arm it.
        job["due_at"] = previous.get(job["id"], {}).get("due_at")
        jobs.append(job)
    new = [job for job in jobs if job["id"] not in previous]
    reserved = [job["due_at"] for job in jobs if job["due_at"]]
    for job, due_at in zip(new, schedule(len(new), now, reserved, rng)):
        job["due_at"] = due_at
    plans[date] = {"revision": revision, "jobs": jobs, "selected": len(selected), "synced_at": now.isoformat()}
    checkpoint(state)  # Randomness and exact text durable BEFORE any publication.
    return True


def drain(state: dict, now: datetime, client, key: str, checkpoint, send, explicit_date: str = "") -> dict:
    date = explicit_date or now.astimezone(TZ).date().isoformat()
    decision = gate(state, now, date)
    rows = state["editions"].setdefault(date, {})
    attempted = 0
    if decision["due"]:
        jobs = sorted((job for job in state["plans"][date]["jobs"] if job["id"] not in rows and job.get("due_at")
                       and timestamp(job["due_at"]) <= now), key=lambda job: job["due_at"])
        job = jobs[0]  # At most one post per poll; delayed runners never burst a batch.
        row = {"status": "pending" if job["text"] else "blocked", "rank": job["rank"],
               "text_hash": hashlib.sha256(job["text"].encode()).hexdigest(), "attempted_at": now.isoformat()}
        rows[job["id"]] = row
        checkpoint(state)
        if job["text"]:
            row.update(send(client, key, job["text"]))
            if row["status"] == "sent":
                # Keep compact evidence, not years of duplicated article bodies.
                state["plans"][date]["jobs"] = [entry for entry in state["plans"][date]["jobs"] if entry["id"] != job["id"]]
            checkpoint(state)
            attempted = 1
    result = gate(state, now, date)
    return {"status": "attention" if result["attention"] or result["unscheduled"] else "ok",
            "date": date, "attempted": attempted, "sent": sum(row["status"] == "sent" for row in rows.values()), **result}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--date", default="")
    parser.add_argument("--force-sync", action="store_true")
    args = parser.parse_args()
    result = gate(load(args.queue), datetime.now(TZ), args.date, args.force_sync)
    for name, value in result.items():
        print(f"{name}={str(value).lower()}")
