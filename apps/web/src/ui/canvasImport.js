/**
 * Client for the Canvas private-import routes.
 *
 * The routes live on the RAG API host (`/api/integrations/canvas/...`), a sibling of the
 * ui-extension base the rest of this client uses — the same arrangement `submitFeedback` already
 * has. Every call carries the sign-in token in the `Authorization` header and never in a URL.
 *
 * Two rules the UI must not break, and which this module keeps in one place so it cannot:
 *   * the normal student path uses the school's OAuth page or the local bridge. The only web
 *     personal-access-token input is the explicitly enabled owner task-credential flow below;
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
  if (response.status === 204) return null;
  const contentType = String(response.headers?.get?.("content-type") || "")
    .split(";", 1)[0]
    .trim()
    .toLowerCase();
  const isJson = contentType === "application/json" || contentType.endsWith("+json");
  if (!isJson) {
    const failure = new Error("学校接口返回了网页而不是数据，请稍后重试并提供请求编号。");
    failure.status = response.status;
    failure.code = "API_RESPONSE_NOT_JSON";
    failure.details = { contentType: contentType || "missing" };
    throw failure;
  }
  let body = null;
  try {
    body = await response.json();
  } catch {
    const failure = new Error("学校接口返回的数据格式无效，请稍后重试。");
    failure.status = response.status;
    failure.code = "API_RESPONSE_NOT_JSON";
    failure.details = { contentType };
    throw failure;
  }
  if (!response.ok) {
    const error = body && body.error;
    const message =
      (error && error.message) || `连接学校服务失败（${response.status}）`;
    const failure = new Error(message);
    failure.status = response.status;
    failure.code = (error && error.code) || null;
    failure.details = (error && error.details) || {};
    throw failure;
  }
  return body;
}

/** Which schools can be connected right now, and why not when they cannot. */
export const institutions = () => call("/institutions");

/** The signed-in user's own connections, public fields only (never a token). */
export const connections = () => call("/connections");

/** The student's own readable Canvas courses, for the selection screen. */
export const courses = (connectionId) =>
  call(`/courses?connection_id=${encodeURIComponent(connectionId)}`);

/** Freeze a selection into an import job. The same selection returns the same job. */
export const startImport = (connectionId, courseIds, saveConnection = false, credentialRef = "") =>
  call("/imports", {
    method: "POST",
    body: JSON.stringify({
      connection_id: connectionId,
      course_ids: courseIds,
      save_connection: saveConnection,
      // A reference to a credential the server holds in its own process for this task — never a
      // credential. Empty for the school's own OAuth connection, which is the public path.
      credential_ref: credentialRef,
    }),
  });

export const importStatus = (jobId) => call(`/imports/${encodeURIComponent(jobId)}`);

/** Attach a newly pasted credential to the same frozen import after restart/expiry. */
export const resumeTaskCredential = (
  jobId,
  personalAccessToken,
  { institutionKey = "", canvasBaseUrl = "" } = {},
) =>
  call(`/imports/${encodeURIComponent(jobId)}/credential`, {
    method: "POST",
    body: JSON.stringify({
      personal_access_token: personalAccessToken,
      institution_key: institutionKey,
      canvas_base_url: canvasBaseUrl,
    }),
  });

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

/* ------------------------------------------------------------------ the local bridge
 *
 * The second route to a school, for the case OAuth cannot cover yet: a school that has not issued a
 * Developer Key. The user runs the local bridge on their own machine; a Personal Access Token is read
 * there through a hidden prompt and kept by the operating system, and CourseJesus only ever receives
 * course metadata, file bytes and receipts.
 *
 * The one rule this module enforces for the UI: there is no field, parameter or call here that could
 * carry a token to the server. A code goes out (it is the bridge's claim ticket), the user's own
 * session token authorises the call, and nothing else.
 */

const LOCAL_ROOT = `${API_ROOT}/local-sessions`;

/** Whether this deployment offers the bridge at all, and why not when it does not. */
export const localBridgeCapability = () => call("/local-sessions/capability");

