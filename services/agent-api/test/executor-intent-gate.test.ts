import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { AgentDatabase } from "../src/db.js";
import { TaskRepository } from "../src/repositories/tasks.js";
import { ToolExecutor } from "../src/tools/executor.js";
import { JevToolIntentGate, type FetchImpl } from "../src/tools/intent-gate.js";


const emptyCreateFields = {
  notes: null,
  courseId: null,
  priority: null,
  dueDate: null,
  sourceCitation: null,
};

function jsonResponse(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as unknown as Response;
}

function gateFor(
  mode: "advisory" | "enforce",
  verdictPayload: unknown,
): JevToolIntentGate {
  const fetchImpl: FetchImpl = () => Promise.resolve(jsonResponse(verdictPayload));
  return new JevToolIntentGate({
    mode,
    url: "http://internal/jev/tool-intent",
    token: "secret-token",
    fetchImpl,
  });
}

describe("ToolExecutor intent gate", () => {
  const ownerUserId = "user-a";
  let database: AgentDatabase;
  let repository: TaskRepository;
  let nextId: number;

  beforeEach(() => {
    database = new AgentDatabase(":memory:");
    database.initialize();
    nextId = 0;
    repository = new TaskRepository(database.connection, {
      clock: () => new Date("2026-08-11T00:00:00.000Z"),
      idFactory: () => `task-${++nextId}`,
    });
  });

  afterEach(() => database.close());

  it("searchTask never calls the gate", async () => {
    const fetchImpl: FetchImpl = () => {
      throw new Error("searchTask must never call the gate");
    };
    const gate = new JevToolIntentGate({
      mode: "enforce",
      url: "http://internal/jev",
      token: "t",
      fetchImpl,
    });
    const executor = new ToolExecutor(repository, gate);
    repository.create(ownerUserId, { title: "Review lighting" });

    const result = await executor.execute(
      ownerUserId,
      "searchTask",
      { query: "lighting", courseId: null, status: null, page: 1, pageSize: 20 },
      { userMessage: "find my lighting task" },
    );

    expect(result.ok).toBe(true);
    expect("intent" in result).toBe(false);
    expect(result.data).toMatchObject({ total: 1 });
  });

  it("createTask with no gate is byte-identical to today", () => {
    const executor = new ToolExecutor(repository);

    const result = executor.execute(ownerUserId, "createTask", {
      title: "Review lighting",
      ...emptyCreateFields,
      courseId: "cs3481",
      priority: "high",
    });

    expect(result).toEqual({
      ok: true,
      data: expect.objectContaining({ id: "task-1", priority: "high" }),
      error: null,
    });
    expect("intent" in result).toBe(false);
  });

  it("enforce + REQUIRE_CONFIRMATION blocks the write", async () => {
    const gate = gateFor("enforce", {
      verdict: "REQUIRE_CONFIRMATION",
      reason: "intent:unavailable",
      used_jev: false,
      jev_label: null,
      receipt_id: null,
      path: "fallback:require_confirmation",
      jev_calls: 1,
    });
    const executor = new ToolExecutor(repository, gate);

    const result = await executor.execute(
      ownerUserId,
      "createTask",
      { title: "Review lighting", ...emptyCreateFields },
      { userMessage: "tell me about lighting" },
    );

    expect(result).toMatchObject({ ok: false, error: { code: "CONFIRMATION_REQUIRED" } });
    expect(result.intent?.verdict).toBe("REQUIRE_CONFIRMATION");
    expect(repository.list(ownerUserId, { page: 1, pageSize: 10 }).total).toBe(0);
  });

  it("enforce + REFUSE_UNAUTHORIZED blocks with INTENT_REFUSED", async () => {
    const task = repository.create(ownerUserId, { title: "Read notes" });
    const gate = gateFor("enforce", {
      verdict: "REFUSE_UNAUTHORIZED",
      reason: "missing_permission",
      used_jev: false,
      jev_label: null,
      receipt_id: null,
      path: "deterministic:missing_permission",
      jev_calls: 0,
    });
    const executor = new ToolExecutor(repository, gate);

    const result = await executor.execute(
      ownerUserId,
      "deleteTask",
      { taskId: task.id },
      { userMessage: "what is this task about" },
    );

    expect(result).toMatchObject({ ok: false, error: { code: "INTENT_REFUSED" } });
    expect(repository.get(ownerUserId, task.id)).not.toBeNull();
  });

  it("advisory records intent but still executes", async () => {
    const gate = gateFor("advisory", {
      verdict: "REQUIRE_CONFIRMATION",
      reason: "intent:unavailable",
      used_jev: false,
      jev_label: null,
      receipt_id: null,
      path: "fallback:require_confirmation",
      jev_calls: 1,
    });
    const executor = new ToolExecutor(repository, gate);

    const result = await executor.execute(
      ownerUserId,
      "createTask",
      { title: "Review lighting", ...emptyCreateFields },
      { userMessage: "create a task" },
    );

    expect(result.ok).toBe(true);
    expect(result.intent?.verdict).toBe("REQUIRE_CONFIRMATION");
    expect(repository.list(ownerUserId, { page: 1, pageSize: 10 }).total).toBe(1);
  });

  it("deleteTask with an ALLOW gate executes with zero Jev calls", async () => {
    const task = repository.create(ownerUserId, { title: "Read notes" });
    const gate = gateFor("enforce", {
      verdict: "ALLOW",
      reason: "explicit",
      used_jev: false,
      jev_label: null,
      receipt_id: null,
      path: "deterministic:explicit",
      jev_calls: 0,
    });
    const executor = new ToolExecutor(repository, gate);

    const result = await executor.execute(
      ownerUserId,
      "deleteTask",
      { taskId: task.id },
      { userMessage: "delete that task" },
    );

    expect(result).toEqual({
      ok: true,
      data: { taskId: task.id, deleted: true },
      error: null,
      intent: expect.objectContaining({ verdict: "ALLOW", usedJev: false, jevCalls: 0 }),
    });
    expect(repository.get(ownerUserId, task.id)).toBeNull();
  });
});
