import { afterEach, describe, expect, it, vi } from "vitest";

import { listLearningDocuments, listProblemIndex } from "./learningApi";


describe("V3 problem source API", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("queries only authenticated workspace-scoped indexes and documents", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [], total: 0 })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: [] })));
    vi.stubGlobal("fetch", fetchMock);
    const getToken = vi.fn().mockResolvedValue("owner-token");

    await listProblemIndex(getToken, "workspace-a", "Q1 50%_match");
    await listLearningDocuments(getToken, "workspace-a");

    expect(fetchMock.mock.calls[0]?.[0]).toContain(
      "/api/learning/workspaces/workspace-a/problem-index?scope=union&limit=50&query=Q1+50%25_match",
    );
    expect(fetchMock.mock.calls[1]?.[0]).toContain(
      "/api/learning/workspaces/workspace-a/documents?scope=union&page_size=100",
    );
    for (const [, init] of fetchMock.mock.calls) {
      expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer owner-token");
    }
  });
});
