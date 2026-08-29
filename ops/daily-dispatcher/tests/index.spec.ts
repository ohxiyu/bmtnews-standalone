import { afterEach, describe, expect, it, vi } from "vitest";

import worker from "../src/index";
import { runSchedule, testing } from "../src/lib";

const ENV = {
  GITHUB_REPOSITORY: "ohxiyu/bmtnews-standalone",
  GITHUB_WORKFLOW: "daily-summary.yml",
  GITHUB_REF: "main",
  EDITION_TIMEZONE: "Asia/Shanghai",
  EDITION_CUTOFF_HOUR: "8",
  PUBLIC_SITE_URL: "https://bmt.news",
  GITHUB_DISPATCH_TOKEN: "test-token",
} satisfies Env;

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("edition scheduling", () => {
  it("targets the Shanghai edition ending at 08:00", () => {
    const context = testing.editionContextFor(
      Date.parse("2026-07-31T00:30:00Z"),
      "Asia/Shanghai",
      8,
    );

    expect(context.date).toBe("2026-07-31");
    expect(context.cutoffUtc.toISOString()).toBe(
      "2026-07-31T00:00:00.000Z",
    );
  });

  it("builds raw and rendered URLs for both languages", () => {
    expect(testing.publicationUrls(ENV, "2026-07-31")).toEqual({
      raw: [
        "https://raw.githubusercontent.com/ohxiyu/bmtnews-standalone/gh-pages/_posts/2026-07-31-summary-zh.md",
        "https://raw.githubusercontent.com/ohxiyu/bmtnews-standalone/gh-pages/_posts/2026-07-31-summary-en.md",
      ],
      rendered: [
        "https://bmt.news/2026/07/31/summary-zh.html",
        "https://bmt.news/2026/07/31/summary-en.html",
      ],
    });
  });
});

describe("dispatcher behavior", () => {
  it("dispatches the explicit edition date when publication is missing", async () => {
    const requests: Request[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const request = new Request(input, init);
        requests.push(request);
        if (request.url.includes("/runs?")) {
          return Response.json({ workflow_runs: [] });
        }
        if (request.method === "POST") {
          return new Response(null, { status: 204 });
        }
        return new Response(null, { status: 404 });
      }),
    );

    await runSchedule(
      "30 0 * * *",
      Date.parse("2026-07-31T00:30:00Z"),
      ENV,
    );

    const dispatch = requests.find((request) => request.method === "POST");
    expect(dispatch).toBeDefined();
    await expect(dispatch?.json()).resolves.toEqual({
      ref: "main",
      inputs: {
        edition_date: "2026-07-31",
        trigger_source: "cloudflare-primary",
      },
    });
  });

  it("does not dispatch while an edition run is active", async () => {
    const requests: Request[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const request = new Request(input, init);
        requests.push(request);
        if (request.url.includes("/runs?")) {
          return Response.json({
            workflow_runs: [
              {
                status: "in_progress",
                conclusion: null,
                head_branch: "main",
                run_started_at: "2026-07-31T00:31:00Z",
                html_url: "https://github.com/example/run/1",
              },
            ],
          });
        }
        return new Response(null, { status: 404 });
      }),
    );

    await runSchedule(
      "40 0 * * *",
      Date.parse("2026-07-31T00:40:00Z"),
      ENV,
    );

    expect(requests.some((request) => request.method === "POST")).toBe(false);
  });

  it("does not rerun AI when gh-pages exists but rendering is delayed", async () => {
    const requests: Request[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const request = new Request(input, init);
        requests.push(request);
        if (request.url.includes("/runs?")) {
          return Response.json({
            workflow_runs: [
              {
                status: "completed",
                conclusion: "success",
                head_branch: "main",
                run_started_at: "2026-07-31T00:31:00Z",
                html_url: "https://github.com/example/run/2",
              },
            ],
          });
        }
        if (request.url.startsWith("https://raw.githubusercontent.com/")) {
          return new Response(null, { status: 200 });
        }
        return new Response(null, { status: 404 });
      }),
    );

    await runSchedule(
      "55 0 * * *",
      Date.parse("2026-07-31T00:55:00Z"),
      ENV,
    );

    expect(requests.some((request) => request.method === "POST")).toBe(false);
  });

  it("fails the final check after dispatching one last recovery", async () => {
    const requests: Request[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const request = new Request(input, init);
        requests.push(request);
        if (request.url.includes("/runs?")) {
          return Response.json({ workflow_runs: [] });
        }
        if (request.method === "POST") {
          return new Response(null, { status: 204 });
        }
        return new Response(null, { status: 404 });
      }),
    );

    await expect(
      runSchedule(
        "10 1 * * *",
        Date.parse("2026-07-31T01:10:00Z"),
        ENV,
      ),
    ).rejects.toThrow("final recovery dispatched");
    expect(requests.filter((request) => request.method === "POST")).toHaveLength(
      1,
    );
  });

  it("exposes only a read-only health endpoint", async () => {
    const health = await worker.fetch(
      new Request("https://dispatcher.example/health"),
      ENV,
    );
    const notFound = await worker.fetch(
      new Request("https://dispatcher.example/run", { method: "POST" }),
      ENV,
    );

    expect(health.status).toBe(200);
    await expect(health.json()).resolves.toMatchObject({
      service: "bmtnews-daily-dispatcher",
      status: "ok",
      admin_oauth: "not_configured",
    });
    expect(notFound.status).toBe(404);
  });

  it("actively verifies Actions write permission without creating a run", async () => {
    const fetchSpy = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) =>
        new Response(null, { status: 422 }),
    );
    vi.stubGlobal("fetch", fetchSpy);
    const response = await worker.fetch(
      new Request("https://dispatcher.example/ready"),
      ENV,
    );
    expect(response.status).toBe(200);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    await expect(response.json()).resolves.toMatchObject({
      status: "ready",
      repository: "ohxiyu/bmtnews-standalone",
      workflow: "daily-summary.yml",
      ref: "main",
      dispatch_permission: "actions:write",
    });
    expect(fetchSpy).toHaveBeenCalledOnce();
    const [input, init] = fetchSpy.mock.calls[0] ?? [];
    expect(String(input)).toContain("/daily-summary.yml/dispatches");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({
      ref: "refs/heads/__bmtnews_permission_probe__/invalid..ref",
    });
  });

  it("rejects a read-only token without leaking GitHub API details", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 403 })));
    const response = await worker.fetch(
      new Request("https://dispatcher.example/ready"),
      ENV,
    );
    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({
      status: "not_ready",
      resolution: "Verify GITHUB_DISPATCH_TOKEN and redeploy the Worker.",
    });
  });
});

