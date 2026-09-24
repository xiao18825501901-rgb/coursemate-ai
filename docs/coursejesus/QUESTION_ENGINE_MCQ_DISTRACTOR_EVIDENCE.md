# Question Engine MCQ distractor evidence

Updated: 2026-09-25

## Status and evidence boundary

This document records the first local P3 question-quality slice. It does not claim live-model,
human-quality, calibration, production, or institutional acceptance. All executions cited below use
the labelled deterministic provider, synthetic course evidence, synthetic identities, isolated
databases, and loopback-only services.

## Implemented contract

The server-owned `QuestionBlueprint.misconception_targets` is the only permitted misconception
vocabulary for an authored single-choice question. Question Author prompt/schema v2 requires one
private `distractor_rationales` row for every incorrect option. Each row binds:

- the exact zero-based wrong-option index;
- one exact misconception string already present in the blueprint;
- an evidence-grounded explanation; and
- one or more source ids from the immutable evidence pack.

The author boundary refuses missing, partial, duplicate-index, correct-option, invented-target, or
out-of-scope-source mappings. The deterministic `QUESTION_SHAPE` and `SOURCE_SCOPE` gates recheck
the same invariants independently before a candidate can become `VALIDATED`. The mapping is included
in the immutable revision identity and persisted in the private `answer_json`; it is not returned in
the pre-submit Assessment session or the public authored-question payload.

Historical v1 provider receipts remain parseable for immutable historical candidates. Every new
author request must use matching `question-author.v2` and `question-author-output.v2` receipts, so a
stale or falsely labelled v1 response cannot be accepted as a new v2 result.

## Verification

| Layer | Result | Evidence |
|---|---|---|
| Author contract | PASS | missing, partial and invented mappings refused; exact mappings remain private |
| Validator hard gates | PASS | valid mapping passes; absent mapping fails `QUESTION_SHAPE` |
| Persistence/integration | PASS | the first five-slot MCQ stores its mapping in private `answer_json`; the learner session omits it |
| Related backend regression | **55 passed**, 1 dependency warning | author, validator, persistence, runtime, five-slot and preparation-contract tests |
| Real Chrome targeted journey | **1 passed**, no retry | `work/codex-audit/browser-1790288661917-40144/playwright-report.json` |
| Browser screenshot | visually inspected | `work/codex-audit/browser-1790288661917-40144/browser-results/codex-audit-empty-assessme-8bafe-ntary-Question-Engine-slots/five-question-slots.png` |
| Static checks | PASS | focused Ruff, byte compilation and `git diff --check` |

The isolated browser database also contains the expected private mapping for the generated
`MCQ_SINGLE` revision. This is synthetic persistence evidence, not a live DeepSeek quality result.

## Remaining P3 work

- Add an explicitly server-authorized rule-violation question intent that can only use real course
  rules from the evidence pack; do not infer a rule taxonomy that the source does not contain.
- Finish the remaining module-specific semantic quality gates without turning Jev into an
  authoritative publisher, grader, permission check, or aggregate quality score.
- Obtain separately authorized representative live DeepSeek generations and human review before
  making any claim about distractor quality.
