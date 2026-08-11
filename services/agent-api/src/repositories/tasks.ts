import { randomUUID } from "node:crypto";
import type { DatabaseSync } from "node:sqlite";

import type {
  CreateTaskInput,
  SourceCitation,
  Task,
  TaskListQuery,
  TaskPage,
  TaskPriority,
  TaskStatus,
  UpdateTaskInput,
} from "../types.js";


interface TaskRow {
  id: string;
  title: string;
  notes: string | null;
  course_id: string | null;
  status: TaskStatus;
  priority: TaskPriority;
  due_date: string | null;
  source_citation: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

interface RepositoryOptions {
  clock?: () => Date;
  idFactory?: () => string;
}

function parseCitation(value: string | null): SourceCitation | null {
  if (value === null) {
    return null;
  }
  const parsed: unknown = JSON.parse(value);
  if (
    typeof parsed !== "object" ||
    parsed === null ||
    !("filename" in parsed) ||
    !("locator" in parsed) ||
    !("excerpt" in parsed) ||
    typeof parsed.filename !== "string" ||
    typeof parsed.locator !== "string" ||
    typeof parsed.excerpt !== "string"
  ) {
    throw new Error("Stored task citation is invalid.");
  }
  return {
    filename: parsed.filename,
    locator: parsed.locator,
    excerpt: parsed.excerpt,
  };
}

function mapTask(row: TaskRow): Task {
  return {
    id: row.id,
    title: row.title,
    notes: row.notes,
    courseId: row.course_id,
    status: row.status,
    priority: row.priority,
    dueDate: row.due_date,
    sourceCitation: parseCitation(row.source_citation),
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    completedAt: row.completed_at,
  };
}

export class TaskRepository {
  private readonly clock: () => Date;
  private readonly idFactory: () => string;

  constructor(
    private readonly database: DatabaseSync,
    options: RepositoryOptions = {},
  ) {
    this.clock = options.clock ?? (() => new Date());
    this.idFactory = options.idFactory ?? (() => `task_${randomUUID()}`);
  }

  create(input: CreateTaskInput): Task {
    const now = this.clock().toISOString();
    const id = this.idFactory();
    this.database
      .prepare(
        `INSERT INTO tasks (
          id, title, notes, course_id, status, priority, due_date,
          source_citation, created_at, updated_at, completed_at
        ) VALUES (?, ?, ?, ?, 'todo', ?, ?, ?, ?, ?, NULL)`,
      )
      .run(
        id,
        input.title,
        input.notes ?? null,
        input.courseId ?? null,
        input.priority ?? "medium",
        input.dueDate ?? null,
        input.sourceCitation === undefined || input.sourceCitation === null
          ? null
          : JSON.stringify(input.sourceCitation),
        now,
        now,
      );
    const task = this.get(id);
    if (task === null) {
      throw new Error("Created task could not be loaded.");
    }
    return task;
  }

  get(id: string): Task | null {
    const row = this.database.prepare("SELECT * FROM tasks WHERE id = ?").get(id) as
      | TaskRow
      | undefined;
    return row === undefined ? null : mapTask(row);
  }

  list(query: TaskListQuery): TaskPage {
    const clauses: string[] = [];
    const values: Array<string | number> = [];
    if (query.courseId !== undefined) {
      clauses.push("course_id = ?");
      values.push(query.courseId);
    }
    if (query.status !== undefined) {
      clauses.push("status = ?");
      values.push(query.status);
    }
    if (query.query !== undefined && query.query.trim() !== "") {
      clauses.push("(title LIKE ? OR notes LIKE ?)");
      const search = `%${query.query.trim()}%`;
      values.push(search, search);
    }
    const where = clauses.length === 0 ? "" : `WHERE ${clauses.join(" AND ")}`;
    const count = this.database
      .prepare(`SELECT COUNT(*) AS total FROM tasks ${where}`)
      .get(...values) as { total: number };
    const offset = (query.page - 1) * query.pageSize;
    const rows = this.database
      .prepare(
        `SELECT * FROM tasks ${where}
         ORDER BY created_at DESC, id DESC
         LIMIT ? OFFSET ?`,
      )
      .all(...values, query.pageSize, offset) as unknown as TaskRow[];
    return {
      items: rows.map(mapTask),
      page: query.page,
      pageSize: query.pageSize,
      total: count.total,
    };
  }

  update(id: string, input: UpdateTaskInput): Task | null {
    if (this.get(id) === null) {
      return null;
    }
    const assignments: string[] = [];
    const values: Array<string | null> = [];
    const add = (column: string, value: string | null): void => {
      assignments.push(`${column} = ?`);
      values.push(value);
    };
    if (input.title !== undefined) add("title", input.title);
    if (input.notes !== undefined) add("notes", input.notes);
    if (input.courseId !== undefined) add("course_id", input.courseId);
    if (input.priority !== undefined) add("priority", input.priority);
    if (input.dueDate !== undefined) add("due_date", input.dueDate);
    if (input.sourceCitation !== undefined) {
      add(
        "source_citation",
        input.sourceCitation === null ? null : JSON.stringify(input.sourceCitation),
      );
    }
    if (input.status !== undefined) {
      add("status", input.status);
      add("completed_at", input.status === "completed" ? this.clock().toISOString() : null);
    }
    if (assignments.length === 0) {
      return this.get(id);
    }
    add("updated_at", this.clock().toISOString());
    this.database
      .prepare(`UPDATE tasks SET ${assignments.join(", ")} WHERE id = ?`)
      .run(...values, id);
    return this.get(id);
  }

  complete(id: string): Task | null {
    return this.update(id, { status: "completed" });
  }

  delete(id: string): boolean {
    return this.database.prepare("DELETE FROM tasks WHERE id = ?").run(id).changes === 1;
  }
}
