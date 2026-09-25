import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  cancelImport,
  canvasApiRoot,
  connectUrl,
  connectableInstitutions,
  connections,
  courses,
  disconnect,
  importStatus,
  institutions,
  needsCredentialMessage,
  openTaskCredential,
  outcomeFromSearch,
  reasonFor,
  resumeTaskCredential,
  setCanvasTokenGetter,
  startImport,
  taskCourses,
  taskCredentialOf,
  taskCredentialState,
  taskCredentialStateLabel,
} from "./canvasImport.js";

/**
 * The Canvas client is the only place the import UI talks to the server, so these tests pin the
 * things a screen can silently get wrong: the URL and method of every call, that the token goes
 * in a header and never in a URL, that a failed call surfaces the server's code, and that a school
 * which is not connectable is described rather than offered.
 */

const calls: { url: string; options: RequestInit }[] = [];

type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

/** A fetch stub: only the fields this client reads exist, and the cast says so out loud. */
function stubFetch({ ok = true, status = 200, body = {}, contentType = "application/json" } = {}): FetchLike {
  return (async (input: RequestInfo | URL, init: RequestInit = {}) => {
    calls.push({ url: String(input), options: init });
    return {
      ok,
      status,
      headers: { get: (name: string) => name.toLowerCase() === "content-type" ? contentType : null },
      json: async () => body,
    } as unknown as Response;
  }) as unknown as FetchLike;
}

/** The n-th recorded call, or a failed test: the project checks undefined indexes. */
function callAt(index: number): { url: string; options: RequestInit } {
  const entry = calls[index];
  if (!entry) throw new Error(`no recorded call at index ${index}`);
  return entry;
}

