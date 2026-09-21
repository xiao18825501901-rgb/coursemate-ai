import { describe, expect, it } from "vitest";

import {
  CITATION_CONTRADICTED,
  CITATION_REJECTED,
  CITATION_UNVERIFIED,
  citationVerdict,
} from "./citationSupport.js";

describe("citation audit verdicts", () => {
  it("marks a contradiction that the backend proved against the source", () => {
    expect(citationVerdict({ support: CITATION_CONTRADICTED })).toEqual({
      flag: "contradicted",
      note: expect.stringContaining("冲突"),
    });
  });

  it("marks a citation the evidence does not address", () => {
    expect(citationVerdict({ support: CITATION_UNVERIFIED })).toEqual({
      flag: "unverified",
      note: expect.stringContaining("没能在原文中核实"),
    });
  });

  it("marks only a rejected citation that carries a reject reason", () => {
    expect(
      citationVerdict({ support: CITATION_REJECTED, audit_reject_reason: "unauthorized" }),
    ).toMatchObject({ flag: "unverified" });
    expect(citationVerdict({ support: CITATION_REJECTED })).toBeNull();
  });

  it("leaves verified, partial, unchecked and legacy cards unmarked", () => {
    // SUPPORTED / PARTIALLY_SUPPORTED / INSUFFICIENT_CONTEXT / no audit at all:
    // the chip must look exactly as it did before the audit existed.
    for (const support of [
      "SUPPORTED",
      "PARTIALLY_SUPPORTED",
      "INSUFFICIENT_CONTEXT",
      undefined,
      null,
    ]) {
      expect(citationVerdict({ support })).toBeNull();
    }
    expect(citationVerdict({})).toBeNull();
    expect(citationVerdict(null)).toBeNull();
    expect(citationVerdict(undefined)).toBeNull();
  });
});
