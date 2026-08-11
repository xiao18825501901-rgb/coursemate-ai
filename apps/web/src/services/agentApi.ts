import { requireOk, requestJson } from "./http";
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

export async function listTasks(filters: TaskFilters = {}): Promise<Page<Task>> {
  const query = new URLSearchParams({ page: "1", pageSize: "100" });
  if (filters.courseId) query.set("courseId", filters.courseId);
  if (filters.status) query.set("status", filters.status);
  if (filters.query) query.set("q", filters.query);
  return requestJson<Page<Task>>(`${AGENT_API}/api/tasks?${query.toString()}`);
}

export async function createTask(input: CreateTaskInput): Promise<Task> {
  return requestJson<Task>(`${AGENT_API}/api/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function updateTask(taskId: string, input: UpdateTaskInput): Promise<Task> {
  return requestJson<Task>(`${AGENT_API}/api/tasks/${encodeURIComponent(taskId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function deleteTask(taskId: string): Promise<void> {
  await requireOk(
    await fetch(`${AGENT_API}/api/tasks/${encodeURIComponent(taskId)}`, { method: "DELETE" }),
  );
}

export async function chatWithAgent(message: string): Promise<AgentChatResponse> {
  return requestJson<AgentChatResponse>(`${AGENT_API}/api/agent/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
}
