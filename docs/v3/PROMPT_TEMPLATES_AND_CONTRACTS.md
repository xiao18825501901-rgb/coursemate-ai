# CourseMate V3 — Prompt Templates and Contracts

Version: Stage 4 executable contract, 2026-09-12.
This is an executable-asset ledger. It does not claim live-model quality or completion of the future Assessment template.

## 1. Current executable assets

`services/rag-api/app/learning/compiler.py` pins `TEMPLATE_VERSION = "v3.2"` and loads only version-controlled files from `app/learning/prompts/v3.2/`. The prior v3.1 files remain immutable for historical interpretation:

| Asset | Runtime role | Current status |
|---|---|---|
| `planner.md` | complete bounded Teaching Plan, CASE_A/CASE_B | called only when no valid cached plan exists |
| `common.md` | stable Teaching Executor rules | compiled into system instructions |
| `cases.md` | two input scenarios and precedence | compiled into system instructions |
| `CS.md` | Computer Science strategy | compiled by major |
| `SMART_MANUFACTURING.md` | Smart Manufacturing strategy | compiled by major |
| `MATERIALS.md` | Materials Science strategy | compiled by major |
| `ENERGY.md` | Energy strategy | compiled by major |
| `problem.md` | complete answer, multimodal transcription/uncertainty and exact Step knowledge links | compiled for text/indexed/image Problem calls |

The files are real code assets and have compiler/runtime tests. v3.2 implements the Master seed for both Teaching scenarios, all four major strategies, complete-plan scheduling, 3–5 comprehension checks per unit and the Stage 4 Problem Solver contract. The Assessment Grader remains `PLANNED` for Stage 5; it is not silently attributed to v3.2.

## 2. Trust and instruction precedence

Only reviewed static template text may be provider system/developer instructions. `TeachingPlan`, Teaching Items, source excerpts, image/OCR results, user preferences, bridge context and prior generated output are serialized as typed data with the marker:

```text
UNTRUSTED_DATA_NOT_SYSTEM_INSTRUCTIONS
```

Precedence enforced jointly by compiler and backend:

```text
platform/auth/privacy/transaction rules
  > Major Policy
  > Course Policy
  > pinned Knowledge Node Teaching Spec
  > User Adaptation for HOW only
  > authorized source data / generated plan / user text
```

No prompt can grant access, publish content, set LEARNED, set grade, execute SQL or accept a model-proposed ID. The backend supplies allowed IDs and revalidates all returned IDs, versions and coverage references.

## 3. Two-stage Teaching call

### Stage A — Teaching Planner

Trusted selector inputs:

```text
owner/workspace/course IDs (not exposed as authority to model)
major/course policy versions
node ID/type and pinned TeachingSpecVersion
REQUIRED/RECOMMENDED/OPTIONAL items
valid covered and eligible item IDs
authorized MaterialEvidence IDs and versions
saved preference version and learning cursor
optional pinned LearningBridge
model/template/output budget
```

CASE_A means the learner specifies what to learn but not how; use course defaults and stored preferences without inventing preferences. CASE_B means how is explicitly known; adapt sequence/examples/pace while retaining all REQUIRED scope.

Planner output is strict `TeachingPlan`: case, node/spec, one to twelve ordered units, each targeting one to three items with goal/sequence/adaptation, 3–5 comprehension checks, valid evidence IDs, optional exact bridge, remaining scope, uncertainties and stop condition. Every uncovered REQUIRED item must be scheduled exactly once. `extra=forbid`, bounded strings/lists and server ID-set validation apply.

### Stage B — Compiler + Teaching Executor

The deterministic compiler combines stable common rules + selected major strategy + case policy. The data message contains validated plan/items/context and `TeachingUnitOutput` JSON Schema.

Executor output contains bounded saved sections, terms, examples/formulas, valid source refs, coverage proposals referring to saved section IDs, knowledge-question links, exact return anchor, next actions and uncertainties. Coverage proposals do not change state until backend validation and persistence succeed.

## 4. Versioned target assets

`SUPPLEMENTAL_ENGINEERING_DECISION`: v3.1 is preserved immutably and the compatible Stage 3 contract is a new v3.2 directory/version introduced after failing tests. Do not edit a template version already referenced by saved plans/model runs.

