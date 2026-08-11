import { describe, expect, it } from "vitest";

import { SseDecoder } from "./ragApi";


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
