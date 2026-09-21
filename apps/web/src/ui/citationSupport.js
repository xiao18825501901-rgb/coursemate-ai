/**
 * Claim↔citation audit verdicts (module D) as shown next to a citation chip.
 *
 * The backend annotates each citation card with the audit verdict and the layer
 * that produced it. Only a *real* negative verdict is surfaced: a verified card and
 * a card that simply was not semantically checked keep their normal appearance, so
 * an installation without the semantic layer renders citations exactly as before.
 */
export const CITATION_UNVERIFIED = "NOT_ADDRESSED_IN_AVAILABLE_EVIDENCE";
export const CITATION_CONTRADICTED = "CONTRADICTED";
export const CITATION_REJECTED = "REJECTED";

/**
 * @param {{support?: string, audit_reject_reason?: string|null}|null|undefined} citation
 * @returns {{flag: "contradicted"|"unverified", note: string}|null}
 */
export function citationVerdict(citation) {
  const support = citation && citation.support;
  if (support === CITATION_CONTRADICTED) {
    return {
      flag: "contradicted",
      note: "这段引用与原文的数值或结论相冲突，请点开核对原文。",
    };
  }
  if (
    support === CITATION_UNVERIFIED ||
    (support === CITATION_REJECTED && citation.audit_reject_reason)
  ) {
    return {
      flag: "unverified",
      note: "这段引用没能在原文中核实（也可能只是当前片段没有提到），请点开原文确认。",
    };
  }
  return null;
}
