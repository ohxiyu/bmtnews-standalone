/**
 * GitHub OAuth relay for the /admin CMS (Decap/Sveltia popup protocol).
 *
 * Optional feature: routes return 503 until both secrets are set via
 * `wrangler secret put GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET`.
 * The OAuth app only needs the `public_repo` scope because the repository
 * is public, and the issued token is delivered exclusively to the admin
 * origin via postMessage — never logged, stored, or echoed elsewhere.
 */

const DEFAULT_ADMIN_ORIGIN = "https://bmt.news";
const OAUTH_SCOPE = "public_repo";
const STATE_COOKIE = "bmtnews_oauth_state";

export type OAuthEnv = Env & {
  GITHUB_OAUTH_CLIENT_ID?: string;
  GITHUB_OAUTH_CLIENT_SECRET?: string;
  ADMIN_ORIGIN?: string;
};

function adminOrigin(env: OAuthEnv): string {
  return (env.ADMIN_ORIGIN ?? DEFAULT_ADMIN_ORIGIN).replace(/\/+$/, "");
}

function oauthConfigured(env: OAuthEnv): boolean {
  return Boolean(env.GITHUB_OAUTH_CLIENT_ID && env.GITHUB_OAUTH_CLIENT_SECRET);
}

function notConfigured(): Response {
  return Response.json(
    {
      error:
        "OAuth sign-in is not configured; set GITHUB_OAUTH_CLIENT_ID and " +
        "GITHUB_OAUTH_CLIENT_SECRET worker secrets, or sign in with a " +
        "personal access token instead.",
    },
    { status: 503 },
  );
}

function stateFromCookie(request: Request): string | null {
  const cookie = request.headers.get("Cookie") ?? "";
  const match = cookie.match(
    new RegExp(`(?:^|;\\s*)${STATE_COOKIE}=([^;]+)`),
  );
  return match?.[1] ?? null;
}

/** Embed a value in an inline script without enabling tag breakout. */
function scriptSafeJson(value: unknown): string {
  return JSON.stringify(value).replaceAll("<", "\\u003c");
}

function popupResult(
  origin: string,
  payload: { token: string } | { error: string },
): Response {
  const message =
    "token" in payload
      ? "authorization:github:success:" +
        JSON.stringify({ provider: "github", token: payload.token })
      : "authorization:github:error:" +
        JSON.stringify({ provider: "github", error: payload.error });
  const body = `<!doctype html>
<html><body><p>Completing sign-in… You can close this window if it does not close itself.</p>
<script>
(() => {
  const origin = ${scriptSafeJson(origin)};
  const message = ${scriptSafeJson(message)};
  let delivered = false;
  const deliver = () => {
    if (delivered || !window.opener) return;
    delivered = true;
    window.opener.postMessage(message, origin);
  };
  window.addEventListener("message", (event) => {
    if (event.origin !== origin) return;
    deliver();
  });
  if (window.opener) {
    window.opener.postMessage("authorizing:github", origin);
    setTimeout(deliver, 1500);
  }
})();
</script></body></html>`;
  return new Response(body, {
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
      "Set-Cookie": `${STATE_COOKIE}=; HttpOnly; Secure; SameSite=Lax; Path=/oauth; Max-Age=0`,
    },
  });
}

export function handleOAuthAuth(request: Request, env: OAuthEnv): Response {
  if (!oauthConfigured(env)) {
    return notConfigured();
  }
  const state = crypto.randomUUID();
  const callback = new URL("/oauth/callback", request.url);
  const authorize = new URL("https://github.com/login/oauth/authorize");
  authorize.searchParams.set("client_id", env.GITHUB_OAUTH_CLIENT_ID as string);
  authorize.searchParams.set("redirect_uri", callback.toString());
  authorize.searchParams.set("scope", OAUTH_SCOPE);
  authorize.searchParams.set("state", state);
  return new Response(null, {
    status: 302,
    headers: {
      Location: authorize.toString(),
      "Cache-Control": "no-store",
      "Set-Cookie": `${STATE_COOKIE}=${state}; HttpOnly; Secure; SameSite=Lax; Path=/oauth; Max-Age=600`,
    },
  });
}

export async function handleOAuthCallback(
  request: Request,
  env: OAuthEnv,
): Promise<Response> {
  if (!oauthConfigured(env)) {
    return notConfigured();
  }
  const origin = adminOrigin(env);
  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const expectedState = stateFromCookie(request);

  if (!code || !state || !expectedState || state !== expectedState) {
    return popupResult(origin, { error: "Invalid or expired sign-in state." });
  }

  let token: string | undefined;
  try {
    const exchange = await fetch(
      "https://github.com/login/oauth/access_token",
      {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "User-Agent": "bmtnews-daily-dispatcher",
        },
        body: JSON.stringify({
          client_id: env.GITHUB_OAUTH_CLIENT_ID,
          client_secret: env.GITHUB_OAUTH_CLIENT_SECRET,
          code,
        }),
      },
    );
    const payload = (await exchange.json()) as Record<string, unknown>;
    if (typeof payload.access_token === "string" && payload.access_token) {
      token = payload.access_token;
    }
  } catch {
    token = undefined;
  }

  if (!token) {
    return popupResult(origin, { error: "GitHub token exchange failed." });
  }
  return popupResult(origin, { token });
}
