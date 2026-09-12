# CourseMate V3 — Architecture and State Machines

Version: Stage 7 current/target baseline, 2026-09-12.
This document distinguishes `CURRENT` source from `TARGET` architecture. Target objects are not claimed implemented until linked tests pass.

## 1. System ownership

```text
Browser / Clerk session
        |
        v
FastAPI RAG API  -- sole owner of learning facts and CourseMate file ACLs
  |-- V2 course, document, ingestion, RAG QA, citations and conversation history
  |-- V3 workspace and shared learning orchestrator
  |     |-- Teaching workflow
  |     |-- Problem workflow
  |     `-- Assessment workflow
  |-- SQLite RAG + learning schema
  `-- authorized local file/derived-artifact storage

Node Task Agent -- retains Todo/task-tool execution; does not own learning progress/grade

Qwen provider -- proposes plans/content/solutions/semantic grading;
                 never authenticates, authorizes, publishes or commits facts
Embedding provider/index -- separately configured and versioned
```

`SUPPLEMENTAL_ENGINEERING_DECISION`: keep V3 inside the existing FastAPI service rather than introduce a new microservice. It makes one transaction owner explicit and avoids falsely claiming cross-database atomicity with the Node Task Agent.

## 2. Bounded modules

| Module | Owns | Must not own |
|---|---|---|
| `documents` | Document identity, immutable versions, derived artifacts, ingestion lifecycle, ACL resolution | learning coverage or grade |
| `knowledge` | course-scoped node registry, aliases/evidence, tree versions, prerequisites, private overlayHealth | document bytes or user grade |
| `teaching` | immutable Spec/items, cached plans, journeys, units, delivery evidence, progress projection | Assessment results |
| `problems` | immutable problem/solution revisions, steps, knowledge links, exposure/attempt metadata | independent Assessment grade |
| `bridges` | pinned cross-workflow context and return anchor | mutable “latest solution” lookup |
| `assessments` | blueprint/session/question attempts, performance evidence, GradePolicy and snapshots | Learning Progress mutation |
| `publication` | consent/review snapshot/version visibility/withdrawal audit | implicit access to unrelated private records |
| `operations` | idempotency, base revision, pre-call budget reservations, model run/usage/error/events | product truth not validated by a domain module |

Shared server functions resolve principal → resource scope before any row, file, retrieval context or model call. The model never receives rows the principal could not access through the deterministic API.

## 3. Core target object graph

```text
Course
  +-- UserCourseWorkspace(owner, course, revision, mode, layout, cursor)
  |     +-- PrivateOverlay
  |     +-- PersonalizedPlanVersion --references--> KnowledgeNode
  |     +-- LearningJourney(node, pinned TeachingSpecVersion)
  |     |     +-- TeachingPlanVersion
  |     |     +-- TeachingUnit
  |     |           +-- TeachingDeliveryEvidence --> TeachingItem
  |     +-- ProblemAttempt --> ProblemRevision --> SolutionRevision --> SolutionStep
  |     |                                      `--> StepKnowledgeLink --> KnowledgeNode
  |     +-- LearningBridge(step + node + journey + context + return anchor)
  |     +-- AssessmentSession --> AssessmentBlueprintVersion
  |     |                       +-- QuestionAttempt --> QuestionRevision
  |     |                       `-- PerformanceEvidence
  |     `-- LearningOperation --> ModelRun / ordered AuditEvent
  +-- Document --> DocumentVersion --> DerivedArtifact / IngestionJob / MaterialEvidence
  +-- TreeVersion --> TreeMembership --> KnowledgeNode
  `-- TeachingSpecVersion --> TeachingItem

GradePolicyVersion --> GradeSnapshot (pinned to policy + assessment evidence)
PublicationRequest --> immutable ReviewSnapshot(version IDs + consent)
```

MaterialEvidence, TeachingDeliveryEvidence and PerformanceEvidence are separate types and tables. Their common word “evidence” does not make them interchangeable.

## 4. Current-to-target data map

