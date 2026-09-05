import { env } from "cloudflare:test";
import { afterEach, describe, expect, it, vi } from "vitest";
import worker from "../src/index";
import { runRecovery, responseStatus, recoveryTesting } from "../src/recovery";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
let sequence = 0;
function fixture(options: {
  raw?: boolean; public?: boolean; homepage?: boolean; active?: boolean;
  success?: boolean; broken?: boolean; dispatchTimeout?: boolean;
} = {}) {
  sequence += 1;
  const date = "2026-09-" + String(sequence).padStart(2, "0");
  const now = Date.parse(date + "T00:50:00Z");
  const requests: Request[] = [];
  const json = JSON.stringify({ date, items: [{ id: "one" }] });
  const home = '<div data-latest-edition-date="' + date + '"></div>' +
    '<section class="daily-day" data-date="' + date + '">' +
    '<article class="digest-item">News</article></section>';
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = new Request(input, init);
    requests.push(request);
    if (request.url.includes("/runs?")) {
      return Response.json({ workflow_runs: options.active || options.success ? [{
        status: options.active ? "in_progress" : "completed",
        conclusion: options.active ? null : "success", head_branch: "main",
        run_started_at: date + "T00:31:00Z", html_url: "https://github.com/run/1",
      }] : [] });
    }
    if (request.method === "POST") {
      if (options.dispatchTimeout) throw new Error("timeout");
      return new Response(null, { status: 204 });
    }
    if (options.broken) return new Response("upstream failure", { status: 503 });
    const raw = request.url.startsWith("https://raw.githubusercontent.com/");
    if (request.method === "HEAD") {
      return new Response(null, { status: (raw ? options.raw : options.public) ? 200 : 404 });
    }
    if (request.url.includes("/api/latest.json")) {
      return new Response((raw ? options.raw : options.public) ? json :
        JSON.stringify({ date: "2026-08-31", items: [{ id: "old" }] }));
    }
    if (request.url.includes("/summary-")) return new Response(options.public ? home : "", {
      status: options.public ? 200 : 404,
    });
    return new Response(options.homepage ? home : "<html>Yesterday</html>");
  }));
  return { date, now, requests, posts: () => requests.filter((r) => r.method === "POST") };
}

