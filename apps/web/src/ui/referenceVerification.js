/**
 * Reference-solution evidence verification (module D's high-impact gate) as it is shown
 * next to a graded question's reference solution.
 *
 * The backend reports two separate facts, and this module keeps them separate in the UI:
 *
 *  * `verified` — layer 1 found nothing wrong (the cited chunks exist, are authorized for
 *    this learner and are the current version);
 *  * `definitive` — a *real* semantic verdict was reached (`SUPPORTED`/`CONTRADICTED`).
 *
 * Without a credential layer 3 never runs, so every reference solution is
 * `verified: true, definitive: false`. Showing nothing in that state is exactly what used
 * to let an unchecked reference look checked, which is why the "sources and permission
 * were confirmed, semantic support was not" note exists.
 *
 * A payload with no `reference_verification` at all (an older server) renders nothing, so
 * this stays invisible until the backend actually reports something.
 */

export const REFERENCE_STALE = "reference_evidence_stale";
export const REFERENCE_UNAUTHORIZED = "reference_evidence_unauthorized";
export const REFERENCE_CONTRADICTED = "reference_contradicted";
export const REFERENCE_UNVERIFIED = "reference_evidence_unverified";

/**
 * @param {{verdict?: string, verified?: boolean, definitive?: boolean}|null|undefined} verification
 * @returns {{kind: "negative"|"unverified", note: string}|null}
 */
export function referenceVerificationNote(verification) {
  if (!verification || typeof verification !== "object") {
    return null;
  }
  const verdict = verification.verdict;
  if (verdict === REFERENCE_UNAUTHORIZED) {
    return {
      kind: "negative",
      note: "这份参考解引用的资料当前无权访问，已标记待复核。",
    };
  }
  if (verdict === REFERENCE_STALE) {
    return {
      kind: "negative",
      note: "这份参考解引用的资料版本已过期或缺失，已标记待复核。",
    };
  }
  if (verdict === REFERENCE_CONTRADICTED) {
    return {
      kind: "negative",
      note: "核验认为引用的资料与参考解的结论相冲突，已标记待复核。",
    };
  }
  if (verdict === REFERENCE_UNVERIFIED) {
    return {
      kind: "unverified",
      note: "这份参考解没有可核验的引用来源。",
    };
  }
  if (verification.definitive === true) {
    // A real semantic verdict was reached and nothing was negative: nothing to warn about.
    return null;
  }
  if (verification.verified === true) {
    return {
      kind: "unverified",
      note: "引用的来源与权限已核实；尚未做语义支持判断。",
    };
  }
  return null;
}
