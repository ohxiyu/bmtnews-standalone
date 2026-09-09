"""Publish the manual Quick Post stream without collection or AI calls.

The private/editorial registry remains in Git. Only an explicit public field
allowlist is emitted; drafts and internal notes never enter the public API.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import html
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from ._file_utils import _atomic_write_text


def public_posts(payload: object, today: date) -> list[dict]:
    rows = payload.get("items", []) if isinstance(payload, dict) else []
    result = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("type") != "quick_post" or row.get("enabled") is not True:
            continue
        try:
            day = date.fromisoformat(row["date"])
        except (KeyError, TypeError, ValueError):
            continue
        identity, body = row.get("id"), row.get("body")
        if not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9-]{36}", identity) or identity in seen:
            continue
        if not isinstance(body, str) or not body.strip() or len(body) > 10000:
            continue
        if not today - timedelta(days=1) <= day <= today:
            continue
        url = str(row.get("url") or "")
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
                url = ""
        except ValueError:
            url = ""
        image = str(row.get("image") or "")
        if not re.fullmatch(r"/assets/uploads/quick-[a-f0-9]{64}\.(png|jpg|webp)", image):
            image = ""
        seen.add(identity)
        result.append({
            "id": identity, "body": body.strip(), "url": url, "image": image,
            "date": day.isoformat(), "category": str(row.get("category") or ""),
            "pin": row.get("pin") is True, "breaking": row.get("breaking") is True,
            "created_at": str(row.get("created_at") or ""),
            "updated_at": str(row.get("updated_at") or ""),
        })
    return sorted(result, key=lambda row: (row["date"], row["pin"], row["created_at"], row["id"]), reverse=True)


def render_posts(items: list[dict]) -> str:
    if not items:
        return ""
    parts = ['<section class="quick-post-stream" aria-label="Quick Post"><h2>Quick Post</h2>']
    for item in items:
        esc = lambda value: html.escape(str(value), quote=True)
        badges = (" · Breaking" if item["breaking"] else "") + (" · PIN" if item["pin"] else "")
        parts.append(f'<article class="quick-post-public" id="quick-{esc(item["id"])}">'
                     f'<small>BMTNews · {esc(item["date"])}{badges}</small>')
        for paragraph in re.split(r"\n\s*\n", item["body"]):
            parts.append(f'<p>{esc(paragraph).replace(chr(10), "<br>")}</p>')
        if item["image"]:
            parts.append(f'<img src="{esc(item["image"])}" alt="Quick Post 配图" loading="lazy">')
        if item["url"]:
            parts.append(f'<a href="{esc(item["url"])}" target="_blank" rel="noopener noreferrer">Source ↗</a>')
        parts.append("</article>")
    parts.append("</section>")
    return "\n".join(parts)


def publish(source: Path, output: Path, today: date) -> None:
    # A corrupt registry must fail the build, not erase the public stream.
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("Invalid editorial registry")
    items = public_posts(payload, today)
    (output / "api").mkdir(parents=True, exist_ok=True)
    (output / "_data").mkdir(parents=True, exist_ok=True)
    _atomic_write_text(output / "api/quick-posts.json", json.dumps(
        {"version": 1, "date": today.isoformat(), "items": items}, ensure_ascii=False) + "\n")
    # JSON strings are output as text by Liquid, not re-parsed as Liquid code.
    _atomic_write_text(output / "_data/quick_posts.json", json.dumps(
        {"html": render_posts(items)}, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("data/editorial.json"))
    parser.add_argument("--output", type=Path, default=Path("docs"))
    parser.add_argument("--date", type=date.fromisoformat)
    args = parser.parse_args()
    publish(args.source, args.output, args.date or datetime.now(ZoneInfo("Asia/Shanghai")).date())


if __name__ == "__main__":
    main()
