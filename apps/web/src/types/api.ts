export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
  };
}

export interface Page<T> {
  items: T[];
  page: number;
  pageSize: number;
  total: number;
}

export interface Course {
  id: string;
  name: string;
  description: string;
  createdAt: string;
}

export type DocumentStatus = "pending" | "processing" | "ready" | "failed" | "unsupported";

export interface CourseDocument {
  id: string;
  courseId: string;
  filename: string;
  mediaType: string;
  extension: string;
  sha256: string;
  status: DocumentStatus;
  chunkCount: number;
  errorMessage: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface Citation {
  sourceLabel: string;
  courseId: string;
  documentId: string;
  chunkId: string;
  filename: string;
  locatorType: string;
  locatorValue: string;
  section: string | null;
  excerpt: string;
  channels: string[];
}

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
}

export interface ToolResult {
  ok: boolean;
  data: unknown;
  error: { code: string; message: string } | null;
}

export interface AgentChatResponse {
  message: string;
  toolResults: ToolResult[];
}
