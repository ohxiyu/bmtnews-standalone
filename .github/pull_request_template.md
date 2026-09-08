## Task and ownership

Closes #<!-- task Issue -->
Owner / branch / worktree:
Affected files and non-goals:
Overlapping tasks checked:

## User and deployment impact

Describe product impact, version changes (or why unchanged), scheduled jobs,
notifications and any production-data effects. Default: PR only.
Current-task merge/deployment authorization (or NOT AUTHORIZED):
Single production integrator:

## Handoff and evidence

- Current pointer: project-docs/handoff.md
- Release / verification record: project-docs/releases/<record>.md
- Code complete:
- Tests passed:
- PR merged:
- Production deployed:
- Live acceptance passed:

Use pending / complete / not_required, with reasons. Never mark downstream
states complete based only on upstream success.

## Validation

Exact commands and observed results, not just planned commands:

```text
uv sync --frozen --extra dev
uv run pytest
uv run python scripts/check_governance.py
```

Unfinished work / unverified behavior:
Blockers / required permissions (names only, never credentials):
Next concrete action:

## Deployment and rollback

Source commit / generated artifact commit:
Worker version (or not changed / unknown with reason):
Production deployment / Actions evidence:
Live URLs, timestamp, expected vs observed results:
Known-good rollback target and procedure:

## Coordination checklist

- [ ] One Issue, editing owner, task branch and worktree; no overlapping edits.
- [ ] Latest origin/main merged and relevant checks rerun.
- [ ] Handoff and verification record accurately include unfinished work.
- [ ] No secrets, .env, copied production state or unrelated changes.
- [ ] No manual main or gh-pages commits/pushes.
- [ ] Version manifests and release note agree within each component.
- [ ] test, analyze and governance checks pass before any authorized merge.
- [ ] Merge/deploy is authorized for this task, or explicitly left to the owner.