describe("admin OAuth relay", () => {
  const OAUTH_ENV = {
    ...ENV,
    GITHUB_OAUTH_CLIENT_ID: "client-id",
    GITHUB_OAUTH_CLIENT_SECRET: "client-secret",
  } as Env;

  it("returns 503 while OAuth secrets are unset", async () => {
    const auth = await worker.fetch(
      new Request("https://dispatcher.example/oauth/auth"),
      ENV,
    );
    const callback = await worker.fetch(
      new Request("https://dispatcher.example/oauth/callback?code=x&state=y"),
      ENV,
    );
    expect(auth.status).toBe(503);
    expect(callback.status).toBe(503);
  });

  it("redirects to GitHub with a narrow scope and a state cookie", async () => {
    const response = await worker.fetch(
      new Request("https://dispatcher.example/oauth/auth"),
      OAUTH_ENV,
    );

    expect(response.status).toBe(302);
    const location = new URL(response.headers.get("Location") ?? "");
    expect(location.origin).toBe("https://github.com");
    expect(location.pathname).toBe("/login/oauth/authorize");
    expect(location.searchParams.get("client_id")).toBe("client-id");
    expect(location.searchParams.get("scope")).toBe("public_repo");
    const state = location.searchParams.get("state");
    expect(state).toBeTruthy();
    expect(response.headers.get("Set-Cookie")).toContain(
      `bmtnews_oauth_state=${state}`,
    );
    expect(response.headers.get("Set-Cookie")).toContain("HttpOnly");
  });

  it("rejects a callback whose state does not match the cookie", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    const response = await worker.fetch(
      new Request(
        "https://dispatcher.example/oauth/callback?code=abc&state=forged",
        { headers: { Cookie: "bmtnews_oauth_state=expected" } },
      ),
      OAUTH_ENV,
    );

    const body = await response.text();
    expect(body).toContain("authorization:github:error");
    expect(body).not.toContain("authorization:github:success");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("exchanges the code and hands the token to the admin origin only", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({ access_token: "gho_test_token", token_type: "bearer" }),
      ),
    );

    const response = await worker.fetch(
      new Request(
        "https://dispatcher.example/oauth/callback?code=abc&state=expected",
        { headers: { Cookie: "bmtnews_oauth_state=expected" } },
      ),
      OAUTH_ENV,
    );

    const body = await response.text();
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(body).toContain("authorization:github:success");
    expect(body).toContain("gho_test_token");
    expect(body).toContain('"https://bmt.news"');
    // The state cookie is cleared after one use.
    expect(response.headers.get("Set-Cookie")).toContain("Max-Age=0");
  });
});
