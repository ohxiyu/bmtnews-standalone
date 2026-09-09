# Source Registry and Management

BMTNews keeps the source registry at
[`https://bmt.news/s/sources/`](https://bmt.news/s/sources/), behind the same
email-only Cloudflare Access policy as Quick Post at /s/.

The page has no database or self-managed login service:

- reads `data/config.github.json` directly from `main`;
- lists source type, editorial track, category, effective status, and stable
  source key;
- filters and searches the current source registry;
- lets maintainers copy the exact source key needed for an update;
- never stores a GitHub token or writes production configuration.

The repository and source configuration remain public, but the management UI
and write dispatcher are authenticated. The address is not linked from the
public navigation. The browser never receives the server-side GitHub token.

## Maintainer workflow

1. Open /s/sources/ and use the source-change form after email verification.
2. Choose `add`, `update`, `pause`, `resume`, or `remove`.
3. For an existing source, copy its stable source key from the table.
4. Fill only the fields needed for the operation:
   - `add`: type, endpoint, category, state, reason, and an RSS name;
   - `update`: source key and any fields that should change;
   - `pause`, `resume`, or `remove`: source key and reason.
5. Submit the form. The authenticated server dispatches the existing workflow;
   the job verifies the GitHub token owner's repository permission again.
6. The workflow validates the request, public RSS endpoint, and complete
   Pydantic production configuration.
7. It creates a unique `agent/source-run-<run-id>-<attempt>` branch containing
   only the configuration change and opens a Draft PR to `main`.
8. If GitHub pauses checks on the bot-created PR, a maintainer clicks
   **Approve workflows to run**.
9. Merge only after the required `test` and `analyze` checks pass.

The Action run summary contains either the Draft PR URL or a precise validation
error. A no-op request does not create a branch.

## Supported changes

The workflow can add, edit, pause, resume, and remove these list entries:

- public RSS feeds;
- public Telegram channels;
- GitHub repository release feeds;
- Reddit subreddits.

Singleton collectors such as Hacker News, Google News, GDELT, and OSS Insight
can be paused or resumed. Query-specific settings still require a normal code
change because those structures contain collector-specific fields.

New or updated RSS URLs must use a public HTTP(S) endpoint. Requests containing
environment placeholders, credentials, loopback addresses, private network
addresses, or non-public DNS results are rejected.

## Operational boundaries

- Do not put API keys, cookies, private feeds, internal URLs, `.env` content,
  or production state in workflow inputs.
- Do not manually edit `gh-pages`; the existing GitHub Actions deployment path
  publishes the registry.
- The registry reflects `main`, so a merged configuration change appears after
  the raw file and Pages deployment caches refresh.
- A source change affects collection only after its PR is merged.
