# CourseMate V3 — Permissions and Data Provenance

Version: Stage 8 cumulative implemented security contract, 2026-09-12.
Authentication is necessary but never sufficient: every API, file read, retrieval query, model context, cache and derivative must authorize the specific resource.

## 1. Principals and scopes

| Principal | Meaning | Default authority |
|---|---|---|
| anonymous | no verified Clerk/test identity | health/public shell only; no learning data |
| authenticated user | server-verified stable user ID | published official course data + their own courses/workspaces/records |
| course owner | authenticated owner of a private user course | mutate that course within lifecycle/policy constraints |
| workspace owner | authenticated owner of User×official-course workspace | all records in that workspace, unless source revoked/missing |
| generic admin | ID in server-side admin allowlist | official drafts/releases and request-bound course/Overlay review snapshots; **not** implicit access to private learning records |
| scoped reviewer | target role not separately implemented | future per-request/expiring assignment; current reviewer is an allowlisted Admin constrained by request-bound routes |
| background worker | service identity with one job/resource capability | only the exact source/version/output path in the job |

The client never chooses its owner ID, role or visibility. Test identities are accepted only when `app_env=test` and the deterministic provider is active.

## 2. Resource scope model

Every V3 resource resolves to a scope before data access:

```text
PUBLIC_VERSION(course_id, publication_version_id)
OWNER_COURSE(owner_user_id, course_id)
OWNER_WORKSPACE(owner_user_id, workspace_id, official_course_id)
REVIEW_SNAPSHOT(reviewer_id, snapshot_id, expires_at)
SERVICE_JOB(job_id, source_version_id, output_kind)
```

An object copied from private input remains private unless an explicit publication workflow binds that exact derivative version. “Generated” does not mean “public.”

## 3. Authorization matrix

Legend: `R` read; `W` mutate; `P` publish/review action; `—` denied/hidden. All cells still require record lifecycle to be active.

| Resource | anonymous | other user | owner | generic admin | scoped reviewer |
|---|---:|---:|---:|---:|---:|
| published official course/version | R | R | R | R/W draft | R |
| private user course | — | — | R/W | V2 policy only; not learning records | only snapshot |
| workspace/private overlay metadata | — | — | R/W | — | only snapshot |
| original file / DocumentVersion | — | — | R/download | — | snapshot read if consented |
| DerivedArtifact / preview | — | — | R | — | snapshot read if consented |
| private chunks/citations/material evidence | — | — | R | — | snapshot subset only |
| private KnowledgeNode/Tree/Spec draft | — | — | R/W | — | snapshot subset only |
| Journey/unit/coverage/progress | — | — | R/W through workflow | — | — |
| Problem/solution/bridge/position | — | — | R/W through workflow | — | — |
| Assessment answers/rubric before submit | — | — | server only | — | — |
| submitted attempt/performance/grade | — | — | R; workflow writes | — | — |
| publication request | — | — | create/withdraw own course or exact Overlay selection | P for separate course/official/Overlay workflows | target: assigned snapshot only |
| content-free operational diagnostics | — | — | own safe status | aggregate/server logs | — |

Denial after authentication uses resource-not-found semantics for private objects so ID probing cannot distinguish nonexistent from unauthorized.

## 4. Endpoint and verb coverage

Authorization must be identical for:

- collection list/count and single metadata;
- `GET`, `HEAD`, conditional and byte `Range` requests;
- original download, inline preview and every derived-artifact route;
- ingestion job status/error and upload quota calculations;
- retrieval candidates, chunks, citations and exact-question locators;
- node/tree/Spec/plan/journey/problem/solution/step/bridge/assessment APIs;
- export, debug, diagnostics, audit and administration endpoints;
- cache lookup and model-context construction.

Checking only the UI or only the final download route is insufficient.

## 5. Data provenance types

| Evidence family | Required identity | Permitted use | Forbidden substitution |
|---|---|---|---|
| MaterialEvidence | course/workspace, document version, derived/chunk version, locator, scope/owner | support definitions, teaching and problem context | cannot prove the user was taught or performed well |
| TeachingDeliveryEvidence | workspace, journey, pinned Spec/Item, unit/step revision, section, completed state | derive REQUIRED coverage and Learning Progress | cannot become Assessment score/grade |
| PerformanceEvidence | assessment session, question/attempt revision, rubric dimension, assistance/exposure state | weak-point/readiness/grade calculations | cannot be inferred from answer display or teaching coverage |

Every citation shown to a user includes a server-resolved accessible source version and stable locator. If a source is revoked, historical audit may retain its opaque reference/hash, but new UI/model requests do not disclose the content.

## 6. Document and preview capability matrix

This policy is implemented locally for the Stage 1 file types. Limits are server settings with conservative defaults and remain production-configuration inputs.

| Type | Inline capability | Processing rule | Fallback |
|---|---|---|---|
| PDF | browser PDF preview | serve authorized bytes with `nosniff`, range support and safe disposition | authorized download |
| PNG/JPEG/WebP/GIF (non-active) | image preview | validate signature/dimensions/size; no remote public URL | authorized download |
| Markdown/TXT | escaped safe render | UTF decoding, bounded chars, no raw HTML/script execution | text/plain download |
| CSV | bounded table | bounded bytes/rows/columns/cell length; never formula-execute | download with truncation reason |
| `.ipynb` | static code/markdown/existing output view | parse JSON with limits; sanitize outputs; **never execute cells** | download with parse reason |
| DOC/DOCX/PPT/PPTX/XLS/XLSX | derived PDF/safe preview when converter is configured | isolated local converter, timeout/resource limits, immutable output artifact | `DOWNLOAD_ONLY` with explicit reason |
| HTML/SVG/executable/archive/unknown | no inline active render by default | quarantine/unsupported policy according to ingestion allowlist | safe download only if policy permits |

