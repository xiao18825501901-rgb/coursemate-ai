import type { DatabaseSync } from "node:sqlite";


export interface ModelRateLimiter {
  consume(ownerUserId: string): boolean;
}

export interface SqliteModelRateLimiterOptions {
  limitPerMinute: number;
  clock?: () => number;
}

export class SqliteModelRateLimiter implements ModelRateLimiter {
  private readonly clock: () => number;

  constructor(
    private readonly database: DatabaseSync,
    private readonly options: SqliteModelRateLimiterOptions,
  ) {
    this.clock = options.clock ?? (() => Date.now());
  }

  consume(ownerUserId: string): boolean {
    const epochSeconds = Math.floor(this.clock() / 1_000);
    const windowStart = epochSeconds - (epochSeconds % 60);
    this.database.prepare(
      "DELETE FROM rate_limit_windows WHERE window_start < ?",
    ).run(windowStart - 3_600);
    const row = this.database.prepare(`
      INSERT INTO rate_limit_windows (owner_user_id, action, window_start, request_count)
      VALUES (?, 'agent_chat', ?, 1)
      ON CONFLICT(owner_user_id, action, window_start)
      DO UPDATE SET request_count = request_count + 1
      RETURNING request_count
    `).get(ownerUserId, windowStart) as { request_count: number };
    return row.request_count <= this.options.limitPerMinute;
  }
}