beforeEach(() => {
  calls.length = 0;
  globalThis.fetch = stubFetch();
  setCanvasTokenGetter(async () => "session-token");
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Canvas import client", () => {
  it("targets the configured RAG origin instead of the frontend SPA fallback", () => {
    expect(canvasApiRoot("https://rag.47-237-179-69.sslip.io/"))
      .toBe("https://rag.47-237-179-69.sslip.io/api/integrations/canvas");
    expect(canvasApiRoot(""))
      .toBe("/api/integrations/canvas");
  });

  it("asks for the institution list with the session token in a header", async () => {
    await institutions();
    const first = callAt(0);
    expect(first.url).toBe("/api/integrations/canvas/institutions");
    expect((first.options.headers as Record<string, string>).Authorization).toBe(
      "Bearer session-token",
    );
    expect(first.url).not.toContain("session-token");
    // Cross-origin production calls authenticate with the bearer token. Sending browser cookies
    // would require credentialed CORS and is both unnecessary and rejected by the RAG service.
    expect(first.options.credentials).toBe("omit");
  });

  it("reads courses for one connection and encodes the id", async () => {
    await courses("conn/with space");
    const first = callAt(0);
    expect(first.url).toBe("/api/integrations/canvas/courses?connection_id=conn%2Fwith%20space");
    expect(first.options.method ?? "GET").toBe("GET");
  });

  it("posts a frozen selection with the opt-in flag it was given", async () => {
    await startImport("conn-1", ["560", "240"], true);
    const first = callAt(0);
    expect(first.url).toBe("/api/integrations/canvas/imports");
    expect(first.options.method).toBe("POST");
    expect(JSON.parse(String(first.options.body))).toEqual({
      connection_id: "conn-1",
      course_ids: ["560", "240"],
      save_connection: true,
      credential_ref: "",
    });
    // Saving a connection is opt-in: the default must not ask for it.
    await startImport("conn-1", ["560"]);
    expect(JSON.parse(String(callAt(1).options.body)).save_connection).toBe(false);
  });

  it("sends a task credential as a reference, and only when one was opened", async () => {
    // The owner-mode path names a credential the server holds in its own process. What travels is
    // an opaque reference the server minted — never the token, which this client submitted once,
    // over the one route that accepts it.
    await startImport("conn-1", ["560"], false, "ref-abc123");
    const body = JSON.parse(String(callAt(0).options.body));
    expect(body.credential_ref).toBe("ref-abc123");
    expect(body.save_connection).toBe(false);

    await openTaskCredential("pasted-value", { institutionKey: "cityu" });
    const opened = JSON.parse(String(callAt(1).options.body));
    expect(callAt(1).url).toBe("/api/integrations/canvas/task-credentials");
    expect(callAt(1).options.method).toBe("POST");
    expect(opened).toEqual({
      personal_access_token: "pasted-value",
      institution_key: "cityu",
      canvas_base_url: "",
    });
    // The credential is in the body, never in the URL, and never on the courses call that uses it.
    await taskCourses("conn-1", "ref-abc123");
    expect(callAt(2).url).toBe(
      "/api/integrations/canvas/courses?connection_id=conn-1&credential_ref=ref-abc123" +
        "&include_file_summary=true",
    );
    expect(callAt(2).url).not.toContain("pasted-value");
  });

  it("reattaches a replacement credential to the same frozen import", async () => {
    await resumeTaskCredential("job/with space", "replacement-value", {
      canvasBaseUrl: "https://canvas.cityu.edu.hk/profile/settings",
    });

    const request = callAt(0);
    expect(request.url).toBe(
      "/api/integrations/canvas/imports/job%2Fwith%20space/credential",
    );
    expect(request.options.method).toBe("POST");
    expect(JSON.parse(String(request.options.body))).toEqual({
      personal_access_token: "replacement-value",
      institution_key: "",
      canvas_base_url: "https://canvas.cityu.edu.hk/profile/settings",
    });
    expect(request.url).not.toContain("replacement-value");
  });

  it("polls a job, cancels it and disconnects with the documented methods", async () => {
    await importStatus("job-1");
    await cancelImport("job-1");
    await disconnect("conn-1");
    expect(calls.map((entry) => [entry.url, entry.options.method ?? "GET"])).toEqual([
      ["/api/integrations/canvas/imports/job-1", "GET"],
      ["/api/integrations/canvas/imports/job-1/cancel", "POST"],
      ["/api/integrations/canvas/connections/conn-1", "DELETE"],
    ]);
  });

  it("never sends a personal access token anywhere on the public path", async () => {
    const { connectUrl: url } = await import("./canvasImport.js");
    expect(url("cityu")).toBe("/api/integrations/canvas/connect?institution=cityu");
    expect(url("cityu")).not.toMatch(/token|pat|access/i);
    // `credential_ref` is a reference, not a credential, and the OAuth route still takes no token.
    expect(startImport.length).toBeLessThanOrEqual(3);
  });

  it("surfaces the server's error code and details instead of a blank failure", async () => {
    globalThis.fetch = stubFetch({
      ok: false,
      status: 503,
      body: {
        error: {
          code: "CANVAS_NOT_CONFIGURED",
          message: "Canvas import is not available on this deployment yet.",
          details: { reason: "NO_CREDENTIAL_KEY" },
        },
      },
    });
    await expect(institutions()).rejects.toMatchObject({
      status: 503,
      code: "CANVAS_NOT_CONFIGURED",
      details: { reason: "NO_CREDENTIAL_KEY" },
      message: "Canvas import is not available on this deployment yet.",
    });
  });

  it("still reports a failure whose body is not the documented shape", async () => {
    globalThis.fetch = (async () =>
      ({
        ok: false,
        status: 502,
        headers: { get: () => "text/html; charset=utf-8" },
        json: async () => {
          throw new Error("not json");
        },
      }) as unknown as Response) as unknown as typeof fetch;
    await expect(connections()).rejects.toMatchObject({
      status: 502,
      code: "API_RESPONSE_NOT_JSON",
    });
  });

  it("rejects a successful SPA fallback before attempting to parse it as JSON", async () => {
    globalThis.fetch = stubFetch({
      ok: true,
      status: 200,
      body: "<html>CourseJesus</html>",
      contentType: "text/html; charset=utf-8",
    });

    await expect(institutions()).rejects.toMatchObject({
      status: 200,
      code: "API_RESPONSE_NOT_JSON",
    });
  });

  it("describes an unavailable school instead of offering it", () => {
    const body = {
      credentialsReady: true,
      institutions: [
        { key: "cityu", label: "CityU", connectable: false, reason: "NO_DEVELOPER_KEY" },
        { key: "cityu-dg", label: "CityU (DG)", connectable: false, reason: "NO_DEVELOPER_KEY" },
      ],
    };
    expect(connectableInstitutions(body)).toEqual([]);
    expect(reasonFor("NO_DEVELOPER_KEY")).toContain("本地资料上传");
    expect(reasonFor("NO_CREDENTIAL_KEY")).toContain("加密密钥");
    expect(reasonFor("SCHEMA_NOT_READY")).toContain("数据库结构");
    expect(reasonFor("SOMETHING_NEW")).toBe("");
    expect(reasonFor(undefined)).toBe("");

    const mixed = {
      institutions: [
        { key: "cityu", connectable: true, reason: "" },
        { key: "cityu-dg", connectable: false, reason: "NO_DEVELOPER_KEY" },
      ],
    };
    expect(connectableInstitutions(mixed).map((item: { key: string }) => item.key)).toEqual(["cityu"]);
    expect(connectableInstitutions(null)).toEqual([]);
  });

  it("reads only a known callback outcome out of the URL", () => {
    expect(outcomeFromSearch("?canvas=connected")).toBe("connected");
    expect(outcomeFromSearch("?canvas=denied&x=1")).toBe("denied");
    expect(outcomeFromSearch("?canvas=failed")).toBe("failed");
    expect(outcomeFromSearch("?canvas=something-else")).toBe("");
    expect(outcomeFromSearch("")).toBe("");
    expect(outcomeFromSearch(undefined)).toBe("");
  });
});

