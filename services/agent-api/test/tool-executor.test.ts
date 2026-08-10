import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { AgentDatabase } from "../src/db.js";
import { TaskRepository } from "../src/repositories/tasks.js";
import { ToolExecutor } from "../src/tools/executor.js";


const emptyCreateFields = {
  notes: null,
  courseId: null,
  priority: null,
  dueDate: null,
  sourceCitation: null,
};

describe("ToolExecutor", () => {
  let database: AgentDatabase;
  let repository: TaskRepository;
  let executor: ToolExecutor;
  let nextId: number;

  beforeEach(() => {
    database = new AgentDatabase(":memory:");
    database.initialize();
    nextId = 0;
    repository = new TaskRepository(database.connection, {
      clock: () => new Date("2026-08-11T00:00:00.000Z"),
      idFactory: () => `task-${++nextId}`,
    });
    executor = new ToolExecutor(repository);
  });

  afterEach(() => database.close());

  it("executes createTask and searchTask through validated arguments", () => {
    const created = executor.execute("createTask", {
      title: "Review lighting",
      ...emptyCreateFields,
      courseId: "cs3481",
      priority: "high",
    });
    const found = executor.execute("searchTask", {
      query: "lighting",
      courseId: "cs3481",
      status: null,
      page: 1,
      pageSize: 20,
    });

    expect(created.ok).toBe(true);
    expect(created.data).toMatchObject({ id: "task-1", priority: "high" });
    expect(found.ok).toBe(true);
    expect(found.data).toMatchObject({ total: 1 });
  });

  it("executes selected update fields, completion, and exact deletion", () => {
    const task = repository.create({ title: "Read notes" });
    const updated = executor.execute("updateTask", {
      taskId: task.id,
      updateFields: ["title", "notes"],
      title: "Read lecture notes",
      notes: "Chapter 2",
      courseId: null,
      status: null,
      priority: null,
      dueDate: null,
    });
    const completed = executor.execute("completeTask", { taskId: task.id });
    const deleted = executor.execute("deleteTask", { taskId: task.id });

    expect(updated.data).toMatchObject({ title: "Read lecture notes", notes: "Chapter 2" });
    expect(completed.data).toMatchObject({ status: "completed" });
    expect(deleted).toEqual({ ok: true, data: { taskId: task.id, deleted: true }, error: null });
    expect(repository.get(task.id)).toBeNull();
  });

  it("rejects unknown tools and malformed arguments without mutation", () => {
    const unknown = executor.execute("runSql", { sql: "DROP TABLE tasks" });
    const malformed = executor.execute("createTask", {
      title: "Unsafe",
      ...emptyCreateFields,
      sql: "DROP TABLE tasks",
    });

    expect(unknown).toMatchObject({ ok: false, error: { code: "UNKNOWN_TOOL" } });
    expect(malformed).toMatchObject({
      ok: false,
      error: { code: "INVALID_TOOL_ARGUMENTS" },
    });
    expect(repository.list({ page: 1, pageSize: 10 }).total).toBe(0);
  });

  it("rejects null for a selected non-nullable update field", () => {
    const task = repository.create({ title: "Read notes" });

    const result = executor.execute("updateTask", {
      taskId: task.id,
      updateFields: ["title"],
      title: null,
      notes: null,
      courseId: null,
      status: null,
      priority: null,
      dueDate: null,
    });

    expect(result).toMatchObject({ ok: false, error: { code: "INVALID_UPDATE_VALUE" } });
    expect(repository.get(task.id)?.title).toBe("Read notes");
  });

  it("returns typed not-found errors and search never mutates ambiguous matches", () => {
    repository.create({ title: "Review lecture one" });
    repository.create({ title: "Review lecture two" });
    const search = executor.execute("searchTask", {
      query: "Review lecture",
      courseId: null,
      status: null,
      page: 1,
      pageSize: 20,
    });
    const missing = executor.execute("deleteTask", { taskId: "missing" });

    expect(search.data).toMatchObject({ total: 2 });
    expect(missing).toMatchObject({ ok: false, error: { code: "TASK_NOT_FOUND" } });
    expect(repository.list({ page: 1, pageSize: 10 }).total).toBe(2);
  });
});