Original bytes are immutable. Conversion does not replace `stored_path`; it creates a content-addressed `DerivedArtifact` linked to the exact `DocumentVersion` and converter/policy version.

## 7. Upload and filesystem boundary

1. Normalize the client filename to display metadata only; server generates the storage name.
2. Enforce extension allowlist, MIME/signature compatibility, total bytes and owner quotas.
3. Resolve every path and reject symlinks or paths outside the configured upload root.
4. Stream to a new random staging file with hard byte limit; compute SHA-256 while writing.
5. Validate/scan according to capability; atomically promote inside the owner/course/document namespace.
6. Create DB metadata only with the final owned path, or compensate the owned file on transaction failure.
7. Do not return absolute server paths or parser/converter stderr to clients.
8. Office conversion and notebook parsing run without network, shell interpolation or user-controlled command arguments.

## 8. Model and prompt boundary

- The authorized retrieval layer chooses source versions before the provider call.
- Documents, images, search results, user preferences and generated plans are low-trust data, serialized separately from versioned system templates.
- Private content is sent only to the explicitly configured provider endpoint after region/account configuration is reviewed; no automatic fallback.
- A model-proposed owner, official/public status, node link, coverage item, grade or tool action is rejected unless the deterministic backend validates it.
- Provider errors expose stable error class/request correlation only. Logs exclude prompt/response bodies, source excerpts, identity tokens and keys.
- Cache keys contain owner/workspace + all relevant policy/template/model/source versions. No cross-user semantic cache for private inputs.

## 9. Assessment secrecy and provenance

- Formal session creation selects and freezes question revisions server-side.
- Correct answers, rubrics, grading prompts and hidden scoring metadata are not embedded in the Web bundle or pre-submit JSON.
- A family exposed by `Problem Mode` is excluded when a formal Blueprint is selected. Help or answer reveal inside an active Assessment irreversibly changes the whole session to `PRACTICE` and all resulting evidence to non-independent.
- Only qualifying submitted independent attempts contribute to GradeSnapshot/readiness; assisted practice may still generate clearly labeled learning feedback.
- Generated or external-inspired questions store source class, author/model/template version, validation status and visibility. Private source material cannot be published by transformation alone.
- Before submit, the client projection contains question prompts/options/marks but no answer, rubric criterion or grader prompt. Open-response grading receives only the submitted answer and exact frozen criterion; GradePolicy choice and final arithmetic remain server-side.

## 10. Lifecycle and revocation

| Event | Immediate effect | Retained history | Physical cleanup |
|---|---|---|---|
| original missing/corrupt | new preview/model context fails explicitly | metadata/hash/audit | no invented replacement |
| user revokes/deletes private document | future retrieval, preview, conversion and context denied; jobs cancelled | opaque citations/event history per retention policy | async owned artifacts after tombstone/check |
| workspace archived | no new operations/uploads; owner may export/read allowed history | journeys/coverage/assessment/audit | no implicit cascade |
| course deletion request | blocked while active workspace/publication references exist | audit and explicit conflict | only after approved dependency plan |
| publication withdrawn | future public/shared access unavailable; cache generation changes | immutable review/publication audit | private source remains owner data; prior lawful downloads are not recallable |
| reviewer grant expires | review routes denied | decision/audit | no owner data deletion |

Deletion is not implemented through `git clean`, database rebuild or broad recursive filesystem commands. Foreign keys default to `RESTRICT` at ownership boundaries where silent cascading would lose private history.

## 11. Required negative evidence

Stage acceptance requires tests with two ordinary users, one admin, anonymous, and where applicable a scoped reviewer. At minimum test guessed IDs, list/count leakage, `HEAD`/`Range`, stale signed/derived URL, cross-user cache, missing file, symlink, unsafe media, revoked source during an open Bridge, provider error/log redaction and hidden assessment answer inspection.

Current local evidence covers owner vs second user/Admin/anonymous for private metadata, stable source versions, preview, original and derived content including `GET`, `HEAD` and byte `Range`. Stage 6 proves that reviewed course sharing is version-bound and revoked on withdrawal; an Overlay candidate list exposes only the current owner's private nodes/specs/document versions/artifacts/evidence; unselected resources and chats stay outside the snapshot; another user receives a non-disclosing 404; and generic Admin has no ambient private-document listing. Stage 8 repeats this boundary in a browser with owner, second-user and Admin processes sharing one synthetic database: Admin can approve only the selected immutable node snapshot and cannot open the owner's workspace. A valid owner with no current Overlay request receives nullable `200`; parent-workspace lookup happens first, so foreign IDs remain 404 and the Web client propagates that denial. Official publication requires a second Admin, locks reviewed node/tree/Spec/evidence inputs, publishes only the exact snapshot, withdraws a superseded release and increments withdrawal cache generation. Retrieval SQL filters frozen source versions before candidate generation and evidence is authorized again before prompt assembly. Assessment tests exclude another owner’s private questions, `MODEL_ONLY` candidates and answer-exposed Problem families; pre-submit DTO tests find no hidden answer/rubric. Malformed/oversized Office, image, CSV/notebook preview and source/artifact integrity cases are covered. Expiring per-reviewer assignment, dedicated public chunk/citation endpoints, production object storage and crash-safe cleanup retry remain unimplemented or unverified, so this document is not a production security acceptance.
