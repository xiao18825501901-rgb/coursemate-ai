import { describe, expect, it } from "vitest";

import {
  REFERENCE_CONTRADICTED,
  REFERENCE_STALE,
  REFERENCE_UNAUTHORIZED,
  REFERENCE_UNVERIFIED,
  referenceVerificationNote,
} from "./referenceVerification.js";

describe("reference-solution verification notes", () => {
  it("explains a real negative verdict instead of only flagging review", () => {
    expect(referenceVerificationNote({ verdict: REFERENCE_UNAUTHORIZED })).toEqual({
      kind: "negative",
      note: expect.stringContaining("无权访问"),
    });
    expect(referenceVerificationNote({ verdict: REFERENCE_STALE })).toEqual({
      kind: "negative",
      note: expect.stringContaining("已过期或缺失"),
    });
    expect(referenceVerificationNote({ verdict: REFERENCE_CONTRADICTED })).toEqual({
      kind: "negative",
      note: expect.stringContaining("相冲突"),
    });
  });

  it("says so when the sources were checked but support was never judged", () => {
    // The production state without a credential: layer 1 clean, layer 3 never ran.
    expect(
      referenceVerificationNote({ verdict: "verified", verified: true, definitive: false }),
    ).toEqual({
      kind: "unverified",
      note: expect.stringContaining("尚未做语义支持判断"),
    });
  });

  it("marks a reference that has no verifiable sources", () => {
    expect(
      referenceVerificationNote({
        verdict: REFERENCE_UNVERIFIED,
        verified: false,
        definitive: false,
      }),
    ).toEqual({ kind: "unverified", note: expect.stringContaining("没有可核验的引用来源") });
  });

  it("stays silent when a real verdict was reached and was not negative", () => {
    expect(
      referenceVerificationNote({ verdict: "verified", verified: true, definitive: true }),
    ).toBeNull();
  });

  it("renders nothing for a payload from before the gate existed", () => {
    expect(referenceVerificationNote(null)).toBeNull();
    expect(referenceVerificationNote(undefined)).toBeNull();
    expect(referenceVerificationNote({})).toBeNull();
    expect(referenceVerificationNote({ verified: false })).toBeNull();
  });
});
