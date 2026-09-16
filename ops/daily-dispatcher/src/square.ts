import { ACTIVE_STATUSES, fetchWorkflowRuns, githubRequest, SCHEDULE_CRONS } from "./lib";
import { runSchedule } from "./recovery";

export const SQUARE_CRON = "*/5 0-15 * * *";
export const CONFIGURED_CRONS = [SCHEDULE_CRONS[0], SCHEDULE_CRONS[1], SQUARE_CRON];

// Share one timer, but preserve the existing publication probe frequency.
export function publicationCron(time: number): string | null {
  const date = new Date(time);
  const hour = date.getUTCHours(), minute = date.getUTCMinutes();
  if (hour >= 0 && hour <= 3 && minute % 10 === 0) return "*/10 0-3 * * *";
  if (hour >= 4 && hour <= 15 && minute === 0) return "0 4-15 * * *";
  return null;
}

export async function dispatchSquare(env: Env, now: number): Promise<string> {
  const date = new Date(now);
  const minute = date.getUTCHours() * 60 + date.getUTCMinutes();
  if (minute < 60 || minute > 930) return "outside_window";
  const runs = await fetchWorkflowRuns(env, "square-distribution.yml");
  if (runs.some(run => run.headBranch === env.GITHUB_REF && ACTIVE_STATUSES.has(run.status))) {
    return "active";
  }
  await githubRequest(env,
    `/repos/${env.GITHUB_REPOSITORY}/actions/workflows/square-distribution.yml/dispatches`,
    { method: "POST", body: JSON.stringify({ ref: env.GITHUB_REF, inputs: { queue_only: true } }) });
  return "dispatched";
}

export async function runCombinedSchedule(cron: string, scheduledTime: number, env: Env): Promise<void> {
  if (cron !== SQUARE_CRON && cron !== "*/5 1-15 * * *") return runSchedule(cron, scheduledTime, env);
  const now = Math.max(scheduledTime, Date.now());
  // Publication failure must not prevent distribution, and vice versa.
  const publication = publicationCron(now);
  const results = await Promise.allSettled([
    dispatchSquare(env, now).then(status => console.log(JSON.stringify({ event: "square_dispatch", status }))),
    publication ? runSchedule(publication, now, env) : Promise.resolve(),
  ]);
  if (results.some(result => result.status === "rejected")) {
    throw new Error("Scheduled publication or Square dispatch failed; inspect workflow and dispatcher permissions");
  }
}
