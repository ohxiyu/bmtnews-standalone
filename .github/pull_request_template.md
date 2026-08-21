## Scope

Describe the single task completed by this pull request.

## User and deployment impact

Explain visible behavior changes, configuration changes, and whether the
scheduled feed or static-site deployment is affected.

## Validation

List the exact checks run and their results.

```text
uv sync --frozen --extra dev
uv run pytest
```

## Coordination checklist

- [ ] This pull request contains one task owned by one agent.
- [ ] The branch was created from `origin/main`.
- [ ] The latest `origin/main` was merged before final validation.
- [ ] Relevant tests pass locally and required GitHub checks pass.
- [ ] No unrelated changes, secrets, `.env` files, or generated daily state are included.
- [ ] `uv.lock` changed only if dependencies changed.
- [ ] `gh-pages` was not edited manually.
- [ ] Deployment and rollback considerations are documented above.
