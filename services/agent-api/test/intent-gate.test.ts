import { describe, expect, it } from "vitest";

import {
  JevToolIntentGate,
  type FetchImpl,
  type ToolIntentRequest,
} from "../src/tools/intent-gate.js";


function jsonResponse(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as unknown as Response;
}

function request(overrides: Partial<ToolIntentRequest> = {}): ToolIntentRequest {
  return {
    userMessage: "请删除这个任务",
    proposedTool: "deleteTask",
    toolArguments: { taskId: "task-1" },
    actorScope: "owner",
    actorPermissions: ["tasks:write"],
    requiredPermissions: ["tasks:write"],
    isReadOnly: false,
    explicit: false,
    objectRevision: null,
    currentRevision: null,
    ownerUserId: "user-a",
    authorizationScope: "tasks",
    courseId: "c1",
    workspaceId: null,
    materialRevision: null,
    nodeId: null,
    specVersion: null,
    ...overrides,
  };
}

describe("JevToolIntentGate", () => {
  it("makes no HTTP call in off mode", async () => {
    const fetchImpl: FetchImpl = () => {
      throw new Error("off mode must never call fetch");
    };
    const gate = new JevToolIntentGate({ mode: "off", fetchImpl });

    const record = await gate.checkToolIntent(request());

    expect(record).toEqual({
      mode: "off",
      checked: false,
      verdict: "ALLOW",
      reason: "gate_off",
      usedJev: false,
      jevLabel: null,
      receiptId: null,
      path: "disabled",
      jevCalls: 0,
    });
  });

  it("POSTs the bounded body with the internal-token header, never the token in the URL", async () => {
    const seen: { url: string; headers: Record<string, string>; body: string }[] = [];
    const fetchImpl: FetchImpl = (url, init) => {
      seen.push({ url, headers: init.headers, body: init.body });
      return Promise.resolve(
        jsonResponse({
          verdict: "ALLOW",
          reason: "intent_consistent",
          used_jev: true,
          jev_label: "CONSISTENT",
          receipt_id: "receipt-1",
          path: "jev",
          jev_calls: 1,
        }),
      );
    };
    const gate = new JevToolIntentGate({
      mode: "enforce",
      url: "http://internal/jev/tool-intent",
      token: "secret-token",
      fetchImpl,
    });

    const record = await gate.checkToolIntent(request({ ownerUserId: "user-a" }));

    expect(seen).toHaveLength(1);
    expect(seen[0]?.url).toBe("http://internal/jev/tool-intent");
    expect(seen[0]?.url).not.toContain("secret-token");
    expect(seen[0]?.headers["X-CourseMate-Internal-Token"]).toBe("secret-token");
    expect(seen[0]?.headers["Content-Type"]).toBe("application/json");
    const body = JSON.parse(seen[0]?.body ?? "{}") as Record<string, unknown>;
    expect(body["owner_user_id"]).toBe("user-a");
    expect(body["proposed_tool"]).toBe("deleteTask");
    expect(body["explicit"]).toBe(false);
    expect(body["is_read_only"]).toBe(false);
    expect(record).toMatchObject({
      mode: "enforce",
      checked: true,
      verdict: "ALLOW",
      usedJev: true,
      jevLabel: "CONSISTENT",
      receiptId: "receipt-1",
      path: "jev",
      jevCalls: 1,
    });
  });

  it("maps a network error to the fail-safe record", async () => {
    const fetchImpl: FetchImpl = () => Promise.reject(new Error("network down"));
    const gate = new JevToolIntentGate({
      mode: "enforce",
      url: "http://internal/jev",
      token: "t",
      fetchImpl,
    });

    const record = await gate.checkToolIntent(request());

    expect(record).toMatchObject({
      mode: "enforce",
      checked: true,
      verdict: "REQUIRE_CONFIRMATION",
      reason: "intent:unavailable",
      usedJev: false,
      path: "fallback:unavailable",
    });
  });

  it("maps a timeout to the fail-safe record", async () => {
    const fetchImpl: FetchImpl = (_url, init) =>
      new Promise<Response>((_resolve, reject) => {
        init.signal.addEventListener("abort", () =>
          reject(new DOMException("The operation was aborted.", "AbortError")),
        );
      });
    const gate = new JevToolIntentGate({
      mode: "advisory",
      url: "http://internal/jev",
      token: "t",
      timeoutMs: 10,
      fetchImpl,
    });

    const record = await gate.checkToolIntent(request());

    expect(record).toMatchObject({
      mode: "advisory",
      verdict: "REQUIRE_CONFIRMATION",
      reason: "intent:unavailable",
      usedJev: false,
      path: "fallback:unavailable",
    });
  });

  it("maps a non-2xx response to the fail-safe record", async () => {
    const fetchImpl: FetchImpl = () =>
      Promise.resolve(jsonResponse({ error: "boom" }, 503));
    const gate = new JevToolIntentGate({
      mode: "enforce",
      url: "http://internal/jev",
      token: "t",
      fetchImpl,
    });

    const record = await gate.checkToolIntent(request());

    expect(record.verdict).toBe("REQUIRE_CONFIRMATION");
    expect(record.reason).toBe("intent:unavailable");
  });

  it("maps malformed JSON to the fail-safe record", async () => {
    const fetchImpl: FetchImpl = () =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: async () => {
          throw new Error("invalid JSON");
        },
      } as unknown as Response);
    const gate = new JevToolIntentGate({
      mode: "enforce",
      url: "http://internal/jev",
      token: "t",
      fetchImpl,
    });

    const record = await gate.checkToolIntent(request());

    expect(record.verdict).toBe("REQUIRE_CONFIRMATION");
    expect(record.reason).toBe("intent:unavailable");
  });

  it("maps an unrecognized verdict to the fail-safe record", async () => {
    const fetchImpl: FetchImpl = () =>
      Promise.resolve(jsonResponse({ verdict: "GRANT_EVERYTHING", used_jev: false }));
    const gate = new JevToolIntentGate({
      mode: "enforce",
      url: "http://internal/jev",
      token: "t",
      fetchImpl,
    });

    const record = await gate.checkToolIntent(request());

    expect(record.verdict).toBe("REQUIRE_CONFIRMATION");
    expect(record.reason).toBe("intent:unavailable");
  });

  it("preserves REFUSE_UNAUTHORIZED from the Python guard", async () => {
    const fetchImpl: FetchImpl = () =>
      Promise.resolve(
        jsonResponse({
          verdict: "REFUSE_UNAUTHORIZED",
          reason: "missing_permission",
          used_jev: false,
          jev_label: null,
          receipt_id: null,
          path: "deterministic:missing_permission",
          jev_calls: 0,
        }),
      );
    const gate = new JevToolIntentGate({
      mode: "enforce",
      url: "http://internal/jev",
      token: "t",
      fetchImpl,
    });

    const record = await gate.checkToolIntent(request());

    expect(record).toMatchObject({
      verdict: "REFUSE_UNAUTHORIZED",
      reason: "missing_permission",
      usedJev: false,
      path: "deterministic:missing_permission",
      jevCalls: 0,
    });
  });
});
