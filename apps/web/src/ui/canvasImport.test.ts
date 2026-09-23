import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  cancelImport,
  connectUrl,
  connectableInstitutions,
  connections,
  courses,
  disconnect,
  importStatus,
  institutions,
  outcomeFromSearch,
  reasonFor,
  setCanvasTokenGetter,
  startImport,
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
function stubFetch({ ok = true, status = 200, body = {} } = {}): FetchLike {
  return (async (input: RequestInfo | URL, init: RequestInit = {}) => {
    calls.push({ url: String(input), options: init });
    return { ok, status, json: async () => body } as unknown as Response;
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
  it("asks for the institution list with the session token in a header", async () => {
    await institutions();
    const first = callAt(0);
    expect(first.url).toBe("/api/integrations/canvas/institutions");
    expect((first.options.headers as Record<string, string>).Authorization).toBe(
      "Bearer session-token",
    );
    expect(first.url).not.toContain("session-token");
    expect(first.options.credentials).toBe("include");
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
    });
    // Saving a connection is opt-in: the default must not ask for it.
    await startImport("conn-1", ["560"]);
    expect(JSON.parse(String(callAt(1).options.body)).save_connection).toBe(false);
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

  it("never sends a personal access token anywhere", async () => {
    const { connectUrl: url } = await import("./canvasImport.js");
    expect(url("cityu")).toBe("/api/integrations/canvas/connect?institution=cityu");
    expect(url("cityu")).not.toMatch(/token|pat|access/i);
    // The client has no parameter for one: the only authorisation route is the school's page.
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
        json: async () => {
          throw new Error("not json");
        },
      }) as unknown as Response) as unknown as typeof fetch;
    await expect(connections()).rejects.toMatchObject({ status: 502, code: null });
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
