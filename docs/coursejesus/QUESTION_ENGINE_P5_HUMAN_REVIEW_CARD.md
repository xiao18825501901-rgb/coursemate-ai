# CourseJesus Question Engine P5 human review card

Card status: **PENDING OWNER DECISION — REVIEW MATERIAL AVAILABLE**
Card version: `p5-20260925-live-v2`
Application candidate: `978e3f714ee9a1a39a34e1969c82615346a60f82`
Test-harness checkpoint: `c36782e69a51becd1fd690f782b0ae458115c987`

The bounded C1-C5 live workflow has produced exact reviewable content. Automated model, Jev,
contract, persistence and UI-projection checks have passed, but they do not decide teaching quality.
Only the project Owner may enter `PASS`, `REVISE` or `REJECT`. Production release remains blocked
until that decision is recorded against this exact bundle.

## Controlled review bundle

Private model content is intentionally excluded from Git. Review it locally at:

`D:\CourseMate_COMPLETE_ARCHIVE_20260918\01_SOURCE_REPOSITORY\work\p5-owner-review-20260925T103415Z\OWNER_REVIEW_CARD_PRIVATE.md`

Evidence identities:

| Artifact | SHA-256 |
|---|---|
| Private human-review card | `0335ba2079a5f046c584947c4c6d38091aafed04ec7a43723746aa5ad0dcb862` |
| Review manifest | `fc91704466ef1b1082d7833dc9965e9a587d462da89cdd88118b18a4993d7ad4` |
| C1/C2 public summary | `279e7b63bec5d00dd72749995ccfa1811580ef0eab39d06254647bd923decbf1` |
| C3-C5 private review | `1f7d1e5ebad4e72d3bb87e073233adf62430f234114d67fd345b8ffe0fa4a7c4` |
| C3-C5 private transport ledger | `419013f4e3cf29d6384e6eac64c1806d38ffcd055cb337c0eae4b58b3404566a` |

The manifest contains the exact source paths and hashes. The private card contains the exact
questions, reference solutions, blind-solve/grader evidence, hint, feedback, re-practice material,
MCQ distractor mapping and rule analysis. Do not publish it or add it to Git.

## Exact cases

| Case | Exact revision(s) | Automated evidence | Human decision |
|---|---|---|---|
| C1/C2 practice | `qe_2b66a37d422649c3b0157c202bab0c49`, re-practice `qe_1fdf1412e5c34304bbf60678a771a36a` | READY, hint non-leakage, feedback, reveal/detail, different family, Jev ambiguity/agreement | **PENDING** |
| C3 MCQ | `qe_47e5e607352741fd9864f06867d52447` | private option mapping persisted; `question.mcq_distractor_quality.v1=on`, outcome `ok` | **PENDING** |
| C4 rule | `qe_2fd0b9a365e8441c83859d544d335b8d` | private rule analysis persisted; `question.rule_violation_quality.v1=on`, outcome `ok` | **PENDING** |
| C5 slot 1, 10 marks | `qe_47e5e607352741fd9864f06867d52447` | frozen assessment; reference verification complete | **PENDING** |
| C5 slot 2, 15 marks | `qe_e9a097b438224c9493e967817cee3b33` | frozen assessment; reference verification complete | **PENDING** |
| C5 slot 3, 20 marks | `qe_aacc5203bc274e05892ced0a57d33328` | frozen assessment; reference verification complete | **PENDING** |
| C5 slot 4, 25 marks | `qe_35925afc03994be2916edead4de31ffc` | frozen assessment; reference verification complete | **PENDING** |
| C5 slot 5, 30 marks | `qe_3197bbfaa1744489b18ad69574fa52b9` | frozen assessment; reference verification complete | **PENDING** |

## Live-call boundary

- C1/C2: 8 completed DeepSeek calls, 4 completed Jev calls, estimated USD `0.0095247`.
- C3-C5: 13 completed DeepSeek calls, 14 completed Jev calls, estimated USD `0.0255264`.
- Combined new-workflow estimate: USD `0.0350511`, using the Owner-provided token prices.
- SDK/transport automatic retry count: `0`.
- Every DeepSeek/Jev network send has a preceding `SEND_INTENT`; completed responses and usage were
  persisted before business parsing.
- Attempt 2 remains immutable `UPSTREAM_UNKNOWN`; possible unmetered DeepSeek calls: `1`; charge:
  `UNKNOWN`. Its reconciliation SHA-256 is
  `8e0b9addcc61a837906866e5b67bdd581567cd37fafd4c2a5d76ad398766c70b`.

## Questions the Owner must answer

For each exact revision: Is it aligned to the named target, sufficiently conditioned, solvable,
correct, unambiguous and appropriately difficult? Are wrong MCQ options genuinely wrong but
plausible? Does the rule correction preserve the same problem and source rule? Are hint and
feedback helpful without revealing the answer? Do the five slots complement rather than paraphrase
one another?

Human reviewer: `UNASSIGNED`
Review timestamp: `NOT_REVIEWED`
Review-manifest SHA-256: `fc91704466ef1b1082d7833dc9965e9a587d462da89cdd88118b18a4993d7ad4`
Decision: **PENDING**
Reason / requested revisions: `NOT_PROVIDED`
