"""Offline repository governance checks; never query credentials or production."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tomllib
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
OWNED_DOCS = [
    "AGENTS.md", "agent.md", "CLAUDE.md", "GEMINI.md",
    "project-docs/codex-collaboration.md", "project-docs/handoff.md",
    "project-docs/backlog.md", "project-docs/ui-rules.md",
    "project-docs/data-contract.md",
]
POINTER = "<!-- execution-pointer -->"
FIELDS = {"goal", "issue", "owner", "branch", "last_verified_commit", "pr",
          "completed", "unfinished", "validation", "unverified", "production",
          "blockers", "next_action", "states", "evidence"}
STATES = {"code", "tests", "pr_merged", "deployed", "production_verified"}


def changed_paths(root, base, head):
    # Refs come from GitHub SHA environment variables, never interpolated shell.
    for value in (base, head):
        if not re.fullmatch(r"[0-9a-f]{40}", value):
            raise ValueError("base/head must be exact commit SHAs")
    return subprocess.check_output(
        ["git", "diff", "--name-only", "--diff-filter=ACMRD", f"{base}...{head}"],
        cwd=root, text=True,
    ).splitlines()


def check_change_evidence(paths, root=None):
    application = any(
        p.startswith(("src/", "docs/", "ops/", "data/"))
        or p in {"VERSION", "pyproject.toml", "uv.lock"}
        or p.startswith(".github/workflows/")
        for p in paths
    )
    errors = []
    if application:
        if "project-docs/handoff.md" not in paths:
            errors.append("application PR must update project-docs/handoff.md")
        if not any(p.startswith("project-docs/releases/") and p.endswith(".md")
                   and (root is None or (root / p).is_file()) for p in paths):
            errors.append("application PR must include a release/verification record")
    return errors


def local_links(root, relative):
    path = root / relative
    if not path.exists():
        return [f"missing document: {relative}"]
    text = path.read_text()
    # Ignore fenced code examples. Validate links, not prose URL examples.
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    errors = []
    for match in re.finditer(r"!?\[[^\]]*\]\(([^)]+)\)", text):
        target = match.group(1).strip().strip("<>")
        if urlsplit(target).scheme or target.startswith("//") or not target:
            continue
        target = unquote(target.split("#", 1)[0])
        if not target:
            continue
        resolved = (path.parent / target).resolve()
        if not resolved.is_relative_to(root.resolve()) or not resolved.exists():
            errors.append(f"{relative}: broken local link {target}")
    return errors


def check(root=ROOT, changed=()):
    errors = []
    try:
        version = (root / "VERSION").read_text().strip()
        if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", version):
            errors.append("VERSION must be a semantic version")
        project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
        lock = tomllib.loads((root / "uv.lock").read_text())
        own = [p["version"] for p in lock["package"] if p["name"] == project["name"]]
        if project["version"] != version or own != [version]:
            errors.append("VERSION, pyproject.toml and uv.lock application version differ")
        release = root / f"project-docs/releases/{version}.md"
        if not release.exists() or f"Version: {version}" not in release.read_text().splitlines():
            errors.append("missing matching application version release note")
        package = json.loads((root / "ops/daily-dispatcher/package.json").read_text())
        npm_lock = json.loads((root / "ops/daily-dispatcher/package-lock.json").read_text())
        if not (package["version"] == npm_lock["version"] == npm_lock["packages"][""]["version"]):
            errors.append("dispatcher package/lock versions differ")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f"invalid version files: {exc}")

    try:
        text = (root / "project-docs/handoff.md").read_text()
        if text.count(POINTER) != 1:
            raise ValueError("handoff must contain exactly one execution pointer")
        match = re.search(r"<!-- execution-pointer -->\s*```json\s*(.*?)\s*```", text, re.S)
        pointer = json.loads(match.group(1)) if match else {}
        if set(pointer) != FIELDS:
            raise ValueError("handoff pointer fields missing or unknown")
        for name in FIELDS - {"states", "production"}:
            value = pointer[name]
            if name in {"completed", "unfinished", "validation", "unverified", "blockers"}:
                if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
                    raise ValueError(f"{name} must be a list of nonempty strings")
            elif not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a nonempty string")
        if not re.fullmatch(r"https://github.com/ohxiyu/bmtnews-standalone/issues/\d+", pointer["issue"]):
            raise ValueError("pointer must reference a task Issue in this repository")
        if not pointer["branch"].startswith("agent/"):
            raise ValueError("pointer branch must be agent/*")
        if not re.fullmatch(r"[0-9a-f]{40}", pointer["last_verified_commit"]):
            raise ValueError("last_verified_commit must be an exact SHA")
        states = pointer["states"]
        if not isinstance(states, dict) or set(states) != STATES or any(s not in {"pending", "complete", "not_required"} for s in states.values()):
            raise ValueError("invalid five-stage delivery states")
        for later, earlier in (("tests", "code"), ("pr_merged", "tests"), ("deployed", "pr_merged"), ("production_verified", "deployed")):
            if states[later] == "complete" and states[earlier] != "complete":
                raise ValueError(f"{later} complete requires {earlier} complete")
        production = pointer["production"]
        required = {"source_commit", "artifact_commit", "edition", "generated_at", "worker_version", "verified_at"}
        if set(production) != required or any(not isinstance(x, str) or not x.strip() for x in production.values()):
            raise ValueError("production snapshot must state all fields, including unknowns")
        evidence = (root / pointer["evidence"]).resolve()
        if not evidence.is_relative_to((root / "project-docs/releases").resolve()) or not evidence.is_file():
            raise ValueError("handoff must link a release evidence file")
        if states["deployed"] == "complete":
            # Real deployment evidence is reviewed by humans; these are minimum
            # structural fields, not proof that a deployment actually happened.
            body = evidence.read_text()
            for label in ("Source commit:", "Worker version:", "Deployment:", "Verification:", "Rollback:"):
                if not re.search(r"^" + re.escape(label) + r"\s*\S+", body, re.M):
                    raise ValueError(f"deployment evidence missing {label}")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f"invalid handoff: {exc}")

    docs = set(OWNED_DOCS)
    docs.update(str(p.relative_to(root)) for p in (root / "project-docs/releases").glob("*.md"))
    docs.update(p for p in changed if p.endswith(".md") and (root / p).exists())
    for path in sorted(docs):
        errors.extend(local_links(root, path))
    for entry in ("agent.md", "CLAUDE.md", "GEMINI.md"):
        path = root / entry
        if path.exists() and ("AGENTS.md" not in path.read_text() or len(path.read_text().splitlines()) > 12):
            errors.append(f"{entry} must remain a short shared-rule entry")
    errors.extend(check_change_evidence(changed, root))
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base")
    parser.add_argument("--head")
    args = parser.parse_args()
    if bool(args.base) != bool(args.head):
        parser.error("--base and --head must be supplied together")
    try:
        paths = changed_paths(ROOT, args.base, args.head) if args.base else []
        errors = check(changed=paths)
    except (ValueError, subprocess.CalledProcessError) as exc:
        errors = [str(exc)]
    if errors:
        print("\n".join(f"ERROR: {error}" for error in errors))
        return 1
    print("Governance checks passed (versions, local file links, execution pointer, PR evidence).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
