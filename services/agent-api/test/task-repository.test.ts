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
    const task = repository.create({
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

    expect(repository.get(task.id)).toEqual(task);
    expect(task).toMatchObject({
      id: "task-1",
      status: "todo",
      createdAt: "2026-08-11T00:00:00.000Z",
      completedAt: null,
    });
  });

  it("filters and paginates by course, status, and search text", () => {
    repository.create({ title: "Review lighting", courseId: "cs3481" });
    const completed = repository.create({ title: "Read heritage case", courseId: "ge2324" });
    repository.complete(completed.id);
    repository.create({ title: "Practice rasterization", courseId: "cs3481" });

    const csTasks = repository.list({ page: 1, pageSize: 10, courseId: "cs3481" });
    const done = repository.list({ page: 1, pageSize: 10, status: "completed" });
    const search = repository.list({ page: 1, pageSize: 1, query: "raster" });

    expect(csTasks.total).toBe(2);
    expect(csTasks.items.every((task) => task.courseId === "cs3481")).toBe(true);
    expect(done.items.map((task) => task.id)).toEqual([completed.id]);
    expect(search.total).toBe(1);
    expect(search.items[0]?.title).toBe("Practice rasterization");
  });

  it("updates, completes, reopens, and deletes without changing creation time", () => {
    const created = repository.create({ title: "Read notes" });

    const updated = repository.update(created.id, {
      title: "Read lecture notes",
      status: "in_progress",
      priority: "medium",
    });
    const completed = repository.complete(created.id);
    const reopened = repository.update(created.id, { status: "todo" });
    const deleted = repository.delete(created.id);

    expect(updated?.createdAt).toBe(created.createdAt);
    expect(updated?.status).toBe("in_progress");
    expect(completed?.status).toBe("completed");
    expect(completed?.completedAt).toBe("2026-08-11T00:00:00.000Z");
    expect(reopened?.completedAt).toBeNull();
    expect(deleted).toBe(true);
    expect(repository.get(created.id)).toBeNull();
  });

  it("returns null or false for missing task IDs", () => {
    expect(repository.get("missing")).toBeNull();
    expect(repository.update("missing", { title: "No task" })).toBeNull();
    expect(repository.complete("missing")).toBeNull();
    expect(repository.delete("missing")).toBe(false);
  });

  it("stores SQL-looking input as data and preserves the table", () => {
    const title = "'); DROP TABLE tasks; --";
    const task = repository.create({ title });

    expect(repository.get(task.id)?.title).toBe(title);
    expect(repository.list({ page: 1, pageSize: 10 }).total).toBe(1);
  });
});
