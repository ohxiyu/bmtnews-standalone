# PR87 合并部署与重刊阻塞

Source commit: bd6f5c307b14c9f26d5cd5fc157b168c6118d8b7 (PR87 merge).

Worker version: Cloudflare Pages fb6f0ff7-5623-474f-bd77-afc6ecbfbfff; independent dispatcher not changed / unknown in this verification.

Deployment: main Cloudflare Pages check succeeded. [PR87](https://github.com/ohxiyu/bmtnews-standalone/pull/87). [Daily Edition](https://github.com/ohxiyu/bmtnews-standalone/actions/runs/35055901908) attempts 1 and 2 failed before publication. This is code deployment, NOT successful edition republication.

Verification: 2026-09-16 12:36 Asia/Shanghai. Local frozen sync, 785 pytest tests (one existing google-genai warning), governance and diff checks passed; PR test/analyze/CodeQL/governance/Pages checks passed before merge. Public https://bmt.news/api/latest.json still has 14 items, generated_at 2026-09-16T00:36:20.538116Z. Its first three CoinEx shutdown stories remain duplicated. Generated branch stays at 527f82e86a1c8769e8aaa5a2bee128736ce19c2f. Do not describe the ranking fix as live-accepted.

Both forced edition runs used the fixed 2026-09-16 window. Failure: Semantic dedup unavailable: refusing to publish unchecked content. Stack: run_daily_edition -> filter_items -> merge_topic_duplicates -> duplicate_groups. This is the early topic stage, before the new final ranking audit. Attempt 1 counted 232 candidates, 204 cached analyses, 28 new analyses, and five metered topic_dedup calls. These counts do not reveal whether the terminal failure was provider-side or schema validation. The exception wrapper discards its cause; do not guess or loosen validation. No Telegram/X publication stage was reached by these attempts.

X queue remains version 1, date 2026-09-16, posted.zh=[1], without selection_keys. No queue was cleared, remapped, or manually edited. New code deliberately pauses the remaining legacy day; next-date behavior is covered by tests but has not yet been observed live. Existing social posts are untouched. Square behavior is outside this release.

Rollback: previous code source 6c1687c777620f11d0cb1145bc729414fa0beeb4 and existing generated artifact 527f82e86a1c8769e8aaa5a2bee128736ce19c2f are reference snapshots. If rollback is authorized, revert through a new reviewed PR and normal deployment; never edit gh-pages or erase X/Square history. Rolling back code alone would restore the known dedup defect and is not recommended without evidence.

## Remaining work

- Add bounded, sanitized diagnostic reason codes for failed comparisons (no credentials or raw model response); reproduce the failure and test the targeted fix.
- Keep the semantic gate fail-closed, model/spend limits unchanged; avoid repeated uninformative paid retries.
- After reviewed repair, republish through Daily Edition, verify unique top events, category caps, score order and public artifact consistency.
- This documentation PR only records evidence; it does not silently include a new code fix or claim completed production acceptance.