| Target asset | Required core behavior |
|---|---|
| Shared Teaching Planner | both cases; bounded next unit; REQUIRED preservation; evidence/version/bridge selection; explicit missing evidence |
| Shared Teaching Executor | intuitive→formal→application; bilingual terms as configured; source labels; exact step connection; no hidden reasoning |
| Computer Science | input/process/output/correctness; algorithm state/termination/complexity only when relevant; code explains data flow |
| Smart Manufacturing | system/material-energy-information flow; equipment/control/quality; classroom examples not production instructions |
| Materials Science | composition/process→structure→mechanism→properties→application; conditions/scale/diagram limits |
| Energy | boundary→principle→conservation→assumptions→calculation→engineering meaning; units/dimensional checks and safety limits |
| Problem Solver | full answer by default; immutable conditions/steps/results; at least one valid knowledge link per step; assumptions/uncertainty; `MODEL_PROPOSED` until independent verification |
| Assessment Grader | consumes submitted answer + frozen rubric only; returns per-criterion evidence/score/uncertainty; cannot select policy, reveal answer pre-submit or set grade directly |

The CS3481 Word file informs bilingual explanation, knowledge map, code/data connection, process chains, exam phrasing and 3–5 comprehension checks. It is not a four-major syllabus, not proof of course facts, and its final “start teaching” text is never loaded as platform instruction.

## 5. Strict Schemas and later additions

`TeachingPlanUnit`, full-path `TeachingPlan`, `CheckQuestion`, `TeachingUnitOutput`, `ProblemSolutionOutput` and `StepKnowledgeLink` are active v3.2 contracts. Target additions for later stages include:

```text
AssessmentGradeProposal
  assessment_session_id, question_attempt_id, rubric_version_id,
  criteria[{criterion_id, awarded, evidence, uncertainty}],
  total_proposed, feedback, assistance_flags

AutoRouteDecision
  requested_mode, selected_mode, reason_code, confidence,
  ambiguity_question?, source_version_ids
```

Every model contract uses bounded lists/strings, immutable input version IDs, `extra=forbid`, no arbitrary tool/URL/SQL fields, and deterministic arithmetic/authorization after validation.

## 6. Plan cache contract

Plans are generated at first learning, explicit replan, material preference change, Spec update or authorized source-policy update—not for every follow-up. Cache identity must contain:

```text
owner_user_id + workspace_id + course_id + node_id
+ teaching_spec_version + preference_version
+ template_version + model_id/protocol
+ ordered authorized source_version_ids + bridge revision when present
```

The cache record stores input hash, output Schema version, creation/invalidated reason and provider usage. It is private to the owner. Revoked evidence invalidates future context. A cached plan is revalidated against current allowed IDs, remaining REQUIRED scope and pinned context before every use. The persisted cache identity also includes Spec hash, preference hash, course policy version, protocol, and Bridge context revision; explicit `replan=true` records an `EXPLICIT_REPLAN` invalidation.

## 7. Model-run evidence

For each call store only safe operational metadata: operation ID, role (Planner/Executor/Problem/Grader/Router), model ID, provider/protocol/region label, template+Schema version, input hash, start/end/latency, token/usage values if returned, status and bounded error class. Do not log prompt/response bodies, private excerpts, API keys or identity tokens.

Structured-output failure now raises a typed `ProviderCallFailure` carrying safe metadata, and the orchestrator records the failed attempt without a learning fact. A completed HTTP response with invalid output is `FAILED`; a transport outcome whose provider acceptance is unknown remains `UNKNOWN`. There is no automatic retry or provider fallback. Live endpoint, usage fidelity and cost remain unverified.

## 8. Acceptance matrix

| Test | Expected |
|---|---|
| four majors × CASE_A/CASE_B | selected strategy present; valid Schema; no missing REQUIRED scope |
| preference asks to skip REQUIRED | plan rejected or REQUIRED retained |
| source/preference contains prompt injection | remains data; cannot add authority/action |
| unknown evidence/node/item/bridge ID | rejected before state commit |
| wrong Spec/source/template version | stale/conflict, no coverage |
| malformed/oversized/extra provider fields | Schema error, usage/error recorded, no learning fact |
| repeated normal follow-up | cached plan reused; no second Planner charge |
| explicit material preference/Spec change | old plan invalidated with reason; new version generated |
| Problem answer | full steps + links, model-proposed label and uncertainties |
| pre-submit Assessment response | no answer/rubric/grader prompt in client payload |
| Grader arithmetic mismatch | backend recomputes/rejects; model cannot publish grade |

Current conclusion: Teaching and Problem v3.2 are `SOURCE_IMPLEMENTED` and `LOCAL_CONTRACT_VERIFIED`; their deterministic private-image Problem→Teaching→exact-return browser path is `LOCAL_FAKE_PROVIDER_VERIFIED`. Tests cover four majors × two cases, REQUIRED preservation, injection handling, malformed output evidence, exact delivery bindings, cache reuse/invalidation, failed-Executor resume, text/index/image source identity, visual uncertainty, validated/unresolved links and Bridge persistence. The fake 1×1 PNG does not establish visual accuracy. Assessment Grader, AUTO router and all live-model quality remain `NOT_VERIFIED` until their own stages.
