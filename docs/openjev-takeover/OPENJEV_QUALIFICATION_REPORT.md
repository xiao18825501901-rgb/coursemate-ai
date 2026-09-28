# OpenJev scoped quality qualification

Date: 2026-09-29 (Asia/Shanghai)

## Decision

`QUALIFICATION_STATUS = UNSET`

The installed model is operational but is **not qualified** to decide any of the
four CourseJesus Question Engine hard gates. All four definitions stay off in
production. This is a fail-closed quality decision, not an installation failure.

## Evidence set

- 240 cases: 4 decision definitions x 3 language groups x 20 cases
- family-grouped calibration/test split; language variants of a family never
  cross the split boundary
- 240 deterministic-oracle labels, 0 human-reviewed gold labels
- explicit production-shaped state, option enums, and per-case instructions
- `truncation=error`, real tokenizer accounting, one decision per request
- no paid translation, DeepSeek judge, or invented human labels

Evidence artifact:

`artifacts/openjev-deployment/openjev-qualification-results-v2.json`

Artifact SHA-256:

`845dfc2f2eaee55412291e9e6a923967c84a3b82d1d4e269653a86d5b0cc3ef8`

Internal evidence digest:

`871e6d1e12e5bb1fac8bec80992ddbd6ef16929dcca1c3dd658caf6ca881ffbf`

The earlier binary-contract attempt is preserved separately as
`openjev-qualification-attempt1-binary-contract.json`; it is not treated as the
production contract.

## Test-split results

Every case/language test subgroup achieved exactly 0.50 accuracy. The 95% Wilson
lower bound for each subgroup was about 0.24. The fixed-choice behavior produced
systematic false rejects for ambiguity, MCQ distractor quality, and rule quality,
and systematic false accepts for answer agreement.

| Definition | Language | Accuracy | False accept | False reject | Mean latency |
|---|---:|---:|---:|---:|---:|
| ambiguity | en | 0.50 | 0 | 5 | 1,144 ms |
| ambiguity | zh | 0.50 | 0 | 5 | 1,193 ms |
| ambiguity | mixed | 0.50 | 0 | 5 | 1,453 ms |
| answer agreement | en | 0.50 | 5 | 0 | 805 ms |
| answer agreement | zh | 0.50 | 5 | 0 | 805 ms |
| answer agreement | mixed | 0.50 | 5 | 0 | 932 ms |
| MCQ distractor quality | en | 0.50 | 0 | 5 | 1,454 ms |
| MCQ distractor quality | zh | 0.50 | 0 | 5 | 1,527 ms |
| MCQ distractor quality | mixed | 0.50 | 0 | 5 | 1,883 ms |
| rule violation quality | en | 0.50 | 0 | 5 | 1,167 ms |
| rule violation quality | zh | 0.50 | 0 | 5 | 1,260 ms |
| rule violation quality | mixed | 0.50 | 0 | 5 | 1,554 ms |

## Interpretation

HTTP success, a loaded model, high probability, and low runtime error rate do not
prove semantic correctness. This model is documented as English-only and trained
on unrelated public domains; the measured CourseJesus contracts are out of that
evidence base. Even the English groups failed, so this is not only a Chinese
support problem.

No threshold can legitimately repair a fixed-label 50% classifier. Therefore:

- no global or per-language threshold is published;
- no receipt is prefilled as positive;
- no deterministic check is deleted;
- no Question Engine READY item is created from an unqualified decision;
- no paid generation is repeated merely to compensate for this result.

## What would be required for promotion

Promotion requires a changed model or training/calibration pipeline, a new versioned
input transform if applicable, separate case/language thresholds, and independent
reviewed evidence. It must be rerun against a held-out family split. The present
240-case run stays immutable as a rejected-candidate record.
