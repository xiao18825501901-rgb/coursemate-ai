import { afterEach, describe, expect, it } from "vitest";

import { AgentDatabase } from "../src/db.js";
import { SqliteModelRateLimiter } from "../src/rate-limit.js";


describe("SqliteModelRateLimiter", () => {
  const databases: AgentDatabase[] = [];

  afterEach(() => {
    databases.splice(0).forEach((database) => database.close());
  });

  it("enforces both minute and UTC-day budgets without charging blocked attempts", () => {
    const database = new AgentDatabase(":memory:");
    databases.push(database);
    database.initialize();
    let now = Date.parse("2026-09-12T00:00:00.000Z");
    const limiter = new SqliteModelRateLimiter(database.connection, {
      limitPerMinute: 2,
      limitPerDay: 3,
      clock: () => now,
    });

    expect(limiter.consume("user-a")).toBe(true);
    expect(limiter.consume("user-a")).toBe(true);
    expect(limiter.consume("user-a")).toBe(false);
    now += 60_000;
    expect(limiter.consume("user-a")).toBe(true);
    expect(limiter.consume("user-a")).toBe(false);
    expect(limiter.consume("user-b")).toBe(true);

    const rows = database.connection.prepare(`
      SELECT owner_user_id, action, request_count
      FROM rate_limit_windows
      ORDER BY owner_user_id, action, window_start
    `).all() as Array<{ owner_user_id: string; action: string; request_count: number }>;
    expect(rows.filter((row) => row.owner_user_id === "user-a")).toEqual([
      { owner_user_id: "user-a", action: "agent_chat_day", request_count: 3 },
      { owner_user_id: "user-a", action: "agent_chat_minute", request_count: 2 },
      { owner_user_id: "user-a", action: "agent_chat_minute", request_count: 1 },
    ]);
  });
});
