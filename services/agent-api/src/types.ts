export type TaskStatus = "todo" | "in_progress" | "completed";
export type TaskPriority = "low" | "medium" | "high";

export interface SourceCitation {
  filename: string;
  locator: string;
  excerpt: string;
}

export interface Task {
  id: string;
  title: string;
  notes: string | null;
  courseId: string | null;
  status: TaskStatus;
  priority: TaskPriority;
  dueDate: string | null;
  sourceCitation: SourceCitation | null;
  createdAt: string;
  updatedAt: string;
  completedAt: string | null;
}

export interface CreateTaskInput {
  title: string;
  notes?: string | null;
  courseId?: string | null;
  priority?: TaskPriority;
  dueDate?: string | null;
  sourceCitation?: SourceCitation | null;
}

export interface UpdateTaskInput {
  title?: string;
  notes?: string | null;
  courseId?: string | null;
  status?: TaskStatus;
  priority?: TaskPriority;
  dueDate?: string | null;
  sourceCitation?: SourceCitation | null;
}

export interface TaskListQuery {
  page: number;
  pageSize: number;
  courseId?: string;
  status?: TaskStatus;
  query?: string;
}

export interface TaskPage {
  items: Task[];
  page: number;
  pageSize: number;
  total: number;
}

export interface ToolResult<T> {
  ok: boolean;
  data: T | null;
  error: { code: string; message: string } | null;
}