| Current Schema/source | Current fact | Target action |
|---|---|---|
| `courses`, `documents`, `chunks`, `ingestion_jobs` | V2 mutable document row, original path, chunks | keep; add version/artifact/provenance tables in 013+ without re-ingesting by default |
| `learning_workspaces` (011) | owner×official-course state + private corpus | keep; add explicit lifecycle/revision fields only through later migration |
| `knowledge_nodes` (012) | minimal private/canonical ID fields | extend through registry/evidence/aliases, not rewrite 012 |
| `teaching_specs` (012) | JSON items + immutable update trigger | retain historical rows; add normalized item/version metadata if needed |
| `learning_journeys`, `teaching_units`, legacy `learning_coverage` | pinned Spec journey and saved unit state | migration 015 adds immutable Plan/Unit links and exact `teaching_delivery_evidence`; legacy rows remain visibly preserved |
| `learning_problems/solutions/steps/bridges` | retained stable IDs and JSON projections | migration 016 adds immutable ProblemRevision/Attempt/SolutionRevision, StepKnowledgeLink and LearningBridgeContext; legacy rows are explicitly preserved, while new rows require exact versions and owner/workspace validation |
| `learning_operations/events/model_runs` + `learning_model_run_evidence` + `learning_model_call_reservations` | idempotent bounded generation, content-free call diagnostics and owner/day + owner/course/day budget reservation | current path includes path IDs, base revision, safe invalid-output metadata, no hidden retry and migration 021 atomic call caps; production counter behavior remains unverified |
| Assessment questions/rubrics/blueprints/sessions/evidence and GradePolicy/Snapshot | migrations 017/018 + `learning/assessments.py` | implemented for atomic-node formal Assessment; author/review UI and integrated COMPOSITE exams remain target work |
| Course/official-knowledge/Overlay publication snapshots, resources, releases and audit | migrations 019/020 + three distinct services | immutable exact-version packages, request-bound Admin reads, owner-scoped Overlay candidates, withdrawal/cache generation and official release supersession are implemented; expiring per-reviewer assignment remains target work |

## 5. State machines

### Workspace mode

```text
AUTO <---- explicit user switch ----> TEACHING
  \                                /
   `------ explicit/semantic ------> PROBLEM
```

- User lock always wins until explicitly changed.
- `AUTO` emits a stored route reason/confidence; deterministic request shape may short-circuit obvious navigation.
- Route selection changes the active workflow, never creates a second learning state.

### Learning Progress (derived, not directly set)

| Derived state | Rule for the journey’s pinned Spec version |
|---|---|
| `NOT_STARTED` | no valid delivery evidence covers any REQUIRED item |
| `LEARNING` | at least one, but not every, REQUIRED item is validly covered |
| `LEARNED` | the set of valid coverage item IDs contains every REQUIRED item |

Assessment score, grade, user acknowledgement and model confidence do not enter this formula. A COMPOSITE node exposes a documented aggregation of descendant ATOMIC nodes and stores no contradictory independent mastery flag.

### Teaching journey

```text
PLANNED -> ACTIVE <-> PAUSED
               |        |
               +------> BLOCKED (missing/revoked evidence, invalidated Spec)
               |
               +------> COVERAGE_COMPLETE
```

- Each unit is bounded and generated only after explicit user action.
- `COVERAGE_COMPLETE` means Q8 delivery completion, not assessment mastery.
- A new Spec version does not mutate old journeys; a migration/replan decision creates a new pinned journey or explicit carry-forward ledger.

### Learning operation

```text
RESERVED(base_revision, request_hash)
  -> RUNNING_PROVIDER
      -> SUCCEEDED(result + validated domain commit)
      -> FAILED_KNOWN(error class, optional usage)
      -> UNKNOWN_OUTCOME(no automatic paid retry)
  -> CONFLICTED_STALE(result retained, not current state)
```

Reservation and finalization are short transactions; provider I/O occurs outside them. Finalization uses compare-and-set on workspace revision. The canonical request hash includes method kind, workspace, path IDs and normalized body.

### Model-call budget reservation

```text
PRECHECK(owner UTC day + owner/course UTC day)
  -> RESERVED before Provider I/O
      -> COMPLETED
      -> FAILED
      -> UNKNOWN (fail closed; no automatic retry)
      -> BLOCKED (local configuration/endpoint gate; excluded from paid-call quota)
  -> DAILY_MODEL_CALL_QUOTA (no Provider call)
```

Migration 021 serializes the count-and-insert step with `BEGIN IMMEDIATE`, so concurrent actions cannot both pass the same last slot. A reserved, failed or unknown attempt remains counted because the external charge status may be real or unknowable. Only an explicit local `MODEL_LIVE_BLOCKED`/`MODEL_ENDPOINT_INVALID` result becomes `BLOCKED`. V3 defaults to 60 calls per owner/day and 60 per owner/course/day in addition to the 30 learning-operations/day gate. The Task Agent has a separate transactional request budget: 10 chat requests/minute and 30/day, with at most four Provider rounds per accepted chat by default.

### Problem/attempt exposure

```text
ProblemRevision(VALIDATED or LEGACY_PRESERVED)
  -> ProblemAttempt(ACTIVE, assistance=ANSWER_EXPOSED)
  -> SolutionRevision(MODEL_PROPOSED / NOT_INDEPENDENTLY_VERIFIED by default)
  -> COMPLETED or CANCELLED
```

Problem Mode deliberately exposes a full solution and therefore creates `ANSWER_EXPOSED` evidence. Text, indexed and image inputs retain immutable source identity; source revocation may null only source FKs and never the retained hash/history. Formal Assessment uses a distinct session and server-held answers. A question or family previously exposed cannot be silently counted as independent evidence.

### LearningBridge

```text
OPEN -> LEARNING -> READY_TO_RETURN -> COMPLETED
  \---------------------> CANCELLED / SOURCE_UNAVAILABLE
