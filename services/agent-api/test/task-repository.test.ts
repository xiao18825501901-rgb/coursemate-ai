import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { AgentDatabase } from "../src/db.js";
import { TaskRepository } from "../src/repositories/tasks.js";

describe("TaskRepository", () => {
  let database: AgentDatabase;
  let repository: TaskRepository;
  let idSequence: number;

  beforeEach(() => {
    database = new AgentDatabase(":memory:");
    database.initialize();
    idSequence = 0;
    repository = new TaskRepository(database.connection, {
      clock: () => new Date("2026-08-11T00:00:00.000Z"),
      idFactory: () => `task-${++idSequence}`,
    });
  });

  afterEach(() => {
    database.close();
  });

  it("creates and reads a fully typed task", () => {
    const task = repository.create("user-a", {
      title: "Review Phong lighting",
      notes: "Focus on diffuse and specular terms.",
      courseId: "cs3481",
      priority: "high",
      dueDate: "2026-08-20",
      sourceCitation: {
        filename: "lighting.md",
        locator: "section Lighting",
        excerpt: "Phong combines three terms.",
      },
    });

    expect(repository.get("user-a", task.id)).toEqual(task);
    expect(task).toMatchObject({
      id: "task-1",
      status: "todo",
      createdAt: "2026-08-11T00:00:00.000Z",
      completedAt: null,
    });
  });

  it("filters and paginates by course, status, and search text", () => {
    repository.create("user-a", { title: "Review lighting", courseId: "cs3481" });
    const completed = repository.create("user-a", { title: "Read heritage case", courseId: "ge2324" });
    repository.complete("user-a", completed.id);
    repository.create("user-a", { title: "Practice rasterization", courseId: "cs3481" });

    const csTasks = repository.list("user-a", { page: 1, pageSize: 10, courseId: "cs3481" });
    const done = repository.list("user-a", { page: 1, pageSize: 10, status: "completed" });
    const search = repository.list("user-a", { page: 1, pageSize: 1, query: "raster" });

    expect(csTasks.total).toBe(2);
    expect(csTasks.items.every((task) => task.courseId === "cs3481")).toBe(true);
    expect(done.items.map((task) => task.id)).toEqual([completed.id]);
    expect(search.total).toBe(1);
    expect(search.items[0]?.title).toBe("Practice rasterization");
  });

  it("updates, completes, reopens, and deletes without changing creation time", () => {
    const created = repository.create("user-a", { title: "Read notes" });

    const updated = repository.update("user-a", created.id, {
      title: "Read lecture notes",
      status: "in_progress",
      priority: "medium",
    });
    const completed = repository.complete("user-a", created.id);
    const reopened = repository.update("user-a", created.id, { status: "todo" });
    const deleted = repository.delete("user-a", created.id);

    expect(updated?.createdAt).toBe(created.createdAt);
    expect(updated?.status).toBe("in_progress");
    expect(completed?.status).toBe("completed");
    expect(completed?.completedAt).toBe("2026-08-11T00:00:00.000Z");
    expect(reopened?.completedAt).toBeNull();
    expect(deleted).toBe(true);
    expect(repository.get("user-a", created.id)).toBeNull();
  });

  it("returns null or false for missing task IDs", () => {
    expect(repository.get("user-a", "missing")).toBeNull();
    expect(repository.update("user-a", "missing", { title: "No task" })).toBeNull();
    expect(repository.complete("user-a", "missing")).toBeNull();
    expect(repository.delete("user-a", "missing")).toBe(false);
  });

  it("stores SQL-looking input as data and preserves the table", () => {
    const title = "'); DROP TABLE tasks; --";
    const task = repository.create("user-a", { title });

    expect(repository.get("user-a", task.id)?.title).toBe(title);
    expect(repository.list("user-a", { page: 1, pageSize: 10 }).total).toBe(1);
  });

  it("enforces owner isolation in every query and mutation", () => {
    const taskA = repository.create("user-a", { title: "Private A" });
    const taskB = repository.create("user-b", { title: "Private B" });

    expect(repository.list("user-a", { page: 1, pageSize: 10 }).items).toEqual([taskA]);
    expect(repository.list("user-b", { page: 1, pageSize: 10 }).items).toEqual([taskB]);
    expect(repository.get("user-a", taskB.id)).toBeNull();
    expect(repository.update("user-a", taskB.id, { title: "stolen" })).toBeNull();
    expect(repository.delete("user-a", taskB.id)).toBe(false);
    expect(repository.get("user-b", taskB.id)?.title).toBe("Private B");
  });

  it("quarantines rows from a legacy task table instead of assigning a real user", () => {
    const legacy = new AgentDatabase(":memory:");
    legacy.connection.exec(`
      CREATE TABLE tasks (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, notes TEXT, course_id TEXT,
        status TEXT NOT NULL, priority TEXT NOT NULL, due_date TEXT,
        source_citation TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        completed_at TEXT
      );
      INSERT INTO tasks VALUES (
        'legacy-1', 'Old task', NULL, NULL, 'todo', 'medium', NULL, NULL,
        '2026-08-11T00:00:00.000Z', '2026-08-11T00:00:00.000Z', NULL
      );
    `);
    legacy.initialize();
    const migrated = new TaskRepository(legacy.connection);

    expect(migrated.list("user-a", { page: 1, pageSize: 10 }).total).toBe(0);
    expect(legacy.connection.prepare(
      "SELECT owner_user_id FROM tasks WHERE id = 'legacy-1'",
    ).get()).toEqual({ owner_user_id: "legacy_orphaned" });
    legacy.close();
  });
});
