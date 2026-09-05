import { checkReadiness } from "./lib";
import { runRecovery, runSchedule, responseStatus } from "./recovery";
import { timingSafeEqual } from "node:crypto";
export { RecoveryGate } from "./gate";
import {
  handleOAuthAuth,
  handleOAuthCallback,
  type OAuthEnv,
} from "./oauth";

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/publication/check") {
      if (request.method !== "POST") {
        return new Response(null, { status: 405, headers: { Allow: "POST" } });
      }
      const provided = new TextEncoder().encode(request.headers.get("Authorization") ?? "");
      const expected = new TextEncoder().encode("Bearer " + env.RECOVERY_CHECK_TOKEN);
      if (!env.RECOVERY_CHECK_TOKEN || provided.length !== expected.length ||
          !timingSafeEqual(provided, expected)) {
        return Response.json({ error: "Unauthorized" }, { status: 401 });
      }
      try {
        const result = await runRecovery(env, Date.now(), "publication-watchdog");
        console.log(JSON.stringify({ event: "publication_check", ...result }));
        return Response.json(result, {
          status: responseStatus(result), headers: { "Cache-Control": "no-store" },
        });
      } catch {
        console.error(JSON.stringify({ event: "publication_check_failed" }));
        return Response.json({ status: "check_failed" }, {
          status: 503, headers: { "Cache-Control": "no-store" },
        });
      }
    }
    if (request.method === "GET" && url.pathname === "/oauth/auth") {
      return handleOAuthAuth(request, env as OAuthEnv);
    }
    if (request.method === "GET" && url.pathname === "/oauth/callback") {
      return handleOAuthCallback(request, env as OAuthEnv);
    }
    if (request.method === "GET" && url.pathname === "/ready") {
      try {
        return Response.json(await checkReadiness(env), {
          headers: { "Cache-Control": "no-store" },
        });
      } catch (error) {
        console.error(JSON.stringify({
          event: "dispatcher_readiness_failed",
          message: String(error instanceof Error ? error.message : error),
        }));
        return Response.json(
          {
            status: "not_ready",
            resolution: "Verify GITHUB_DISPATCH_TOKEN and redeploy the Worker.",
          },
          { status: 503, headers: { "Cache-Control": "no-store" } },
        );
      }
    }
    if (request.method !== "GET" || url.pathname !== "/health") {
      return Response.json({ error: "Not found" }, { status: 404 });
    }
    const oauthEnv = env as OAuthEnv;
    return Response.json({
      service: "bmtnews-daily-dispatcher",
      status: "ok",
      primary_cron_utc: "30 0 * * *",
      final_cron_utc: "10 1 * * *",
      admin_oauth: Boolean(
        oauthEnv.GITHUB_OAUTH_CLIENT_ID && oauthEnv.GITHUB_OAUTH_CLIENT_SECRET,
      )
        ? "configured"
        : "not_configured",
    });
  },

  async scheduled(
    controller: ScheduledController,
    env: Env,
  ): Promise<void> {
    await runSchedule(controller.cron, controller.scheduledTime, env);
  },
} satisfies ExportedHandler<Env>;