/** Open a session for one registered school and get the one-time code to paste into a terminal. */
export const openLocalSession = (institutionKey) =>
  call("/local-sessions", {
    method: "POST",
    body: JSON.stringify({ institution_key: institutionKey }),
  });

export const localSession = (sessionId) =>
  call(`/local-sessions/${encodeURIComponent(sessionId)}`);

export const selectLocalCourses = (sessionId, courseIds) =>
  call(`/local-sessions/${encodeURIComponent(sessionId)}/selection`, {
    method: "POST",
    body: JSON.stringify({ canvas_course_ids: courseIds }),
  });

export const cancelLocalSession = (sessionId) =>
  call(`/local-sessions/${encodeURIComponent(sessionId)}/cancel`, { method: "POST" });

/**
 * Match a typed school address against the registered schools.
 *
 * The server refuses an unregistered school on purpose: an authorisation flow pointed at an arbitrary
 * host would hand the school's code to whoever owns that host. So the page looks the address up in
 * the list the server gave it, and when there is no match it says the school is not open yet instead
 * of starting anything.
 */
export function institutionForAddress(body, address) {
  const wanted = String(address || "").trim().replace(/\/+$/, "").toLowerCase();
  if (!wanted) return null;
  const list = (body && body.institutions) || [];
  return list.find((item) => String(item.origin || "").toLowerCase() === wanted) || null;
}

/** The exact address the user has to open in Canvas, from the tutorial the task requires. */
export const TOKEN_STEPS = [
  "登录你的学校 Canvas，点右上角 Account（账户）。",
  "打开 Settings（设置）。",
  "在 Approved Integrations（已批准的集成）里点 + New Access Token（新建访问令牌）。",
  "Purpose 填 local import；Expires 选一个短期限；点 Generate Token。",
  "复制 Token，只在本地终端里粘贴，不要粘贴到任何网页。",
];

export const TOKEN_WARNING =
  "为了保护你的 Canvas 凭据，请不要把这个 Token 粘贴到 CourseJesus 网页。" +
  "本地导入工具会通过隐藏输入读取 Token，并保存在你电脑的系统凭据库里。";

/** The command the user runs locally once a session is open. The code is a ticket, not a secret. */
export function bridgeCommand(code) {
  return `canvas-study-assistant bridge --code ${code}`;
}

export const BRIDGE_STEPS = [
  "在同一台电脑上打开终端，运行下面的命令。",
  "工具会隐藏输入你的 Canvas Token（Personal Access Token），并保存到系统凭据库。",
  "工具用 Token 在你本机读取你本人的课程列表，把课程名发回这一页。",
  "在这一页选择要导入的课程，工具才开始下载并上传文件。",
  "Token 不会离开你的电脑；CourseJesus 只收到课程信息、文件和导入回执。",
];

export const LOCAL_STATUS_LABELS = {
  OPEN: "等待本地工具连接",
  CLAIMED: "本地工具已连接，正在读取课程",
  SELECTED: "已选择课程，等待本地工具上传",
  IMPORTING: "正在导入文件",
  COMPLETED: "导入完成",
  COMPLETED_WITH_WARNINGS: "导入完成，但有需要留意的文件",
  FAILED: "导入失败",
  CANCELLED: "已取消",
  EXPIRED: "连接码已过期，请重新生成",
};

/* ------------------------------------------------- the one-off task credential (owner mode)
 *
 * The third route to a school, and the narrowest: a personal access token pasted into this page
 * for **one** import task. It exists because the owner's own testing must not wait for the
 * school's Developer Key, and it is offered only when the deployment enables it for a listed
 * account — the server decides that, and `taskCredentialOf()` reads the answer rather than
 * assuming it.
 *
 * What is different from the OAuth path, and what the screen has to say out loud:
 *   * the token reaches the server, which is the opposite of the local bridge's rule. The page
 *     therefore says so on the step where it is pasted, and the public connect screen separately
 *     says that its normal student path does not accept personal access tokens;
 *   * the server holds it in memory for this one task and destroys it once the Canvas reads are
 *     finished, before any file is parsed or indexed;
 *   * no institution has approved this path for students. It is the owner's testing route, and
 *     the screen says that too instead of implying an approval that does not exist.
 */

