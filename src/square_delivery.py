"""Independent, no-AI Square distribution with durable pre-send checkpoints.

Unknown outcomes are NEVER automatically retried: the API offers no documented
idempotency key or lookup. A crash after checkpoint leaves a visible pending row.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from ._file_utils import _atomic_write_text

ENDPOINT = "https://www.binance.com/bapi/composite/v1/public/pgc/openApi/content/add"
SHANGHAI = ZoneInfo("Asia/Shanghai")


def story_key(item: dict) -> str:
    # Stable across ranking/title changes; never use the numerical rank as identity.
    url = item.get("url")
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        raise ValueError("Selected item has no source URL")
    return hashlib.sha256(url.encode()).hexdigest()


def compose(item: dict, date: str) -> str:
    title = item.get("title", {}).get("zh")
    summary = item.get("summary", {}).get("zh")
    if not isinstance(title, str) or not title.strip() or not isinstance(summary, str) or not summary.strip():
        raise ValueError("Chinese title/summary missing")
    # Preserve the published wording, paragraphs and qualifications. No model call,
    # invented facts, tags, or arbitrary truncation of a sentence/number.
    text = f"{title.strip()}\n\n{summary.strip()}\n\n来源：{item['url']}\nBMTNews · {date} · https://bmt.news"
    if len(text) > 10000:
        raise ValueError("Content exceeds local safety limit; editorial review required")
    return text


def read_state(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "editions": {}}
    state = json.loads(path.read_text())  # Corruption must fail closed, never reset.
    if not isinstance(state, dict) or state.get("version") != 1 or not isinstance(state.get("editions"), dict):
        raise ValueError("Invalid Square queue")
    for rows in state["editions"].values():
        if not isinstance(rows, dict) or any(not isinstance(row, dict) or row.get("status") not in
            {"pending", "sent", "unknown", "rejected", "blocked"} for row in rows.values()):
            raise ValueError("Invalid Square queue entries")
    return state


def git_checkpoint(directory: Path, state: dict) -> None:
    _atomic_write_text(directory / "queue.json", json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(directory), *args], check=True, capture_output=True)
    git("add", "queue.json")
    git("commit", "-m", "chore: checkpoint Square delivery")
    # No force push. A rejected checkpoint MUST prevent the external POST.
    git("push", "origin", "HEAD:refs/heads/square-queue")


def send(client: httpx.Client, key: str, text: str) -> dict:
    try:
        with client.stream("POST", ENDPOINT, headers={"X-Square-OpenAPI-Key": key,
                "Content-Type": "application/json", "clienttype": "binanceSkill"},
                json={"contentType": 1, "bodyTextOnly": text}) as response:
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > 65536:
                    return {"status": "unknown", "detail": "oversized_response"}
            if response.status_code >= 500 or 300 <= response.status_code < 400:
                return {"status": "unknown", "detail": f"http_{response.status_code}"}
            payload = json.loads(body)
            if not isinstance(payload, dict):
                return {"status": "unknown", "detail": "invalid_response"}
            code = str(payload.get("code", ""))
            if response.is_success and code == "000000":
                data = payload.get("data") or {}
                post_id = str(data.get("id", "")) if isinstance(data, dict) else ""
                # Safe identifier only, never log raw API messages or response bodies.
                return {"status": "sent", "post_id": post_id if post_id.isdigit() else ""}
            return {"status": "rejected", "detail": "api_" + code if code.isdigit() else f"http_{response.status_code}"}
    except (httpx.HTTPError, ValueError):
        return {"status": "unknown", "detail": "transport_or_response_error"}


def distribute(edition: dict, state: dict, *, now: datetime, client: httpx.Client,
               key: str, checkpoint, explicit_date: str = "") -> dict:
    today = now.astimezone(SHANGHAI).date().isoformat()
    date = edition.get("date")
    if date != (explicit_date or today):
        return {"status": "skipped", "reason": "edition_date_mismatch"}
    items = edition.get("items")
    if not isinstance(items, list) or len(items) > 100 or any(not isinstance(item, dict) for item in items):
        raise ValueError("Invalid selected items or daily cap exceeded")
    rows = state["editions"].setdefault(date, {})
    candidates = []
    seen = set()
    for item in items:
        identity = story_key(item)
        if identity not in seen and identity not in rows:
            candidates.append((identity, item))
        seen.add(identity)
    # Normal day: one per hourly slot. Lost/delayed slots increase the next
    # batch just enough to finish by 23:17. No long-running sleeping runner.
    hour = now.astimezone(SHANGHAI).hour
    slots = max(1, 24 - max(9, hour))
    budget = max(1, math.ceil(len(candidates) / slots))
    if len(rows) + len(candidates) > 100:
        raise ValueError("Daily attempt cap exceeded")
    attempted = 0
    for identity, item in candidates[:budget]:
        try:
            text = compose(item, date)
        except ValueError:
            rows[identity] = {"status": "blocked", "detail": "invalid_content"}
            checkpoint(state)
            continue
        rows[identity] = {"status": "pending", "rank": item.get("rank"),
            "text_hash": hashlib.sha256(text.encode()).hexdigest(), "attempted_at": now.isoformat()}
        checkpoint(state)  # Must reach the remote before calling Square.
        result = send(client, key, text)
        rows[identity].update(result)
        checkpoint(state)
        attempted += 1
        if result["status"] != "sent":
            break  # Avoid hammering an expired/restricted key or daily cap.
    counts = {status: sum(row["status"] == status for row in rows.values())
              for status in ("sent", "pending", "unknown", "rejected", "blocked")}
    return {"status": "attention" if any(counts[s] for s in counts if s != "sent") else "ok",
        "date": date, "selected": len(seen), "attempted": attempted,
        "remaining": sum(identity not in rows for identity in seen), **counts}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--edition", type=Path, required=True)
    parser.add_argument("--queue-dir", type=Path, required=True)
    parser.add_argument("--edition-date", default="")
    args = parser.parse_args()
    if os.getenv("SQUARE_ENABLED") != "true" or not os.getenv("BINANCE_SQUARE_OPENAPI_KEY", "").strip():
        print("Square disabled or posting key missing; nothing sent.")
        return
    try:
        edition = json.loads(args.edition.read_text())
        state = read_state(args.queue_dir / "queue.json")
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            report = distribute(edition, state, now=datetime.now(SHANGHAI), client=client,
                key=os.environ["BINANCE_SQUARE_OPENAPI_KEY"].strip(),
                checkpoint=lambda value: git_checkpoint(args.queue_dir, value), explicit_date=args.edition_date)
        output = json.dumps(report, ensure_ascii=False)
        print(output)
        if os.getenv("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
                summary.write("\n## Binance Square\n\n```json\n" + output + "\n```\n")
        if report["status"] == "attention":
            raise SystemExit(1)
    except (ValueError, OSError, subprocess.CalledProcessError):
        # Neither subprocess stderr nor API responses are safe to echo.
        print("Square stopped: invalid state/input or checkpoint failure. No automatic retry.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
