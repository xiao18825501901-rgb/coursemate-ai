import { afterEach, expect, test, vi } from "vitest";

import { request, setUiErrorTranslator } from "./api.js";

afterEach(() => {
  setUiErrorTranslator(null);
  vi.restoreAllMocks();
});

const translate = (key: string, params: Record<string, unknown> = {}) => ({
  "errors.WORKSPACE_BUSY": "Another operation is in progress. View or continue it",
  "errors.NETWORK_UNAVAILABLE": "Connection unavailable. Your current progress has been retained",
  "errors.HTTP_STATUS": `Request failed (${params.status})`,
  "errors.diagnostic": `Diagnostic ID: ${params.id}`,
}[key] || `MISSING:${key}`);

test("typed API errors localize the safe envelope and retain raw diagnostics privately", async () => {
  setUiErrorTranslator(translate);
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: {
    code: "WORKSPACE_BUSY",
    message: "底层 provider operation is running",
    diagnostic_id: "TEST_ONLY-diag",
  } }), { status: 409, headers: { "Content-Type": "application/json" } }));

  let caught: any;
  try { await request("/test-only"); } catch (error) { caught = error; }
  expect(caught.message).toBe("Another operation is in progress. View or continue it · Diagnostic ID: TEST_ONLY-diag");
  expect(caught.code).toBe("WORKSPACE_BUSY");
  expect(caught.rawMessage).toBe("底层 provider operation is running");
  expect(caught.detail.diagnostic_id).toBe("TEST_ONLY-diag");
});

test("network failures use localized safe copy while cancellation keeps AbortError semantics", async () => {
  setUiErrorTranslator(translate);
  vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new TypeError("TEST_ONLY network detail"));
  await expect(request("/test-only")).rejects.toMatchObject({
    code: "NETWORK_UNAVAILABLE",
    message: "Connection unavailable. Your current progress has been retained",
    rawMessage: "TEST_ONLY network detail",
  });

  const aborted = new DOMException("TEST_ONLY abort", "AbortError");
  vi.mocked(globalThis.fetch).mockRejectedValueOnce(aborted);
  await expect(request("/test-only", { signal: new AbortController().signal })).rejects.toBe(aborted);
});

