import fs from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";


const SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  owner_user_id TEXT NOT NULL,
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

CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rate_limit_windows (
  owner_user_id TEXT NOT NULL,
  action TEXT NOT NULL,
  window_start INTEGER NOT NULL,
  request_count INTEGER NOT NULL CHECK (request_count >= 0),
  PRIMARY KEY (owner_user_id, action, window_start)
);

`;

const LEGACY_OWNER_USER_ID = "legacy_orphaned";

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
    const columns = this.connection.prepare("PRAGMA table_info(tasks)").all() as Array<{
      name: string;
    }>;
    if (!columns.some((column) => column.name === "owner_user_id")) {
      this.connection.exec(
        `ALTER TABLE tasks ADD COLUMN owner_user_id TEXT NOT NULL DEFAULT '${LEGACY_OWNER_USER_ID}'`,
      );
    }
    this.connection.exec(`
      CREATE INDEX IF NOT EXISTS idx_tasks_owner_status_due
      ON tasks(owner_user_id, status, due_date);
      CREATE INDEX IF NOT EXISTS idx_tasks_owner_course_status
      ON tasks(owner_user_id, course_id, status);
      INSERT OR IGNORE INTO schema_migrations (version, name)
      VALUES (1, 'task ownership and per-user limits');
    `);
  }

  close(): void {
    this.connection.close();
  }
}
