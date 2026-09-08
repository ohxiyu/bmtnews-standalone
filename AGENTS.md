# BMTNews Collaboration Rules

These rules apply to every human or coding agent working in this repository.
Detailed onboarding and command examples are in
[`project-docs/codex-collaboration.md`](project-docs/codex-collaboration.md).

## Source of truth

- `origin/main` is the only source of truth for application code.
- Never commit or push directly to `main`.
- Never edit `gh-pages` manually. It is generated exclusively by the
  publication workflows (Daily Edition, Feed Collection, Deploy Docs and related
  archive/weekly workflows).
- Do not merge `gh-pages` into `main`.

## One task, one owner, one branch

- Each task must have exactly one editing owner, one branch, one worktree, and
  one pull request.
- Use branches named `agent/<short-task-name>`.
- Do not let multiple Codex sessions edit the same worktree or branch.
- A second agent may review a task, but it must not edit the task branch unless
  ownership is explicitly transferred.
- Tasks that modify the same core module or depend on each other must be done
  sequentially. Merge the first pull request before starting the dependent
  branch from the new `origin/main`.

## Before editing

Read this file, `agent.md`, `project-docs/handoff.md`, the assigned Issue and
relevant UI/data rules first. Handoff contains one Current execution pointer;
backlog is not authorization to execute every task. Verify remote main, open
Issues/PRs, claims and live version before trusting any recorded snapshot.
If the user specifies a new task, update the pointer rather than continuing
stale unfinished work. Explain current state, next action and no-touch scope.

1. Confirm the worktree has no unrelated changes with `git status -sb`.
2. Run `git fetch origin`.
3. Create the task branch from `origin/main`, not from a stale local branch.
4. State the intended files and behavior before making changes.

Do not overwrite, discard, reset, or silently include changes created by
another user or agent.

## Change boundaries

- Python 3.11+ with uv is the application stack; static Pages content lives in
  `docs/`, and the independent TypeScript dispatcher lives in `ops/daily-dispatcher/`.
- Keep project process documents in `project-docs/`, not the publicly deployed
  `docs/` directory. See [document ownership](project-docs/codex-collaboration.md).
- Default delivery is a PR only. Merge or production deployment needs explicit
  authorization for the current task; prior chat/deployment approval does not
  carry forward. A document cannot grant permissions or inherit account login.
- Preserve existing services, schedules and spend limits. No new paid services,
  plans, model upgrades, quota increases or added external auth without approval.
  Do not invent a zero-cost guarantee for existing AI/provider usage.
- Claim a bounded Issue before implementation: one owner, file scope,
  acceptance criteria, dependencies, branch/worktree and deployment authority.
  One explicitly designated integrator serializes production changes. Other
  agents never assume merge/deploy authority from their assigned code task.
- Do not remove upstream notices, copyright or licenses without a separate
  rights review and authorization.

- Keep each pull request focused on one task.
- Update `uv.lock` only when dependencies change.
- Never commit API keys, `.env` files, credentials, private URLs, or copied
  production secrets.
- Do not commit generated daily state or summaries from a local run unless the
  task explicitly concerns a checked-in fixture.
- Preserve the Asia/Shanghai daily-feed boundary and the automated deployment
  path unless the task explicitly changes them.

## Required validation

Run the checks that match the change. The default full validation is:

```bash
uv sync --frozen --extra dev
uv run pytest
uv run python scripts/check_governance.py
```

Before a pull request is merged:

1. Run `git fetch origin`.
2. Merge `origin/main` into the task branch.
3. Resolve both text conflicts and behavior conflicts.
4. Run the relevant tests again.
5. Push the updated task branch.
6. Confirm the required GitHub checks pass.

Do not force-push unless the repository owner explicitly authorizes it.

## Pull requests

- Pull request direction must be `base: main` and
  `compare: agent/<short-task-name>`.
- Describe scope, user impact, deployment impact, and validation evidence.
- Do not combine unrelated cleanup with the requested change.
- Do not merge while required checks are pending or failing.
- After merge, delete the remote task branch and remove its local worktree.
- Application PRs must update `project-docs/handoff.md` and add/update a record
  in `project-docs/releases/`. Keep code complete, tests passed, PR merged,
  deployed and production verified as five distinct states. Record unfinished
  work, unverified claims, exact evidence and next action even when blocked.
- Preserve unfinished work on its task branch and Draft PR; never force a merge
  just to hand off. Verify ancestry before deleting a merged branch/worktree.
- VERSION is the application version and must agree with pyproject.toml and
  the bmtnews package in uv.lock plus its release note. Worker package versions
  are independent but package.json and both package-lock root versions must agree.
- CI validates version/link/pointer structure and changed-path handoff evidence.
  It cannot prove facts, deployment authority or live behavior; reviewers must
  inspect linked evidence. After authorized deployment, update the release record
  and pointer through a follow-up documentation PR, never a direct main commit.
