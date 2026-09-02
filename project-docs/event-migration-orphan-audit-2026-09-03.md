# Historical legacy-page audit

## Finding

The reviewed production snapshot at `ebabcd313633767126e49370cb1a47622b9e78d8` contained 22 active legacy threads in `_data/threads.json`, and all 22 were covered by the approved event migration. Deployment verification also found one older page, `/threads/t4eace9a087/`, that remained on `gh-pages` because deployments preserve files that are not regenerated.

The page was created at `b5af1dc8c1a0030d7ea83c731d3d44974325b031`. Its ATLAS source record was removed from the archive by `633657b35f516424bc1153a877af24b6c02ba192`, so the page was absent from the active thread index and from the 178-record migration input even though its URL still resolved publicly.

## Reviewed handling

The old page incorrectly grouped two reports that share the LayerZero entity but do not describe one evolving event:

1. LayerZero losing ecosystem partners remains a canonical singleton event in the migrated archive at `/events/evt_50b9754707140701/`.
2. The ATLAS product announcement is not present in the reviewed production archive. Its original source link is preserved explicitly as a historical source instead of fabricating an archive record or merging it into the partner-loss event.

Both language variants are replaced by noindex retired indexes. This keeps the bookmarked URLs working, states why the old grouping was wrong, and avoids inventing a timeline update from missing source data.

## Verification contract

- The machine-readable manifest is `data/historical-legacy-pages.json`.
- Both `/threads/t4eace9a087/` and `/en/threads/t4eace9a087/` must exist after migration deployment.
- The canonical event target must exist in `_data/events.json`.
- The historical ATLAS source URL must remain present on both compatibility pages.
- The guarded migration workflow verifies these conditions together with the 22 active legacy URL mappings.
