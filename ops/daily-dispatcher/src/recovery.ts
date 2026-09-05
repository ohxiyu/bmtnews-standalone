import {
  ACTIVE_STATUSES, editionContextFor, fetchWorkflowRuns,
  githubRequest, publicationUrls, testing, urlExists,
} from "./lib";

export interface RecoveryResult {
  status: string;
  edition_date: string;
  checked_at: string;
  overdue: boolean;
  raw_ready?: boolean;
  public_ready?: boolean;
  items?: number;
  active_run_url?: string | null;
}

// Bound response bodies, including chunked responses, before parsing.
async function readBounded(response: Response, limit = 2_000_000): Promise<string> {
  const reader = response.body?.getReader();
  if (!reader) return "";
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit) throw new Error("Publication response exceeds limit");
      chunks.push(value);
    }
  } finally {
    await reader.cancel();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return new TextDecoder().decode(bytes);
}

async function getText(url: string): Promise<string | null> {
  let target = new URL(url);
  for (let redirects = 0; redirects <= 3; redirects++) {
    const response = await fetch(target, {
      headers: { "Cache-Control": "no-cache", Accept: "text/html, application/json" },
      redirect: "manual", signal: AbortSignal.timeout(10_000),
    });
    if ([301, 302, 303, 307, 308].includes(response.status)) {
      const location = response.headers.get("Location");
      if (!location) throw new Error("Publication redirect lacks Location");
      const next = new URL(location, target);
      if (next.origin !== target.origin) throw new Error("Publication redirect changed origin");
      // Pages canonicalizes .html to extensionless routes.
      next.searchParams.set("publication_check", new URL(url).searchParams.get("publication_check") ?? "");
      await response.body?.cancel();
      target = next;
      continue;
    }
    if (response.status === 404) return null;
    if (!response.ok) throw new Error("Publication probe failed: HTTP " + response.status);
    return readBounded(response);
  }
  throw new Error("Publication redirect limit exceeded");
}

function editionItems(text: string | null, date: string): number {
  if (text === null) return 0;
  // A soft 404 or corrupt JSON must not be mistaken for a missing edition
  // and cause an expensive publication. Fail closed and alert instead.
  const data: unknown = JSON.parse(text);
  if (typeof data !== "object" || data === null || !("date" in data) ||
      !("items" in data) || !Array.isArray(data.items)) {
    throw new Error("Invalid publication JSON");
  }
  return data.date === date ? data.items.length : 0;
}

function contentRevisions(text: string | null, language: "zh" | "en"): string[] | null {
  if (!text) return null;
  const data = JSON.parse(text);
  // Keep old editions readable until a normal publication adds the markers.
  if (data.content_revision_version !== 1) return null;
  return data.items.map((item: {content_revision?: Record<string, unknown>}) => {
    const revision = item.content_revision?.[language];
    if (typeof revision !== "string" || !/^[a-f0-9]{64}$/.test(revision)) {
      throw new Error("Invalid story content revision");
    }
    return revision;
  });
}

function renderedRevisionsMatch(html: string, expected: string[] | null): boolean {
  if (expected === null) return true;
  const actual = Array.from(html.matchAll(/data-content-revision="([a-f0-9]{64})"/g))
    .map((match) => match[1]);
  return actual.length === expected.length &&
    expected.every((revision, index) => actual[index] === revision);
}

export async function inspectPublication(env: Env, date: string, now: number) {
  const base = env.PUBLIC_SITE_URL.replace(/\/+$/, "");
  const nonce = "?publication_check=" + now;
  const rawBase = "https://raw.githubusercontent.com/" +
    env.GITHUB_REPOSITORY + "/gh-pages";
  const urls = publicationUrls(env, date);
  const [rawJson, rawPosts, publicJson, home] = await Promise.all([
    getText(rawBase + "/api/latest.json" + nonce),
    Promise.all(urls.raw.map((url) => urlExists(url + nonce))),
    getText(base + "/api/latest.json" + nonce),
    getText(base + "/" + nonce),
  ]);
  const items = editionItems(rawJson, date);
  const publicItems = editionItems(publicJson, date);
  const revisions = {
    zh: contentRevisions(rawJson, "zh"),
    en: contentRevisions(rawJson, "en"),
  };
  // Same date/count is not enough: compare the actual published payload.
  const samePayload = rawJson !== null && publicJson !== null &&
    JSON.stringify(JSON.parse(rawJson)) === JSON.stringify(JSON.parse(publicJson));
  const rawReady = items > 0 && rawPosts.every(Boolean);
  // Both latest marker and actual first-day article count must match. Old
  // articles from the second day cannot make an empty current day healthy.
  const firstDay = home?.split('<section class="daily-day"')[1]?.split(
    '<section class="daily-day"',
  )[0] ?? "";
  const homeItems = (firstDay.match(/<article class="digest-item(?:\s|")/g) ?? []).length;
  const homeReady = home?.includes('data-latest-edition-date="' + date + '"') &&
    firstDay.includes('data-date="' + date + '"') && homeItems >= items &&
    renderedRevisionsMatch(firstDay, revisions.zh);
  const rendered = rawReady && publicItems === items && samePayload && homeReady
    ? await Promise.all(urls.rendered.map(async (url, index) => {
        const html = await getText(url + nonce);
        return Boolean(html?.includes('data-date="' + date + '"') &&
          (html.match(/<article class="digest-item(?:\s|")/g) ?? []).length >= items &&
          renderedRevisionsMatch(html, index === 0 ? revisions.zh : revisions.en));
      }))
    : [false];
  return { rawReady, publicReady: Boolean(rawReady && rendered.every(Boolean)), items };
}

