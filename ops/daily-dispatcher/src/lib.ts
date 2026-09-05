const PRIMARY_CRON = "30 0 * * *";
const FINAL_CRON = "10 1 * * *";
const PERMISSION_PROBE_REF =
  "refs/heads/__bmtnews_permission_probe__/invalid..ref";
export const ACTIVE_STATUSES = new Set([
  "queued",
  "in_progress",
  "waiting",
  "pending",
  "requested",
]);

type TriggerStage = "primary" | "retry-1" | "retry-2" | "final";

interface WorkflowRun {
  status: string;
  conclusion: string | null;
  headBranch: string;
  startedAt: Date;
  htmlUrl: string | null;
}

interface EditionContext {
  date: string;
  cutoffUtc: Date;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredString(
  value: unknown,
  field: string,
  allowEmpty = false,
): string {
  if (typeof value !== "string" || (!allowEmpty && value.length === 0)) {
    throw new Error(`GitHub response field ${field} is invalid`);
  }
  return value;
}

function optionalString(value: unknown, field: string): string | null {
  if (value === null) {
    return null;
  }
  return requiredString(value, field, true) || null;
}

function parseTimestamp(value: unknown, field: string): Date {
  const parsed = new Date(requiredString(value, field));
  if (Number.isNaN(parsed.getTime())) {
    throw new Error(`GitHub response field ${field} is not a timestamp`);
  }
  return parsed;
}

function parseWorkflowRun(value: unknown): WorkflowRun {
  if (!isRecord(value)) {
    throw new Error("GitHub workflow run is not an object");
  }
  const startedAt =
    value.run_started_at ?? value.created_at ?? value.updated_at;
  return {
    status: requiredString(value.status, "status"),
    conclusion: optionalString(value.conclusion, "conclusion"),
    headBranch: requiredString(value.head_branch, "head_branch"),
    startedAt: parseTimestamp(startedAt, "run_started_at"),
    htmlUrl: optionalString(value.html_url, "html_url"),
  };
}

function parseWorkflowRuns(value: unknown): WorkflowRun[] {
  if (!isRecord(value) || !Array.isArray(value.workflow_runs)) {
    throw new Error("GitHub response is missing workflow_runs");
  }
  return value.workflow_runs.map(parseWorkflowRun);
}

function stageForCron(cron: string): TriggerStage {
  const stages: Record<string, TriggerStage> = {
    [PRIMARY_CRON]: "primary",
    "40 0 * * *": "retry-1",
    "55 0 * * *": "retry-2",
    [FINAL_CRON]: "final",
  };
  const stage = stages[cron];
  if (stage === undefined) {
    throw new Error(`Unsupported Cron Trigger: ${cron}`);
  }
  return stage;
}

function zonedParts(
  moment: Date,
  timezoneName: string,
): Record<string, number> {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezoneName,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
  const result: Record<string, number> = {};
  for (const part of formatter.formatToParts(moment)) {
    if (
      part.type === "year" ||
      part.type === "month" ||
      part.type === "day" ||
      part.type === "hour" ||
      part.type === "minute" ||
      part.type === "second"
    ) {
      result[part.type] = Number(part.value);
    }
  }
  return result;
}

function requirePart(parts: Record<string, number>, name: string): number {
  const value = parts[name];
  if (value === undefined || !Number.isInteger(value)) {
    throw new Error(`Timezone conversion is missing ${name}`);
  }
  return value;
}

function zonedLocalToUtc(
  date: string,
  hour: number,
  timezoneName: string,
): Date {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (match === null) {
    throw new Error(`Invalid edition date: ${date}`);
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const targetWallTime = Date.UTC(year, month - 1, day, hour);
  let candidate = targetWallTime;

  for (let attempt = 0; attempt < 3; attempt += 1) {
    const parts = zonedParts(new Date(candidate), timezoneName);
    const observedWallTime = Date.UTC(
      requirePart(parts, "year"),
      requirePart(parts, "month") - 1,
      requirePart(parts, "day"),
      requirePart(parts, "hour"),
      requirePart(parts, "minute"),
      requirePart(parts, "second"),
    );
    candidate += targetWallTime - observedWallTime;
  }
  return new Date(candidate);
}

export function editionContextFor(
  scheduledTime: number,
  timezoneName: string,
  cutoffHour: number,
): EditionContext {
  if (!Number.isInteger(cutoffHour) || cutoffHour < 0 || cutoffHour > 23) {
    throw new Error("EDITION_CUTOFF_HOUR must be an integer from 0 to 23");
  }
  const parts = zonedParts(new Date(scheduledTime), timezoneName);
  const date = [
    String(requirePart(parts, "year")).padStart(4, "0"),
    String(requirePart(parts, "month")).padStart(2, "0"),
    String(requirePart(parts, "day")).padStart(2, "0"),
  ].join("-");
  return {
    date,
    cutoffUtc: zonedLocalToUtc(date, cutoffHour, timezoneName),
  };
}

function githubHeaders(env: Env): HeadersInit {
  return {
    Accept: "application/vnd.github+json",
    Authorization: `Bearer ${env.GITHUB_DISPATCH_TOKEN}`,
    "Content-Type": "application/json",
    "User-Agent": "bmtnews-cloudflare-dispatcher",
    "X-GitHub-Api-Version": "2022-11-28",
  };
}

export async function githubRequest(
  env: Env,
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const response = await fetch(`https://api.github.com${path}`, {
    ...init,
    headers: {
      ...githubHeaders(env),
      ...init.headers,
    },
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok) {
    throw new Error(
      `GitHub API ${init.method ?? "GET"} ${path} returned HTTP ${response.status}`,
    );
  }
  return response;
}

async function verifyDispatchPermission(env: Env): Promise<void> {
  const repository = encodeURIComponent(env.GITHUB_REPOSITORY).replace(
    "%2F",
    "/",
  );
  const workflow = encodeURIComponent(env.GITHUB_WORKFLOW);
  const path = `/repos/${repository}/actions/workflows/${workflow}/dispatches`;
  const response = await fetch(`https://api.github.com${path}`, {
    method: "POST",
    headers: githubHeaders(env),
    body: JSON.stringify({ ref: PERMISSION_PROBE_REF }),
    signal: AbortSignal.timeout(10_000),
  });

  // GitHub checks Actions: write before resolving the ref. A write-capable
  // token reaches ref validation and gets 422 for this deliberately invalid
  // Git ref, while a read-only token gets 403. No workflow run is created.
  if (response.status !== 422) {
    throw new Error(
      `GitHub dispatch permission probe returned HTTP ${response.status}`,
    );
  }
}

export async function checkReadiness(env: Env): Promise<{
  status: "ready";
  repository: string;
  workflow: string;
  ref: string;
  dispatch_permission: "actions:write";
}> {
  if (!env.GITHUB_DISPATCH_TOKEN) {
    throw new Error("GITHUB_DISPATCH_TOKEN is not configured");
  }
  await verifyDispatchPermission(env);
  return {
    status: "ready",
    repository: env.GITHUB_REPOSITORY,
    workflow: env.GITHUB_WORKFLOW,
    ref: env.GITHUB_REF,
    dispatch_permission: "actions:write",
  };
}

export async function fetchWorkflowRuns(env: Env): Promise<WorkflowRun[]> {
  const repository = encodeURIComponent(env.GITHUB_REPOSITORY).replace(
    "%2F",
    "/",
  );
  const workflow = encodeURIComponent(env.GITHUB_WORKFLOW);
  const response = await githubRequest(
    env,
    `/repos/${repository}/actions/workflows/${workflow}/runs?per_page=30`,
  );
  return parseWorkflowRuns(await response.json());
}

export async function urlExists(url: string): Promise<boolean> {
  const response = await fetch(url, {
    method: "HEAD",
    headers: {
      "Cache-Control": "no-cache",
      "User-Agent": "bmtnews-cloudflare-dispatcher",
    },
    redirect: "follow",
    signal: AbortSignal.timeout(10_000),
  });
  if (response.status === 404) return false;
  if (!response.ok) throw new Error(`Publication probe returned HTTP ${response.status}`);
  return true;
}

export function publicationUrls(env: Env, editionDate: string): {
  raw: string[];
  rendered: string[];
} {
  const repository = env.GITHUB_REPOSITORY;
  const base = env.PUBLIC_SITE_URL.replace(/\/+$/, "");
  const [year, month, day] = editionDate.split("-");
  if (year === undefined || month === undefined || day === undefined) {
    throw new Error(`Invalid edition date: ${editionDate}`);
  }
  return {
    raw: ["zh", "en"].map(
      (language) =>
        `https://raw.githubusercontent.com/${repository}/gh-pages/_posts/` +
        `${editionDate}-summary-${language}.md`,
    ),
    rendered: ["zh", "en"].map(
      (language) =>
        `${base}/${year}/${month}/${day}/summary-${language}.html`,
    ),
  };
}


export const testing = {
  editionContextFor,
  publicationUrls,
  stageForCron,
  zonedLocalToUtc,
};
