import type { GetSessionToken } from "../auth/AuthProvider";
import { authenticatedFetch, requireOk, requestJson } from "./http";
import type {
  Citation,
  ConversationDetail,
  ConversationSummary,
  Course,
  CourseCreateInput,
  CourseDocument,
  CourseUpdateInput,
  IngestionJob,
  LanguagePreference,
  Page,
  QaStreamMeta,
  UploadAccepted,
} from "../types/api";


const RAG_API = import.meta.env.VITE_RAG_API_URL ?? "http://localhost:8000";

export interface SseEvent {
  event: string;
  data: Record<string, unknown>;
}

export class SseDecoder {
  private buffer = "";

  push(fragment: string): SseEvent[] {
    this.buffer += fragment.replaceAll("\r\n", "\n");
    const frames = this.buffer.split("\n\n");
    this.buffer = frames.pop() ?? "";
    return frames.flatMap((frame) => this.parseFrame(frame));
  }

  flush(): SseEvent[] {
    const frame = this.buffer;
    this.buffer = "";
    return frame.trim() === "" ? [] : this.parseFrame(frame);
  }

  private parseFrame(frame: string): SseEvent[] {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of frame.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
    }
    if (dataLines.length === 0) return [];
    const data: unknown = JSON.parse(dataLines.join("\n"));
    if (typeof data !== "object" || data === null || Array.isArray(data)) {
      throw new Error("SSE data must be a JSON object.");
    }
    return [{ event, data: data as Record<string, unknown> }];
  }
}

export interface QaStreamCallbacks {
  onMeta?: (data: QaStreamMeta) => void;
  onDelta: (text: string) => void;
  onCitation: (citation: Citation) => void;
  onDone?: () => void;
}

export async function listCourses(getToken: GetSessionToken): Promise<Page<Course>> {
  return requestJson<Page<Course>>(getToken, `${RAG_API}/api/courses?page=1&pageSize=100`);
}

export async function createCourse(
  getToken: GetSessionToken,
  input: CourseCreateInput,
): Promise<Course> {
  return requestJson<Course>(getToken, `${RAG_API}/api/courses`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function updateCourse(
  getToken: GetSessionToken,
  courseId: string,
  input: CourseUpdateInput,
): Promise<Course> {
  return requestJson<Course>(
    getToken,
    `${RAG_API}/api/courses/${encodeURIComponent(courseId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
}

export async function deleteCourse(
  getToken: GetSessionToken,
  courseId: string,
): Promise<void> {
  await requireOk(await authenticatedFetch(
    getToken,
    `${RAG_API}/api/courses/${encodeURIComponent(courseId)}`,
    { method: "DELETE" },
  ));
}

export async function listDocuments(
  getToken: GetSessionToken,
  courseId: string,
): Promise<Page<CourseDocument>> {
  return requestJson<Page<CourseDocument>>(
    getToken,
    `${RAG_API}/api/courses/${encodeURIComponent(courseId)}/documents?page=1&pageSize=100`,
  );
}

export async function listConversations(
  getToken: GetSessionToken,
  courseId: string,
): Promise<Page<ConversationSummary>> {
  return requestJson<Page<ConversationSummary>>(
    getToken,
    `${RAG_API}/api/conversations?courseId=${encodeURIComponent(courseId)}&page=1&pageSize=100`,
  );
}

export async function createConversation(
  getToken: GetSessionToken,
  courseId: string,
  preferredLanguage: LanguagePreference = "auto",
): Promise<ConversationSummary> {
  return requestJson<ConversationSummary>(getToken, `${RAG_API}/api/conversations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ courseId, preferredLanguage }),
  });
}

export async function getConversation(
  getToken: GetSessionToken,
  conversationId: string,
): Promise<ConversationDetail> {
  return requestJson<ConversationDetail>(
    getToken,
    `${RAG_API}/api/conversations/${encodeURIComponent(conversationId)}`,
  );
}

export async function renameConversation(
  getToken: GetSessionToken,
  conversationId: string,
  title: string,
): Promise<ConversationSummary> {
  return requestJson<ConversationSummary>(
    getToken,
    `${RAG_API}/api/conversations/${encodeURIComponent(conversationId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    },
  );
}

export async function deleteConversation(
  getToken: GetSessionToken,
  conversationId: string,
): Promise<void> {
  await requireOk(
    await authenticatedFetch(
      getToken,
      `${RAG_API}/api/conversations/${encodeURIComponent(conversationId)}`,
      { method: "DELETE" },
    ),
  );
}

export async function uploadDocument(
  getToken: GetSessionToken,
  courseId: string,
  file: File,
): Promise<UploadAccepted> {
  const body = new FormData();
  body.append("file", file);
  return requestJson<UploadAccepted>(
    getToken,
    `${RAG_API}/api/courses/${encodeURIComponent(courseId)}/documents`,
    { method: "POST", body },
  );
}

export async function getIngestionJob(
  getToken: GetSessionToken,
  jobId: string,
): Promise<IngestionJob> {
  return requestJson<IngestionJob>(
    getToken,
    `${RAG_API}/api/ingestion-jobs/${encodeURIComponent(jobId)}`,
  );
}

export async function deleteDocument(
  getToken: GetSessionToken,
  courseId: string,
  documentId: string,
): Promise<void> {
  await requireOk(await authenticatedFetch(
    getToken,
    `${RAG_API}/api/courses/${encodeURIComponent(courseId)}/documents/${encodeURIComponent(documentId)}`,
    { method: "DELETE" },
  ));
}

export async function streamQa(
  getToken: GetSessionToken,
  courseId: string,
  question: string,
  callbacks: QaStreamCallbacks,
  signal?: AbortSignal,
  conversationId?: string,
): Promise<void> {
  const request: RequestInit = {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      courseId,
      question,
      ...(conversationId === undefined ? {} : { conversationId }),
    }),
  };
  if (signal !== undefined) request.signal = signal;
  const response = await requireOk(
    await authenticatedFetch(getToken, `${RAG_API}/api/qa/chat`, request),
  );
  if (response.body === null) throw new Error("The browser did not provide a response stream.");
  const reader = response.body.getReader();
  const textDecoder = new TextDecoder();
  const sseDecoder = new SseDecoder();

  const dispatch = (item: SseEvent): void => {
    if (item.event === "meta") callbacks.onMeta?.(item.data as QaStreamMeta);
    if (item.event === "delta" && typeof item.data.text === "string") {
      callbacks.onDelta(item.data.text);
    }
    if (item.event === "citation") callbacks.onCitation(item.data as unknown as Citation);
    if (item.event === "done") callbacks.onDone?.();
    if (item.event === "error") {
      const message =
        typeof item.data.message === "string" ? item.data.message : "The answer stream failed.";
      throw new Error(message);
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    for (const item of sseDecoder.push(textDecoder.decode(value, { stream: true }))) dispatch(item);
  }
  for (const item of sseDecoder.push(textDecoder.decode())) dispatch(item);
  for (const item of sseDecoder.flush()) dispatch(item);
}
