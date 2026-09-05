import { DurableObject } from "cloudflare:workers";

// One object per edition. Synchronous SQL claims are committed before any
// caller performs external I/O; a crashed caller leaves a bounded lease.
export class RecoveryGate extends DurableObject<Env> {
  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    this.ctx.storage.sql.exec(
      "CREATE TABLE IF NOT EXISTS gate (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    );
  }

  private read(key: string): string | null {
    return this.ctx.storage.sql.exec<{ value: string }>(
      "SELECT value FROM gate WHERE key = ?", key,
    ).toArray()[0]?.value ?? null;
  }

  private write(key: string, value: string): void {
    this.ctx.storage.sql.exec(
      "INSERT OR REPLACE INTO gate (key, value) VALUES (?, ?)", key, value,
    );
  }

  claim(now: number): string | null {
    if (Number(this.read("lease_until") ?? "0") > now) return null;
    const token = crypto.randomUUID();
    this.write("owner", token);
    this.write("lease_until", String(now + 120_000));
    return token;
  }

  release(token: string): void {
    if (this.read("owner") === token) this.write("lease_until", "0");
  }

  firstRawSeen(now: number): number {
    const previous = this.read("raw_seen");
    if (previous !== null) return Number(previous);
    this.write("raw_seen", String(now));
    return now;
  }

  claimAction(token: string, kind: "daily" | "pages", now: number): string {
    if (this.read("owner") !== token ||
        Number(this.read("lease_until")) <= now) return "lock_lost";
    const attempts = Number(this.read(kind + "_attempts") ?? "0");
    if (attempts >= (kind === "daily" ? 3 : 2)) return "retry_limit";
    if (Number(this.read(kind + "_next") ?? "0") > now) return "cooldown";
    this.write(kind + "_attempts", String(attempts + 1));
    // Keep the cooldown even on timeouts: GitHub/the hook may have accepted
    // the request although the response was lost.
    this.write(kind + "_next", String(now + 30 * 60_000));
    return "claimed";
  }
}