/** The capability the server reports for *this* account, or a closed default. */
export function taskCredentialOf(body) {
  const capability = body && body.taskCredential;
  if (!capability || typeof capability !== "object") {
    return { available: false, reason: "TASK_CREDENTIAL_DISABLED", ownerOnly: true };
  }
  return capability;
}

/** Why the one-off credential path is not offered, in the user's words. */
export function taskCredentialReasonFor(reason) {
  if (reason === "TASK_CREDENTIAL_DISABLED") return "";
  if (reason === "NOT_LISTED_FOR_TASK_CREDENTIAL") return "";
  if (reason === "SCHEMA_NOT_READY") return "本部署还没有启用私有课程数据库结构。";
  return "";
}

/** The five steps of the one-off import, shown above the form. */
export const TASK_CREDENTIAL_STEPS = [
  "在 Canvas 里打开 Account（账户）→ Settings（设置）→ + New Access Token。",
  "Purpose 填 CourseJesus 一次性导入，Expires 选最短的有效期，点 Generate Token。",
  "把 Token 粘贴到下面，选择学校，然后点「确认学校账号」。",
  "页面会显示它读到的 Canvas 账号，并列出你可以导入的课程；选好课程再点开始导入。",
  "读到文件后，服务器会立即销毁这个 Token；导入与索引不再使用它。",
];

export const TASK_CREDENTIAL_WARNING =
  "这个 Token 会发送到 CourseJesus 服务器，只在本次导入任务期间保存在内存中，" +
  "完成文件读取后立即销毁，不写入数据库、不写入日志，也不会用于以后的后台同步。";

export const TASK_CREDENTIAL_POLICY_NOTE =
  "这是站长为自己的账号开通的一次性导入方式，学校尚未批准面向所有学生的 Token 方式。";

export const TASK_CREDENTIAL_STATE_LABELS = {
  NEVER_STORED: "没有可用的凭据",
  PRESENT_TRANSIENTLY: "本次任务正在使用中",
  DESTROYING: "正在销毁",
  DESTROYED: "已销毁",
  EXPIRED: "已过期",
  LOST_ON_RESTART: "服务重启后已失效，请重新粘贴",
};

/** The user's words for a lifecycle state, so the screen never shows a raw code. */
export function taskCredentialStateLabel(state) {
  return TASK_CREDENTIAL_STATE_LABELS[state] || "未知状态";
}

/** Whether a job is waiting for a new credential before it can continue. */
export function needsCredentialMessage(status) {
  if (!status || !status.needsCredential) return "";
  const label = taskCredentialStateLabel(status.credentialState);
  return `本次导入的凭据${label}，需要重新粘贴 Token 才能继续。已下载的文件不受影响。`;
}

/**
 * Hold a pasted token for one task. The value is sent once, in the body, and never put in a URL.
 *
 * `institutionKey` and `canvasBaseUrl` are alternatives: the server matches a typed address
 * against its own registry, so an unregistered host is refused rather than contacted.
 */
export const openTaskCredential = (personalAccessToken, { institutionKey = "", canvasBaseUrl = "" } = {}) =>
  call("/task-credentials", {
    method: "POST",
    body: JSON.stringify({
      personal_access_token: personalAccessToken,
      institution_key: institutionKey,
      canvas_base_url: canvasBaseUrl,
    }),
  });

/** The lifecycle state of one held credential, read back from the server that holds it. */
export const taskCredentialState = (credentialRef) =>
  call(`/task-credentials/${encodeURIComponent(credentialRef)}`);

/** Destroy it now, rather than waiting for the task to finish. */
export const forgetTaskCredential = (credentialRef, reason = "user_disconnected") =>
  call(`/task-credentials/${encodeURIComponent(credentialRef)}/forget`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });

/** The student's readable courses, read with the task credential instead of a stored one. */
export const taskCourses = (connectionId, credentialRef) =>
  call(
    `/courses?connection_id=${encodeURIComponent(connectionId)}` +
      `&credential_ref=${encodeURIComponent(credentialRef)}` +
      `&include_file_summary=true`
  );