describe("production-aware recovery", () => {
  it("requires matching raw JSON, both posts, public JSON and actual homepage items", async () => {
    const f = fixture({ raw: true, public: true, homepage: true });
    const result = await runRecovery(env, f.now, "test");
    expect(result.status).toBe("healthy");
    expect(result.items).toBe(1);
    expect(f.posts()).toHaveLength(0);
  });

  it("recovers a missing edition even when an unrelated workflow succeeded", async () => {
    const f = fixture({ success: true });
    expect((await runRecovery(env, f.now, "test")).status).toBe("daily_dispatched");
    expect(await f.posts()[0]?.json()).toEqual({
      ref: "main", inputs: { edition_date: f.date, trigger_source: "test" },
    });
  });

  it("does not multiply jobs on simultaneous checks or before GitHub lists the run", async () => {
    const f = fixture();
    await Promise.all(Array.from({ length: 5 }, () => runRecovery(env, f.now, "test")));
    expect(f.posts()).toHaveLength(1);
    expect((await runRecovery(env, f.now + 60_000, "test")).status).toBe("daily_cooldown");
    expect(f.posts()).toHaveLength(1);
  });

  it("limits daily recovery to three attempts per edition", async () => {
    const f = fixture();
    for (let n = 0; n < 3; n++) {
      expect((await runRecovery(env, f.now + n * 31 * 60_000, "test")).status)
        .toBe("daily_dispatched");
    }
    expect((await runRecovery(env, f.now + 100 * 60_000, "test")).status)
      .toBe("daily_retry_limit");
    expect(f.posts()).toHaveLength(3);
  });

  it("retains cooldown if dispatch times out after possible acceptance", async () => {
    const f = fixture({ dispatchTimeout: true });
    await expect(runRecovery(env, f.now, "test")).rejects.toThrow("timeout");
    expect((await runRecovery(env, f.now + 60_000, "test")).status).toBe("daily_cooldown");
    expect(f.posts()).toHaveLength(1);
  });

  it("does not dispatch while a run is active and flags a stuck run", async () => {
    const f = fixture({ active: true });
    expect((await runRecovery(env, f.now, "test")).status).toBe("publication_active");
    const stuck = await runRecovery(env, f.now + 30 * 60_000, "test");
    expect(stuck.status).toBe("publication_stuck");
    expect(responseStatus(stuck)).toBe(503);
    expect(f.posts()).toHaveLength(0);
  });

  it("only rebuilds Pages when content exists but homepage is stale", async () => {
    const f = fixture({ raw: true, public: true });
    expect((await runRecovery(env, f.now, "test")).status).toBe("pages_waiting");
    expect((await runRecovery(env, f.now + 16 * 60_000, "test")).status)
      .toBe("pages_dispatched");
    expect(f.posts()).toHaveLength(1);
    expect(f.posts()[0]?.url).toContain("/pages/webhooks/deploy_hooks/");
    expect((await runRecovery(env, f.now + 20 * 60_000, "test")).status)
      .toBe("pages_cooldown");
    await runRecovery(env, f.now + 47 * 60_000, "test");
    expect((await runRecovery(env, f.now + 80 * 60_000, "test")).status)
      .toBe("pages_retry_limit");
    expect(f.posts()).toHaveLength(2);
  });

  it("fails closed on upstream errors rather than treating them as missing news", async () => {
    const f = fixture({ broken: true });
    await expect(runRecovery(env, f.now, "test")).rejects.toThrow("HTTP 503");
    expect(f.posts()).toHaveLength(0);
  });

  it("does not publish before 08:30 Shanghai and alerts at 09:15", async () => {
    const f = fixture();
    expect((await runRecovery(env, f.now - 30 * 60_000, "test")).status).toBe("not_due");
    expect(f.requests).toHaveLength(0);
    const result = await runRecovery(env, f.now + 25 * 60_000, "test");
    expect(responseStatus(result)).toBe(503);
  });

  it("rejects malformed JSON and counts only the expected date", () => {
    expect(recoveryTesting.editionItems('{"date":"old","items":[1]}', "today")).toBe(0);
    expect(recoveryTesting.editionItems('{"date":"today","items":[]}', "today")).toBe(0);
    expect(() => recoveryTesting.editionItems("<html>OK</html>", "today")).toThrow();
    expect(() => recoveryTesting.editionItems("{}", "today")).toThrow();
  });

  it("protects the mutating endpoint, rejects GET and ignores URL token guesses", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    for (const url of [
      "https://example.com/publication/check",
      "https://example.com/publication/check?token=test-check-token",
    ]) {
      expect((await worker.fetch(new Request(url), env)).status).toBe(405);
      expect((await worker.fetch(new Request(url, { method: "POST" }), env)).status).toBe(401);
    }
    expect(fetch).not.toHaveBeenCalled();
  });

  it("accepts the scoped secret and returns verified production status", async () => {
    const f = fixture({ raw: true, public: true, homepage: true });
    vi.spyOn(Date, "now").mockReturnValue(f.now);
    const response = await worker.fetch(new Request("https://example.com/publication/check", {
      method: "POST", headers: { Authorization: "Bearer " + env.RECOVERY_CHECK_TOKEN },
    }), env);
    expect(response.status).toBe(200);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(await response.json()).toMatchObject({ status: "healthy", edition_date: f.date });
    expect(f.posts()).toHaveLength(0);
  });

  it("leases survive callers and old owners cannot release a replacement lock", async () => {
    const gate = env.RECOVERY_GATE.getByName("lease-test");
    const owner = await gate.claim(1000);
    expect(owner).not.toBeNull();
    expect(await gate.claim(2000)).toBeNull();
    const replacement = await gate.claim(122000);
    expect(replacement).not.toBeNull();
    await gate.release(owner!);
    expect(await gate.claim(123000)).toBeNull();
    expect(await gate.claimAction(owner!, "daily", 123000)).toBe("lock_lost");
  });
});