```

The normalized bridge context pins problem revision, attempt, solution revision, step, validated knowledge link, node/Spec/item, journey, original conditions, selected question/reason and return anchor. Legacy contexts retain explicit `LEGACY_PRESERVED` status. Return is allowed to historical UI context when safe, but revoked source content is not rehydrated into new model context.

### Assessment blueprint and session

```text
Blueprint: BUILDING -> FROZEN -> RETIRED

Session: IN_PROGRESS -> SUBMITTED -> GRADED
              |              `-> remains SUBMITTED / NEEDS_REVIEW
              +-> ABANDONED
              `-> INVALIDATED
```

- Blueprint, five question revisions, unequal weights totaling 100, rubrics, sources and GradePolicy binding are frozen before the session starts.
- `ABANDONED` or unsubmitted never becomes zero/F.
- Help/reveal switches the entire session to assisted/practice and every resulting evidence row to non-independent; it cannot be converted back.
- Raw score and rubric evidence may reach `GRADED` while letter/GPA remains `UNCONFIGURED`.
- A strict model grader may propose criterion marks for open responses, but backend validation/arithmetic owns marks and snapshots. `NEEDS_REVIEW` emits no invented score.

### Performance-triggered replan

```text
PENDING -- explicit user Teaching action --> linked PlanVersion
   |                                      -> remediation TeachingUnit
   |                                      -> APPLIED after completed delivery
   `--------------------------------------> DISMISSED (future explicit policy)
```

Creating weak PerformanceEvidence does not call a model. Planner receives only authorized criterion/item summaries after the user explicitly continues Teaching; it does not receive hidden answers or full student responses. Remediation links do not mutate the Q8 coverage formula, so `LEARNED` remains a delivery-completion fact.

### Publication

```text
PRIVATE_DRAFT -> REVIEW_PENDING -> PUBLISHED_SNAPSHOT
       ^             |                    |
       |             +-> REJECTED         +-> WITHDRAWN
       `------- edit creates new draft/version --------'

OFFICIAL_DRAFT -> INDEPENDENT_REVIEW -> ACTIVE_RELEASE
                                           |
                       replacement --------+-> prior release WITHDRAWN

OWNER_PRIVATE_SELECTION -> OVERLAY_REVIEW -> ACTIVE_SELECTED_OVERLAY
```

Approval binds exact versions. Course, official knowledge and selected private Overlay use separate request types and routes. Generic Admin access does not provide ambient private-workspace browsing: it exposes only request-bound snapshot resources. Editing private source never changes an approved snapshot. Withdrawal increments the release cache generation and stops future access without deleting owner data or rewriting the review history; prior lawful downloads cannot be recalled. Approving a replacement official tree withdraws the prior request/release in the same transaction and retires its tree.

## 6. Transaction and concurrency rules

1. Every client mutation supplies an idempotency key and expected workspace/resource revision where applicable.
2. Unique constraints reject duplicate active workspaces, memberships, coverage evidence, and canonical operation IDs.
3. No provider/network call occurs inside a SQLite write transaction.
4. Final domain writes validate authorized IDs and base revision again.
5. Long-running cross-service actions, if introduced, use an outbox/compensation record. There is no claim that the RAG SQLite and Node Task SQLite share an atomic transaction.
6. File write lifecycle is stage-to-random-temp → validate/hash → atomic rename → DB commit; failures remove only the owned temp file. Deletion/revocation uses a tombstone/audit step before physical cleanup.
7. Provider errors and invalid output retain content-free model-run diagnostics; user content, API keys and private excerpts are never logged.

## 7. API contracts and compatibility

- Existing `/api/courses`, `/api/qa`, conversation, publication and Task Agent contracts remain stable.
- V3 routes live under `/api/learning`; the router and migrations are disabled by default.
- Resource IDs are opaque and resolved server-side; owner IDs in request bodies are ignored/rejected.
- Private-resource absence and denial return the same 404 envelope after authentication.
- Version/revision conflicts return a stable 409 code and current safe revision metadata, not private row details.
- Generated output passes `extra=forbid` bounded schemas and semantic ID checks before persistence.
- Streaming protocol support is an adapter capability, not inferred from an OpenAI-compatible base URL.

## 8. Architecture acceptance gate

This design may advance from Stage 0 only when:

- V3-off initializes/operates V2 without V3 Schema or queries;
- the requirements ledger maps Q1–Q10 and all Master Prompt domains;
- new engineering choices are labeled supplemental;
- production/model/account unknowns remain explicit;
- no real database or upload directory has been mutated by tests;
- the full current V2 regression is green or every failure has a diagnosed, in-scope correction before the first Stage 1 commit.
