import { describe, expect, it } from "vitest";

import { AgentDatabase } from "../src/db.js";

describe("AgentDatabase readiness", () => {
  it("requires the latest migration", () => {
    const database = new AgentDatabase(":memory:");
    try {
      expect(database.isReady()).toBe(false);
      database.initialize();
      expect(database.isReady()).toBe(true);

      database.connection.exec("DELETE FROM schema_migrations WHERE version = 1");
      expect(database.isReady()).toBe(false);
    } finally {
      database.close();
    }
  });

  it("fails closed after the connection is closed", () => {
    const database = new AgentDatabase(":memory:");
    database.initialize();
    database.close();

    expect(database.isReady()).toBe(false);
  });
});
