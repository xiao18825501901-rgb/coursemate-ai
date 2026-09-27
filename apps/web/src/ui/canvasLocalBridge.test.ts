
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  BRIDGE_STEPS,
  bridgeCommand,
  institutionForAddress,
  localBridgeCapability,
  localSession,
  LOCAL_STATUS_LABELS,
  openLocalSession,
  selectLocalCourses,
  TOKEN_STEPS,
  TOKEN_WARNING,
} from "./canvasImport.js";

/**
 * The local-bridge client and the rule that shapes it.
 *
 * The product revision is explicit: OAuth is the production route for every user, and the local
 * Personal-Access-Token route is a bridge for a school that has not issued a Developer Key — with the
 * token never reaching CourseJesus. That is a claim about code, so it is checked here:
 *
 *   * the client's calls carry a one-time *code* out and the user's own session token, never a Canvas
 *     credential in any direction;
 *   * this public bridge has no credential input or credential-bearing request. A separately
 *     gated owner flow is the only web exception, and the build scanner verifies that boundary;
 *   * the tutorial the task requires is present, and so is the sentence that tells public users
 *     not to paste a token into this path.
 */

const calls: { url: string; options: RequestInit }[] = [];

type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

function stubFetch({ ok = true, status = 200, body = {} } = {}): FetchLike {
  return (async (input: RequestInfo | URL, init: RequestInit = {}) => {
    calls.push({ url: String(input), options: init });
    return {
      ok,
      status,
      headers: { get: (name: string) => name.toLowerCase() === "content-type" ? "application/json" : null },
      json: async () => body,
    } as unknown as Response;
  }) as unknown as FetchLike;
}

function callAt(index: number): { url: string; options: RequestInit } {
  const entry = calls[index];
  if (!entry) throw new Error(`no recorded call at index ${index}`);
  return entry;
}

beforeEach(() => {
  calls.length = 0;
  globalThis.fetch = stubFetch();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("local bridge client", () => {
  it("asks whether the deployment offers the bridge", async () => {
    await localBridgeCapability();
    expect(callAt(0).url).toBe("/api/integrations/canvas/local-sessions/capability");
  });

  it("opens a session with a school key and sends no credential", async () => {
    await openLocalSession("cityu");
    const call = callAt(0);
    expect(call.url).toBe("/api/integrations/canvas/local-sessions");
    expect(call.options.method).toBe("POST");
    const body = JSON.parse(String(call.options.body));
    expect(body).toEqual({ institution_key: "cityu" });
    // The whole body is the school key: there is no field a token could travel in.
    expect(Object.keys(body)).toEqual(["institution_key"]);
  });

  it("polls a session and selects courses by Canvas course id only", async () => {
    await localSession("cls_1");
    expect(callAt(0).url).toBe("/api/integrations/canvas/local-sessions/cls_1");

    await selectLocalCourses("cls_1", ["560", "240"]);
    const call = callAt(1);
    expect(call.url).toBe("/api/integrations/canvas/local-sessions/cls_1/selection");
    expect(JSON.parse(String(call.options.body))).toEqual({
      canvas_course_ids: ["560", "240"],
    });
  });

  it("encodes a session id into the path instead of interpolating it raw", async () => {
    await localSession("cls/../evil");
    expect(callAt(0).url).toBe("/api/integrations/canvas/local-sessions/cls%2F..%2Fevil");
  });

  it("matches a typed school address against the registry and refuses an unknown one", () => {
    const body = {
      institutions: [
        { key: "cityu", origin: "https://canvas.cityu.edu.hk", label: "CityU" },
        { key: "cityu-dg", origin: "https://cityu-dg.instructure.com", label: "CityU (DG)" },
      ],
    };
    expect(institutionForAddress(body, "https://canvas.cityu.edu.hk")?.key).toBe("cityu");
    // A trailing slash and a different case are the same school.
    expect(institutionForAddress(body, "HTTPS://Canvas.CityU.edu.hk/")?.key).toBe("cityu");
    // Anything else is refused rather than guessed: an unknown host cannot be connected.
    expect(institutionForAddress(body, "https://evil.example")).toBeNull();
    expect(institutionForAddress(body, "")).toBeNull();
  });

  it("gives the user the command, the steps and the warning the task requires", () => {
    expect(bridgeCommand("abc123")).toBe(
      'CourseJesus-Canvas-Bridge.exe --ticket "abc123"',
    );
    expect(bridgeCommand("abc123")).not.toContain("--code");
    expect(BRIDGE_STEPS.join(" ")).toContain("不需要安装 Python、WSL 或修改 PATH");
    expect(TOKEN_STEPS.join(" ")).toContain("Approved Integrations");
    expect(TOKEN_STEPS.join(" ")).toContain("New Access Token");
    expect(TOKEN_WARNING).toContain("不要把这个 Token 粘贴到 CourseJesus 网页");
    expect(TOKEN_WARNING).toContain("隐藏输入");
    // Every bridge state the screen can show has words, so no raw enum reaches the student.
    const labels: Record<string, string> = LOCAL_STATUS_LABELS;
    for (const state of ["OPEN", "CLAIMED", "SELECTED", "IMPORTING", "COMPLETED", "EXPIRED"]) {
      expect(labels[state]).toBeTruthy();
    }
  });
});
