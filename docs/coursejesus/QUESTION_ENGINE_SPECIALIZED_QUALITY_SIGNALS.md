# Question Engine specialized quality signals

Updated: 2026-09-25

Application revision: `f00f3e3eb012d2868930a3fb924b8ef0926fb940`

## Evidence boundary

This is local deterministic-provider and fake-TypeSafe-Jev evidence. It does not establish live
DeepSeek quality, calibrated Jev accuracy, human approval, production deployment, or institutional
correctness. No scalar quality score is created.

## Implemented signals

The two existing base signals remain separate:

- `question.ambiguity.v1`; and
- `question.answer_agreement.v1`.

Two Choice-only module signals are now registered:

- `question.mcq_distractor_quality.v1` returns `ACCEPTABLE`, `WEAK`, `AMBIGUOUS`, or `UNCERTAIN`.
  It sees only the frozen question/options, private wrong-option mappings, server-owned
  misconception targets, and authorized evidence rules.
- `question.rule_violation_quality.v1` returns `SUPPORTED`, `UNSUPPORTED`, `AMBIGUOUS`, or
  `UNCERTAIN`. It sees only the question, private evidence-bound rule analysis, and authorized
  evidence rules.

They do not author content, alter options, invent rules, assign marks, change permissions, set
`LEARNED`, or publish questions. Exact option coverage, misconception membership, source scope,
rule quotation, revision identity and tenant scope remain deterministic hard gates.

An applicable question reaches `VALIDATED` only when all six hard gates pass, both base signals
have durable on-mode `CLEAR`/`AGREE` receipts, and its module signal has a durable on-mode positive
receipt (`ACCEPTABLE` or `SUPPORTED`). Missing, shadow, unreceipted, weak, unsupported, ambiguous,
uncertain, stale or mismatched signals stay `NEEDS_REVIEW`. Ordinary non-specialized questions
continue to require exactly the two base receipts.

Persistence recomputes every bounded decision input hash. Saved five-slot Assessment revisions now
require either two or three exact receipts according to their frozen blueprint; a missing MCQ
specialized receipt fails closed on resume.

## Verification

| Layer | Result | Evidence |
|---|---|---|
| Related backend regression | **99 passed**, 1 dependency warning | catalog, callsites, author, validator, persistence, runtime, five-slot, preparation and UI-extension tests |
| Failure boundaries | PASS | missing/weak MCQ signal and missing/unsupported rule signal stay under review; shadow rule signal cannot publish; missing MCQ receipt invalidates saved-slot resume |
| Static checks | PASS | focused Ruff, byte compilation and `git diff --check` |
| Real Chrome targeted Assessment journey | **1 passed**, no retry | `work/codex-audit/browser-1790290220100-42460/playwright-report.json` |
| Screenshot | visually inspected | `work/codex-audit/browser-1790290220100-42460/browser-results/codex-audit-empty-assessme-8bafe-ntary-Question-Engine-slots/five-question-slots.png` |
| Isolated browser database | PASS | five reports stored; first MCQ report has the two base dimensions plus `MCQ_DISTRACTOR_QUALITY`; its private mapping remains in `answer_json` |

## Remaining acceptance

- Run the wider same-SHA P4 regression and exact-candidate migration/restore rehearsal.
- Any representative live DeepSeek generation, live Jev calibration, human quality review, or
  production verification requires its own current authorization and evidence.
