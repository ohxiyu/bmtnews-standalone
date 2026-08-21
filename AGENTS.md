# BMTNews Collaboration Rules

These rules apply to every human or coding agent working in this repository.
Detailed onboarding and command examples are in
[`project-docs/codex-collaboration.md`](project-docs/codex-collaboration.md).

## Source of truth

- `origin/main` is the only source of truth for application code.
- Never commit or push directly to `main`.
- Never edit `gh-pages` manually. It is generated exclusively by the
  `BMTNews Feed Update` workflow.
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

1. Confirm the worktree has no unrelated changes with `git status -sb`.
2. Run `git fetch origin`.
3. Create the task branch from `origin/main`, not from a stale local branch.
4. State the intended files and behavior before making changes.

Do not overwrite, discard, reset, or silently include changes created by
another user or agent.

## Change boundaries

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
