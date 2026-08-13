import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  renameConversation,
  SseDecoder,
  streamQa,
} from "./ragApi";


describe("SseDecoder", () => {
  it("decodes named JSON events split across arbitrary chunks", () => {
    const decoder = new SseDecoder();

    const first = decoder.push('event: delta\ndata: {"te');
    const second = decoder.push('xt":"Phong"}\n\nevent: citation\ndata: {"chunkId":"c1"}\n');
    const third = decoder.push("\n");

    expect(first).toEqual([]);
    expect(second).toEqual([{ event: "delta", data: { text: "Phong" } }]);
    expect(third).toEqual([{ event: "citation", data: { chunkId: "c1" } }]);
  });

  it("supports CRLF and a final frame without a trailing blank line", () => {
    const decoder = new SseDecoder();

    expect(decoder.push('event: done\r\ndata: {"ok":true}\r\n')).toEqual([]);
    expect(decoder.flush()).toEqual([{ event: "done", data: { ok: true } }]);
  });
});

describe("conversation API", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("uses authenticated owner-scoped resource endpoints", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [], page: 1, pageSize: 100, total: 0 })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "conv_1" })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "conv_1", messages: [] })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "conv_1", title: "Renamed" })))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    const getToken = vi.fn().mockResolvedValue("token-a");

    await listConversations(getToken, "cs3481");
    await createConversation(getToken, "cs3481", "zh-CN");
    await getConversation(getToken, "conv_1");
    await renameConversation(getToken, "conv_1", "Renamed");
    await deleteConversation(getToken, "conv_1");

    expect(fetchMock.mock.calls.map(([url, init]) => [url, init?.method ?? "GET"]))
      .toEqual([
        [expect.stringContaining("/api/conversations?courseId=cs3481"), "GET"],
        [expect.stringContaining("/api/conversations"), "POST"],
        [expect.stringContaining("/api/conversations/conv_1"), "GET"],
        [expect.stringContaining("/api/conversations/conv_1"), "PATCH"],
        [expect.stringContaining("/api/conversations/conv_1"), "DELETE"],
      ]);
    for (const [, init] of fetchMock.mock.calls) {
      expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer token-a");
    }
  });

  it("sends an existing conversation id when continuing a stream", async () => {
    const encoder = new TextEncoder();
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      new ReadableStream({
        start(controller) {
          controller.enqueue(encoder.encode('event: done\ndata: {"ok":true}\n\n'));
          controller.close();
        },
      }),
    ));
    vi.stubGlobal("fetch", fetchMock);

    await streamQa(
      vi.fn().mockResolvedValue("token-a"),
      "cs3481",
      "继续解释",
      { onDelta: vi.fn(), onCitation: vi.fn() },
      undefined,
      "conv_123",
    );

    const request = fetchMock.mock.calls[0]?.[1];
    expect(request).toBeDefined();
    expect(JSON.parse(String(request?.body))).toEqual({
      courseId: "cs3481",
      question: "继续解释",
      conversationId: "conv_123",
    });
  });
});
