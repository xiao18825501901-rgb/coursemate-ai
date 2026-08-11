import fs from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";


const SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 200),
  notes TEXT CHECK (notes IS NULL OR length(notes) <= 5000),
  course_id TEXT,
  status TEXT NOT NULL CHECK (status IN ('todo', 'in_progress', 'completed')),
  priority TEXT NOT NULL CHECK (priority IN ('low', 'medium', 'high')),
  due_date TEXT CHECK (due_date IS NULL OR due_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  source_citation TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_status_due_date ON tasks(status, due_date);
CREATE INDEX IF NOT EXISTS idx_tasks_course_status ON tasks(course_id, status);
`;

export class AgentDatabase {
  readonly connection: DatabaseSync;

  constructor(databasePath: string) {
    if (databasePath !== ":memory:") {
      fs.mkdirSync(path.dirname(databasePath), { recursive: true });
    }
    this.connection = new DatabaseSync(databasePath, {
      enableForeignKeyConstraints: true,
      timeout: 10_000,
    });
    if (databasePath !== ":memory:") {
      this.connection.exec("PRAGMA journal_mode = WAL");
    }
  }

  initialize(): void {
    this.connection.exec(SCHEMA_SQL);
  }

  close(): void {
    this.connection.close();
  }
}
