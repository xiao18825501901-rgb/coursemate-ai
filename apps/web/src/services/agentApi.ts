import type { GetSessionToken } from "../auth/AuthProvider";
import { authenticatedFetch, requireOk, requestJson } from "./http";
import type {
  AgentChatResponse,
  CreateTaskInput,
  Page,
  Task,
  TaskStatus,
  UpdateTaskInput,
} from "../types/api";


const AGENT_API = import.meta.env.VITE_AGENT_API_URL ?? "http://localhost:8001";

export interface TaskFilters {
  courseId?: string;
  status?: TaskStatus;
  query?: string;
}

export async function listTasks(
  getToken: GetSessionToken,
  filters: TaskFilters = {},
): Promise<Page<Task>> {
  const query = new URLSearchParams({ page: "1", pageSize: "100" });
  if (filters.courseId) query.set("courseId", filters.courseId);
  if (filters.status) query.set("status", filters.status);
  if (filters.query) query.set("q", filters.query);
  return requestJson<Page<Task>>(getToken, `${AGENT_API}/api/tasks?${query.toString()}`);
}

export async function createTask(getToken: GetSessionToken, input: CreateTaskInput): Promise<Task> {
  return requestJson<Task>(getToken, `${AGENT_API}/api/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function updateTask(
  getToken: GetSessionToken,
  taskId: string,
  input: UpdateTaskInput,
): Promise<Task> {
  return requestJson<Task>(getToken, `${AGENT_API}/api/tasks/${encodeURIComponent(taskId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function deleteTask(getToken: GetSessionToken, taskId: string): Promise<void> {
  await requireOk(
    await authenticatedFetch(
      getToken,
      `${AGENT_API}/api/tasks/${encodeURIComponent(taskId)}`,
      { method: "DELETE" },
    ),
  );
}

export async function chatWithAgent(
  getToken: GetSessionToken,
  message: string,
): Promise<AgentChatResponse> {
  return requestJson<AgentChatResponse>(getToken, `${AGENT_API}/api/agent/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
}