export async function runRecovery(
  env: Env, now: number, source: string,
): Promise<RecoveryResult> {
  const context = editionContextFor(now, env.EDITION_TIMEZONE, Number(env.EDITION_CUTOFF_HOUR));
  const elapsed = now - context.cutoffUtc.getTime();
  const result: RecoveryResult = {
    status: "not_due", edition_date: context.date,
    checked_at: new Date(now).toISOString(), overdue: elapsed >= 75 * 60_000,
  };
  // Cron starts at 08:30; external and backup checks cannot publish before it.
  if (elapsed < 30 * 60_000) return result;
  const gate = env.RECOVERY_GATE.getByName(context.date);
  const owner = await gate.claim(now);
  if (!owner) return { ...result, status: "check_in_progress" };
  try {
    const [assets, runs] = await Promise.all([
      inspectPublication(env, context.date, now), fetchWorkflowRuns(env),
    ]);
    Object.assign(result, {
      raw_ready: assets.rawReady, public_ready: assets.publicReady, items: assets.items,
    });
    if (assets.publicReady) return { ...result, status: "healthy" };
    // Also block on yesterday's queued/stuck run: submitting another one can
    // replace the single pending run in GitHub's concurrency group.
    const active = runs.find((run) =>
      run.headBranch === env.GITHUB_REF && ACTIVE_STATUSES.has(run.status));
    if (active) return {
      ...result,
      status: now - active.startedAt.getTime() >= 45 * 60_000
        ? "publication_stuck" : "publication_active",
      active_run_url: active.htmlUrl,
    };
    const kind = assets.rawReady ? "pages" : "daily";
    if (kind === "pages") {
      const seen = await gate.firstRawSeen(now);
      if (now - seen < 15 * 60_000) return { ...result, status: "pages_waiting" };
    }
    const claim = await gate.claimAction(owner, kind, now);
    if (claim !== "claimed") return { ...result, status: kind + "_" + claim };
    if (kind === "pages") {
      // The secret hook builds the current gh-pages HEAD, without invoking AI.
      const hook = new URL(env.PAGES_DEPLOY_HOOK);
      if (hook.origin !== "https://api.cloudflare.com" ||
          !hook.pathname.startsWith("/client/v4/pages/webhooks/deploy_hooks/")) {
        throw new Error("Invalid Pages recovery hook");
      }
      const response = await fetch(hook, {
        method: "POST", redirect: "manual", signal: AbortSignal.timeout(10_000),
      });
      if (!response.ok) throw new Error("Pages recovery hook failed");
    } else {
      await githubRequest(env,
        "/repos/" + env.GITHUB_REPOSITORY + "/actions/workflows/" +
          encodeURIComponent(env.GITHUB_WORKFLOW) + "/dispatches",
        { method: "POST", body: JSON.stringify({
          ref: env.GITHUB_REF,
          inputs: { edition_date: context.date, trigger_source: source },
        }) },
      );
    }
    return { ...result, status: kind + "_dispatched" };
  } finally {
    await gate.release(owner);
  }
}

export function responseStatus(result: RecoveryResult): number {
  if (result.status === "healthy" || result.status === "not_due") return 200;
  if (result.overdue || /stuck|retry_limit|lock_lost/.test(result.status)) return 503;
  return 202;
}

export async function runSchedule(cron: string, time: number, env: Env): Promise<void> {
  const stage = testing.stageForCron(cron);
  // A scheduler delivery delayed across midnight must not resurrect yesterday.
  const result = await runRecovery(env, Math.max(time, Date.now()), "cloudflare-" + stage);
  console.log(JSON.stringify({ event: "publication_check", source: stage, ...result }));
  if (responseStatus(result) === 503) throw new Error("Publication recovery needs attention");
}

export const recoveryTesting = { editionItems, contentRevisions, renderedRevisionsMatch };
