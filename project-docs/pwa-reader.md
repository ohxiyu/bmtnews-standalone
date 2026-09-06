# PWA reader: stages 1–3

The website and installed app share the same pages and design tokens. This layer
does not change collection schedules, AI analysis, publishing, or authentication.

## Reader behavior

- Public pages use network-first navigation with a 3.5-second deadline. An offline
  copy shows its save time; pages never visited show an honest offline fallback.
- The homepage already contains two full days. Their canonical daily pages are
  also warmed. Other detail pages are saved on visits, not crawled in advance.
- Cache limits are 30 pages, 20 MiB of HTML and 30 days. Each HTML snapshot requires
  its matching versioned CSS/JS before it is committed. Orphaned asset versions
  are pruned. Browser storage pressure can evict these caches at any time.
- Admin, source operations, APIs, credential-bearing requests, unknown query
  parameters, private/no-store responses, unrelated redirects and error pages are
  not saved. Cloudflare's dated `.html` → extensionless canonical redirect is
  accepted only when both URLs resolve to the same public offline key.
  Online navigation preserves the request's redirect mode: the browser follows
  redirects itself, and opaque redirect responses are never saved. Background
  warming may follow redirects subject to the public-key check above.
  A server 401, 403 or 404 is never replaced by an old saved page.
- `/pwa-version.json` and `/service-worker.js` bypass edge cache. On open/resume,
  the client checks for a new build and offers a user-controlled refresh. Updates
  never force a reload while reading. No background sync or push is introduced.
- “阅读 / Saved” opens a device-local library with page/story bookmarks, a continue
  action, cache status and separate cache/reading-data cleanup controls. Bookmarking
  records a link, not a guarantee that the target's full page is offline.
- Story identity is derived from canonical source URL + language, not list rank.
  Read state is tied to the current content revision. Reading position uses story
  identity + relative offset. The dated edition is a fallback when a story leaves
  the current two-day feed. Native back/forward-cache restoration is respected.
- Reading data is bounded to 200 bookmarks, 1,000 read markers and 20 positions.
  It stays on this device; clearing browser data or uninstalling may lose it.
- The four-section bottom navigation appears only on small standalone displays.
  Normal browser and desktop navigation remain unchanged. Installation prompts
  continue to use native browser support or the existing iOS instructions.

## Validation and maintenance

Run `uv run pytest` and the following frontend suite:

```sh
node --test tests/test_pwa_*.mjs tests/test_agent_worker.mjs tests/test_story_card.mjs
```

The PWA tests cover the
route/security boundary, online manual redirects (including browser response
validation), offline fallback, timeout, version mismatch, retained
asset versions, cache limits, clearing races, local storage failures, stable
identity and revision-aware read markers. These run in PR CI.

After changing CSS/JS, update the aggregate `asset_version` in both config files
as enforced by `test_agent_readiness.py`. Jekyll emits a fresh build timestamp in
HTML, the version endpoint and service worker. Use normal PR → main → Deploy Docs
→ Cloudflare publishing; never modify the generated gh-pages branch manually.

Acceptance in a secure-context browser: save a story, mark it read, navigate to its
dated edition, reopen the library, stop the local server and reload a saved page.
Verify cached timestamp, working styles, an uncached-page fallback and clear-cache
behavior. Publish a changed local build and verify the update remains opt-in.
Check narrow layouts and desktop navigation. A real iOS/Android home-screen install
still requires a physical-device acceptance pass; desktop emulation is not proof.

## Initial implementation acceptance

Local browser checks confirmed saved/read state across the home and dated edition,
detail-page bookmarks, and restoration of the same story at the saved scroll offset.
With the HTTP server stopped, both daily editions remained readable with their
styles and a visible save time. Clearing the cache preserved bookmarks and changed
the subsequent offline navigation to the uncached-page fallback. A new Jekyll build
remained opt-in; accepting it loaded the new build and restored the same story.
Chinese and English layouts were checked down to 320 px, including the four section
indexes. A standalone CSS fixture at 390 px verified four 52 px-high bottom targets,
hidden duplicate top navigation and no sideways overflow; it is not a device test.
Production acceptance additionally covers Cloudflare's canonical dated URLs and
the transient first-install waiting state, which must not trigger an update prompt.

## Online redirect regression

Run `node tests/fixtures/pwa_navigation_server.mjs`, open
`http://127.0.0.1:4178/`, and wait for the visible "Worker controlling" status.
The fixture serves the actual reader and service worker with Pages-style 308
redirects. Click both dates and the English date, refresh, return home, and visit
the three other sections. Stop the server, reload and click a dated `.html` link:
the saved page and timestamp must remain visible. This was verified in a real
browser, in addition to unit tests that fail against the old redirect-following
implementation. The fixture is not a substitute for post-deployment date clicks.

This worker-only fix preserves cache names and reading data. Jekyll's build
timestamp and changed service-worker bytes trigger the existing opt-in update
flow; no asset fingerprint bump or cache purge is needed.
