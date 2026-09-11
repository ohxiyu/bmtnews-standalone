"""Independent, no-AI Square distribution with durable pre-send checkpoints.

Unknown outcomes are NEVER automatically retried: the API offers no documented
idempotency key or lookup. A crash after checkpoint leaves a visible pending row.
"""
from __future__ import annotations

import argparse
import hashlib
import json
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
    from .square_plan import load
    return load(path)


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




def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--edition", type=Path)
    parser.add_argument("--queue-dir", type=Path, required=True)
    parser.add_argument("--edition-date", default="")
    args = parser.parse_args()
    if os.getenv("SQUARE_ENABLED") != "true" or not os.getenv("BINANCE_SQUARE_OPENAPI_KEY", "").strip():
        print("Square disabled or posting key missing; nothing sent.")
        return
    try:
        from .square_plan import load, sync_plan, drain
        state = load(args.queue_dir / "queue.json")
        now = datetime.now(SHANGHAI)
        checkpoint = lambda value: git_checkpoint(args.queue_dir, value)
        if args.edition:
            sync_plan(json.loads(args.edition.read_text()), state, now, compose, story_key,
                      checkpoint, args.edition_date)
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            report = drain(state, now, client, os.environ["BINANCE_SQUARE_OPENAPI_KEY"].strip(),
                           checkpoint, send, args.edition_date)
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
