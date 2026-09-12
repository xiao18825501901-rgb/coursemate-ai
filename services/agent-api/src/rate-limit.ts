import type { DatabaseSync } from "node:sqlite";


export interface ModelRateLimiter {
  consume(ownerUserId: string): boolean;
}

export interface SqliteModelRateLimiterOptions {
  limitPerMinute: number;
  limitPerDay: number;
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
    const minuteStart = epochSeconds - (epochSeconds % 60);
    const dayStart = epochSeconds - (epochSeconds % 86_400);
    this.database.exec("BEGIN IMMEDIATE");
    try {
      this.database.prepare(`
        DELETE FROM rate_limit_windows
        WHERE (action = 'agent_chat_minute' AND window_start < ?)
           OR (action = 'agent_chat_day' AND window_start < ?)
      `).run(minuteStart - 3_600, dayStart);
      const count = (action: string, windowStart: number): number => {
        const row = this.database.prepare(`
          SELECT request_count
          FROM rate_limit_windows
          WHERE owner_user_id = ? AND action = ? AND window_start = ?
        `).get(ownerUserId, action, windowStart) as { request_count: number } | undefined;
        return row?.request_count ?? 0;
      };
      if (
        count("agent_chat_minute", minuteStart) >= this.options.limitPerMinute ||
        count("agent_chat_day", dayStart) >= this.options.limitPerDay
      ) {
        this.database.exec("COMMIT");
        return false;
      }
      const increment = this.database.prepare(`
        INSERT INTO rate_limit_windows (owner_user_id, action, window_start, request_count)
        VALUES (?, ?, ?, 1)
        ON CONFLICT(owner_user_id, action, window_start)
        DO UPDATE SET request_count = request_count + 1
      `);
      increment.run(ownerUserId, "agent_chat_minute", minuteStart);
      increment.run(ownerUserId, "agent_chat_day", dayStart);
      this.database.exec("COMMIT");
      return true;
    } catch (error) {
      this.database.exec("ROLLBACK");
      throw error;
    }
  }
}
