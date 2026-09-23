/**
 * Client for the Canvas private-import routes.
 *
 * The routes live on the RAG API host (`/api/integrations/canvas/...`), a sibling of the
 * ui-extension base the rest of this client uses — the same arrangement `submitFeedback` already
 * has. Every call carries the sign-in token in the `Authorization` header and never in a URL.
 *
 * Two rules the UI must not break, and which this module keeps in one place so it cannot:
 *   * there is no personal-access-token input anywhere — the only way to reach a school is the
 *     school's own OAuth page, opened by a full-page navigation to `connectUrl()`;
 *   * a connection that is not `connectable` must be rendered as "not open yet" with the local
 *     upload fallback, so `reasonFor()` turns the server's reason code into a sentence rather
 *     than leaving a button that fails on click.
 */

const API_ROOT = "/api/integrations/canvas";

let tokenGetter = async () => null;

/** The ui-extension shell owns the one token getter; this client reuses it. */
export function setCanvasTokenGetter(fn) {
  tokenGetter = fn;
}

async function call(path, options = {}) {
  const token = await tokenGetter();
  const headers = {
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  const response = await fetch(API_ROOT + path, {
    ...options,
    headers: { ...headers, ...options.headers },
    credentials: "include",
    cache: "no-store",
  });
  if (!response.ok) {
    let body = null;
    try {
      body = await response.json();
    } catch {
      /* a non-JSON error body is still an error */
    }
    const error = body && body.error;
    const message =
      (error && error.message) || `连接学校服务失败（${response.status}）`;
    const failure = new Error(message);
    failure.status = response.status;
    failure.code = (error && error.code) || null;
    failure.details = (error && error.details) || {};
    throw failure;
  }
  if (response.status === 204) return null;
  return response.json();
}

/** Which schools can be connected right now, and why not when they cannot. */
export const institutions = () => call("/institutions");

/** The signed-in user's own connections, public fields only (never a token). */
export const connections = () => call("/connections");

/** The student's own readable Canvas courses, for the selection screen. */
export const courses = (connectionId) =>
  call(`/courses?connection_id=${encodeURIComponent(connectionId)}`);

/** Freeze a selection into an import job. The same selection returns the same job. */
export const startImport = (connectionId, courseIds, saveConnection = false) =>
  call("/imports", {
    method: "POST",
    body: JSON.stringify({
      connection_id: connectionId,
      course_ids: courseIds,
      save_connection: saveConnection,
    }),
  });

export const importStatus = (jobId) => call(`/imports/${encodeURIComponent(jobId)}`);

export const cancelImport = (jobId) =>
  call(`/imports/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });

export const disconnect = (connectionId) =>
  call(`/connections/${encodeURIComponent(connectionId)}`, { method: "DELETE" });

/**
 * The school's authorisation page, which the browser must open as a full-page navigation:
 * the school redirects back to our callback and the server sends the user on to the import page.
 */
export const connectUrl = (institutionKey) =>
  `${API_ROOT}/connect?institution=${encodeURIComponent(institutionKey)}`;

const REASONS = {
  NO_DEVELOPER_KEY: "学校连接尚未开通：学校还没有为本站签发 Developer Key，请使用本地资料上传。",
  NO_CREDENTIAL_KEY: "学校连接尚未开通：本部署还没有配置凭据加密密钥，请使用本地资料上传。",
  SCHEMA_NOT_READY: "学校连接尚未开通：本部署还没有启用私有课程数据库结构。",
};

/** Turn the server's reason code into a sentence the import screen can show. */
export function reasonFor(reason) {
  return REASONS[reason] || "";
}

/** Whether any school can be connected at all, which decides the screen's headline. */
export function connectableInstitutions(body) {
  const list = (body && body.institutions) || [];
  return list.filter((item) => item.connectable);
}

/**
 * The outcome the callback appended to the import page's URL (`?canvas=connected|denied|failed`),
 * read once so the shell can report it and strip it from the address bar.
 */
export function outcomeFromSearch(search) {
  const value = new URLSearchParams(search || "").get("canvas");
  return ["connected", "denied", "failed"].includes(value) ? value : "";
}

export const OUTCOME_MESSAGES = {
  connected: "学校账号已连接，可以选择要导入的课程了。",
  denied: "你取消了学校授权，没有连接任何账号。",
  failed: "学校授权没有完成，可以重新连接或先上传本地资料。",
};
