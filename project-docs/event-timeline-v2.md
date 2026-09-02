# BMTNews Event Timeline v2

This document is the durable implementation path for replacing the legacy
cross-day story threads with real event progression. The three phases must be
completed sequentially because each phase changes the assumptions of the next.

## Product contract

An event is a stable real-world incident, decision, release, transaction,
legal case, vote, or operational change. A timeline update is a material new
fact about that same root event. Multiple outlets repeating the same facts add
source confidence to an existing update; they do not create another point on
the timeline.

Every public event must eventually answer:

1. What is the event and what is its current status?
2. What materially changed at each point in time?
3. Which sources support each update?
4. Is the event still developing, resolved, disputed, or closed?

## Phase 1 — model and matching contract

Status: implemented in the first PR; deliberately not connected to production
publishing.

- Add stable `TrackedEvent` and `EventUpdate` models with timezone-aware
  timestamps, update types, status, sources, confidence, and current state.
- Retrieve candidate events only through hard identifiers, named entities, or
  multiple specific topic keys. Generic industry tags cannot open the gate.
- Classify each candidate as `same_event_update`, `duplicate_coverage`,
  `related_but_distinct`, or `unrelated` through a strict JSON contract.
- Allow unattended attachment only for same-event or duplicate decisions at
  confidence `>= 0.90`.
- Keep real production false-positive and false-negative examples as regression
  fixtures.

## Phase 2 — audited archive migration

Status: review draft prepared from production revision
`ebabcd313633767126e49370cb1a47622b9e78d8`; publishing remains blocked until
the owner approves the checked-in
[`event-migration-audit-2026-09-02.md`](event-migration-audit-2026-09-02.md).

The plan is checked in with `approved: false`. Both the CLI and tests enforce
that state as a write barrier: audit generation is allowed, while archive,
catalog, and legacy-URL output writes are refused.

- Build a deterministic event catalog from the published archive without
  modifying `gh-pages` during the dry run.
- Emit a review report containing every proposed merge, split, duplicate,
  uncertain relation, and legacy-thread redirect.
- Manually review the migration report before publishing it.
- Preserve legacy URLs through redirects or explicit retired-event pages.
- Make the migration idempotent and verify a second run produces no diff.
- Replace historical full-summary nodes with material-change updates and
  grouped source evidence wherever the archive supports that distinction.

Phase 2 acceptance target: at least 95% precision on reviewed event membership,
zero cross-protocol security-incident merges in the regression corpus, and no
duplicate-coverage nodes presented as progress.

## Phase 3 — reader experience and four-hour updates

Status: blocked on the reviewed Phase 2 catalog.

- Render a stable event title, current status, first/last change timestamps,
  and chronological update nodes.
- Show `what_changed`, update type, source evidence, and corrections instead of
  repeating full article summaries.
- Add event JSON endpoints and link daily stories to both `event_id` and
  `update_id`.
- Run event-only incremental analysis after each four-hour collection while
  retaining the daily edition boundary.
- Reuse cached story analysis and classify only newly retrieved candidates.
- Verify desktop/mobile/PWA rendering against migrated production data.

## Non-goals for Phase 1

Phase 1 does not rewrite archive records, alter the current `/threads/` pages,
change the daily publication window, add scheduled AI calls, or deploy a new
public API. Those changes require the reviewed catalog created in Phase 2.