describe("the one-off task credential, as the client and the screen present it", () => {
  it("is offered only when the server says this account may use it", () => {
    // The screen reads the capability rather than assuming it, and a deployment that has not
    // enabled the path answers as it always did.
    expect(taskCredentialOf({})).toEqual({
      available: false,
      reason: "TASK_CREDENTIAL_DISABLED",
      ownerOnly: true,
    });
    expect(taskCredentialOf({ taskCredential: { available: true, reason: "" } }).available).toBe(true);
    expect(
      taskCredentialOf({ taskCredential: { available: false, reason: "NOT_LISTED_FOR_TASK_CREDENTIAL" } })
        .reason,
    ).toBe("NOT_LISTED_FOR_TASK_CREDENTIAL");
  });

  it("never shows a raw lifecycle code to the user", () => {
    for (const state of [
      "NEVER_STORED",
      "PRESENT_TRANSIENTLY",
      "DESTROYING",
      "DESTROYED",
      "EXPIRED",
      "LOST_ON_RESTART",
    ]) {
      const label = taskCredentialStateLabel(state);
      expect(label).not.toBe(state);
      expect(label).not.toBe("未知状态");
    }
    expect(taskCredentialStateLabel("SOMETHING_ELSE")).toBe("未知状态");
    expect(taskCredentialStateLabel(undefined)).toBe("未知状态");
  });

  it("asks for a new credential only when the server says one is needed", () => {
    expect(needsCredentialMessage({ needsCredential: false, credentialState: "DESTROYED" })).toBe("");
    expect(needsCredentialMessage(null)).toBe("");
    const message = needsCredentialMessage({
      needsCredential: true,
      credentialState: "LOST_ON_RESTART",
    });
    expect(message).toContain("服务重启后已失效");
    expect(message).toContain("已下载的文件不受影响");
  });

  it("reads the credential's state back from the server instead of guessing it", async () => {
    globalThis.fetch = stubFetch({ body: { credentialRef: "ref-1", state: "DESTROYED" } });
    const body = await taskCredentialState("ref/1");
    expect(callAt(0).url).toBe("/api/integrations/canvas/task-credentials/ref%2F1");
    expect(body.state).toBe("DESTROYED");
  });
});
