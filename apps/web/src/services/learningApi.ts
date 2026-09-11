import type { GetSessionToken } from "../auth/AuthProvider";
import type { LearningState } from "../types/learning";
import { requestJson } from "./http";

export const learningBase = `${import.meta.env.VITE_RAG_API_URL ?? "http://localhost:8000"}/api/learning`;
export const v3Enabled = import.meta.env.VITE_V3_ENABLED === "true";
export function joinLearning(getToken: GetSessionToken, courseId: string) {
  return requestJson<{ id: string }>(getToken, `${learningBase}/workspaces`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ course_id: courseId }),
  });
}
export function getLearningState(getToken: GetSessionToken, workspace: string) {
  return requestJson<LearningState>(getToken, `${learningBase}/workspaces/${workspace}/state`);
}
export function learningAction<T>(getToken: GetSessionToken, workspace: string, path: string, payload: unknown, method = "POST") {
  return requestJson<T>(getToken, `${learningBase}/workspaces/${workspace}/${path}`, {
    method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
}
