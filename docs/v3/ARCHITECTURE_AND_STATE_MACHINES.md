# CourseMate V3 — Architecture and State Machines

Version: Stage 3 current/target baseline, 2026-09-12.
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
| `operations` | idempotency, base revision, model run/usage/error/events | product truth not validated by a domain module |

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
| `learning_problems/solutions/steps/bridges` | text problem and pinned step context | add immutable revision/source/image/knowledge-link/exposure fields |
| `learning_operations/events/model_runs` + `learning_model_run_evidence` | idempotent bounded generation and content-free call diagnostics | current path includes path IDs, base revision, safe invalid-output metadata and no hidden retry; daily aggregate caps remain target work |
| Assessment/tree/publication snapshot tables | absent | add in numbered migrations after focused tests |

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

### Problem/attempt exposure

```text
DRAFT -> SOLUTION_AVAILABLE -> ANSWER_EXPOSED
                       \----> PRACTICE_ATTEMPT(assisted)
```

Problem Mode deliberately exposes a full solution. Formal Assessment uses a distinct session and server-held answers. A question or family previously exposed cannot be silently counted as independent evidence.

### LearningBridge

```text
OPEN -> TEACHING_ACTIVE -> READY_TO_RETURN -> RETURNED
  \----------> SOURCE_REVOKED / STALE_VERSION
```

The bridge pins problem revision, solution revision, step, node, Spec/journey, original conditions, selected step content and return anchor. Return is still allowed to historical UI context when safe, but revoked source content is not rehydrated into new model context.

### Assessment session

```text
CREATED -> IN_PROGRESS -> SUBMITTED -> GRADED
                   \-> ABANDONED
                   \-> INVALIDATED
```

- Blueprint, five question revisions, unequal weights totaling 100, rubrics, sources and GradePolicy are frozen at `CREATED`.
- `ABANDONED` or unsubmitted never becomes zero/F.
- Help/reveal switches the affected attempt to assisted/practice; it cannot be converted back to independent evidence.
- Raw score and rubric evidence may reach `GRADED` while letter/GPA remains `UNCONFIGURED`.

### Publication

```text
PRIVATE_DRAFT -> REVIEW_PENDING -> PUBLISHED_SNAPSHOT
       ^             |                    |
       |             +-> REJECTED         +-> WITHDRAWN
       `------- edit creates new draft/version --------'
```

Approval binds exact versions. Editing private source never changes an approved snapshot. Withdrawal changes public visibility but does not delete owner data or rewrite history.

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
