# CASE_ADOPTION_MATRIX

Disposition of the twelve CourseMate/Jev application cases for this round.

**Source note (honest):** the referenced Word file
(`85462d421aa7c5974f16e77c6757a63d_1348753965729759177_m(3).doc`) is **not present** anywhere in this
workspace or the download folders I can read, and the 60-case collection it cites was never provided.
The case list and the dispositions below therefore come from the task specification itself, and the
only cases implemented are those the specification scoped for this round. No claim is made about the
content of the unread collection, and none of its URLs is treated as a real API path.

| # | Case | Disposition | Why |
|---|---|---|---|
| 1 | Notra brand mention / GEO | **NOT ADOPTED** | Marketing visibility scoring is outside the teaching-quality line and the owner excluded GEO this round |
| 2 | Entity alignment | **ADOPTED (P1)** — module B, `CourseEntityResolution` | Directly useful: bilingual aliases and duplicate evidence hurt retrieval |
| 3 | RAG passage classification / conflict | **ADOPTED (P0)** — module C, `EvidenceConsistency` | Conflicts and condition differences are a real correctness risk in course material |
| 4 | Citation checking | **ADOPTED (P0)** — module D, `ClaimCitationAudit` | The pause report showed citation support had **no** call site; this closes it |
| 5 | Browser Use / autonomous browsing | **DEV-ONLY PROBE, NOT ADOPTED** | Never in the student request path; deterministic Playwright journeys remain the acceptance mechanism |
| 6 | Skill suggestion | **ADOPTED (P1)** — module E, `TeachingCapabilityRouter` | Routes to CourseMate's own existing teaching capabilities, not to external plugins |
| 7 | Tool risk middleware | **ADOPTED (P1)** — module F, `ToolIntentCheck` | Only for model-proposed side-effecting calls with genuine intent ambiguity; permissions stay in code |
| 8 | Ticket triage | **ADOPTED (P2, last)** — lightweight user-initiated feedback classification | Small, opt-in, no CRM; user must submit explicitly |
| 9 | Website expression scoring | **NOT ADOPTED** | Website marketing scoring must not be used to judge teaching |
| 10 | Paper Trellis | **MERGED into #4** | Same job as citation checking; a second citation service would be duplicate infrastructure |
| 11 | Extraction cascade | **ADOPTED (P0, highest priority)** — module A, `ExtractionVerification` | Field-level extraction from questions/tables/figures/answers is where silent errors enter grading |
| 12 | Auto features / CatBoost | **NOT ADOPTED** | No student-ability, exam-score or churn prediction models this round; existing explainable run metrics continue |

## Rules applied to every adopted case

* **Reuse before adding.** Cases 3, 4, 6 and 7 were checked against the existing Jev definitions
  (`retrieval.support.v1`, `source.supports_claim.v1`, `source.select_span.v1`, `intent.next_action.v1`,
  `pedagogy.next_method.v1`, `corpus.quality.v1`, `coverage.item_support.v1`,
  `assessment.criterion_review.v1`) before any new definition was proposed. A new definition is
  registered only where no existing one is semantically the same, and never as a parallel service.
* **No second infrastructure.** No second gateway, no second citation service, no knowledge-tree
  authority, no new store for grades/users. New state extends the existing receipt table or uses one
  minimal additive migration.
* **Deterministic first.** For every adopted case the code decides what it can (schema, required
  fields, numeric/unit checks, question ids, permission and revision checks, hash equality); Jev only
  judges the semantic residue.
* **Jev can never decide authority.** Permissions, totals, LEARNED, answer reveal, file deletion,
  publication and tool execution stay with code + evidence + current revision.
* **Cost shape.** Ingestion-time work runs once per material version and is cached; chat-time work
  runs only where it changes behaviour (retrieval, context, intent, citation, coverage, assessment);
  explicit commands and arithmetic cost zero Jev calls.

## Not implemented, and why it will not be claimed otherwise

Cases 1, 5, 9 and 12 are excluded by the specification. They are not "planned", not partially wired,
and nothing in the product may imply they exist. If a later round wants them, they need their own
scope, data and evaluation — and case 12 in particular would need a fairness and consent review
before any student prediction model is considered.
