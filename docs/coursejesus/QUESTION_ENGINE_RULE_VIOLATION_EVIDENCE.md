# Question Engine rule-violation evidence

Updated: 2026-09-25

## Status and evidence boundary

This document records a local P3 contract slice. It does not claim live-model, human-quality,
production, or institutional acceptance. The cited executions use the labelled deterministic
provider, synthetic course evidence and isolated databases.

## Implemented contract

`question-rule-violation-policy-v1` is an explicit server-owned generation policy. It may only be
used with an `EXPLANATION` blueprint. Question Author prompt/schema v3 requires one learner-visible
proposed statement plus a private `rule_violation_analysis` containing:

- the same proposed statement;
- one exact evidence fragment id;
- a non-empty rule quote copied as a contiguous substring of that fragment;
- the corrected statement; and
- an explanation.

The author boundary refuses missing analysis, fabricated quotes, out-of-scope references and
questions that omit the proposed statement. The deterministic `QUESTION_SHAPE` and `SOURCE_SCOPE`
gates independently recheck those invariants. The private analysis participates in the immutable
question revision and is persisted in private `answer_json`; it is not added to the public authored
question.

Historical v1/v2 provider receipts remain parseable for immutable historical records. Every new
author request must use matching `question-author.v3` and `question-author-output.v3` receipts.

The productive practice prototype `rule_violation_analysis` selects the new policy through the
existing non-authoritative prototype choice. The source rule itself still comes only from the frozen
evidence pack; the choice service cannot create or authorize a rule.

## Verification

| Layer | Result | Evidence |
|---|---|---|
| Author contract | PASS | exact evidence-bound analysis accepted; missing, fabricated and question-absent statements refused |
| Validator hard gates | PASS | exact binding passes; missing/fabricated binding fails `QUESTION_SHAPE` |
| Persistence/runtime | PASS | private analysis survives storage and the productive rule prototype reaches READY with synthetic evidence |
| Related backend regression | **61 passed**, 1 dependency warning | author, validator, persistence, runtime, five-slot and preparation-contract tests |
| Static checks | PASS | focused Ruff, byte compilation and `git diff --check` |

## Remaining P3 work

- The separate non-authoritative rule-semantic signal is now recorded in
  `QUESTION_ENGINE_SPECIALIZED_QUALITY_SIGNALS.md`. Deterministic source/shape gates remain
  authoritative.
- Obtain separately authorized representative live DeepSeek generations and human review before
  making any claim about question quality.
