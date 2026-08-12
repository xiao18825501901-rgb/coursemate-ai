import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, authenticatedFetch } from "./http";


describe("authenticatedFetch", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
  });

  it("adds the Clerk bearer token while preserving other headers", async () => {
    await authenticatedFetch(async () => "session-token", "https://api.example.test/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });

    const [, init] = vi.mocked(fetch).mock.calls[0] ?? [];
    const headers = new Headers(init?.headers);
    expect(headers.get("Authorization")).toBe("Bearer session-token");
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("fails before the network when no session token exists", async () => {
    await expect(
      authenticatedFetch(async () => null, "https://api.example.test/tasks"),
    ).rejects.toEqual(expect.objectContaining({
      status: 401,
      code: "UNAUTHENTICATED",
    }) as Partial<ApiError>);
    expect(fetch).not.toHaveBeenCalled();
  });
});
