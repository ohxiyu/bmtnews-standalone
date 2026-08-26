import { checkReadiness, runSchedule } from "./lib";
import {
  handleOAuthAuth,
  handleOAuthCallback,
  type OAuthEnv,
} from "./oauth";

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
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
