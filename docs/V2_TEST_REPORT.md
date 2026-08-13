# CourseMate AI V2 Test Report

Executed: 2026-08-14 on `feature/coursemate-v2-ai-tutor` using inert provider variables and
deterministic test providers. No billable model call was made.

## Final automated gates

| Gate | Result |
|---|---|
| RAG pytest | **166 passed**, 1 non-failing dependency warning |
| RAG Ruff | **passed** for app, tests and all three Python operational scripts |
| RAG/monitor strict Mypy | **passed**, 40 source files |
| Web Vitest | **29 passed** across 6 files |
| Agent Vitest | **51 passed** across 9 files |
| Web/Agent TypeScript | **passed** |
| Web production build | **passed**, 310.12 kB JS / 90.85 kB gzip |
| Agent production build | **passed** |
| Playwright Chrome | **4/4 passed** |
| npm production dependency audit | **0 vulnerabilities** |
| Migration-on-copy | **integrity ok**, no FK violations, versions 1-10, 8 activity triggers, second run idempotent |
| Full backup/isolated restore | **passed** for RAG DB + Agent DB + 68 uploads; hashes/counts/integrity/FKs matched |
| API readiness/security headers | **passed** including generic 503, read-only missing-DB behavior, HSTS/CSP/Permissions Policy |
| Monitoring probe | **passed** for fresh/stale/incomplete/symlink backup and artifact handling plus malformed/non-HTTPS fail-closed behavior |
| Tracked credential-pattern scan | **no match** |

The warning is Starlette's TestClient transport deprecation; it does not change behavior and its
dependency migration should be scheduled deliberately.

## Browser journeys

1. Asks three consecutive course-scoped questions, waits for each completed streamed/cited answer,
   proves all three turns survive refresh and a fresh browser context using the deterministic
   login-equivalent adapter, then switches official courses and adds an answer to the study plan.
2. Creates a task through the Function Calling Agent, then edits and completes it.
3. Uses navigation and core actions at a 390 px viewport.
4. Creates a private course, uploads/indexes a document, previews/saves a teaching profile, gives
   dual publication consent, receives pending state, asks from the private source, and deletes it.

## Security/behavior coverage

The suites exercise Chinese/English language policy; persisted history/continuation; general-chat
bypass; intent/rewrite/strategy progression; exact filename/question/subpart location; structured
and hybrid fallback; citation truth; prompt injection hierarchy; admin-only diagnostics; two-user
course/conversation/profile/task isolation; file validation/deletion; profile version pinning/restore;
owner withdrawal and dual-consent/admin publication; post-publication owner lock;
course/file/byte quotas; course language inheritance; and all legacy Agent tools.
Course activity timestamps are also verified for document, conversation and profile changes.
The operational tests additionally cover incomplete backups, checksum tampering, unsafe/duplicate
archive members, manifest count/size budgets, non-overwrite restore and distinct database paths.

## Acceptance status

| Criterion | Status | Evidence/limitation |
|---|---|---|
| A Chinese | PASS | deterministic language/prompt/QA tests |
| B History | PASS | API/UI/browser persistence coverage |
| C General chat | PASS | greeting bypasses no-evidence refusal |
| D Grounded QA | PASS | hybrid retrieval, SSE, citations regressions |
| E Exact question | PASS | real-corpus isolated golden locator cases |
| F Deep tutor | PASS (contract) | strategy/prompt/examples covered; subjective live quality unbenchmarked |
| G Model benchmark | **NOT PASS** | live paid 50-case comparison prohibited/unrun |
| H Create course | PASS | API/UI/Chrome create-upload-index-chat |
| I Private default | PASS | two-user matrix across endpoints |
| J Teaching profile | PASS | typed/versioned/profile pinning |
| K Prompt builder | PASS | deterministic preview/edit/save |
| L Publication | PASS | dual consent + admin approval + review lock |
| M Existing features | PASS | complete RAG/Web/Agent/browser regression |
| N Production | **NOT PASS** | live host/API inaccessible; no deployment credentials/runtime evidence |

CourseMate V2 is source- and local-release-ready, not production-accepted. Criteria G and N must not
be relabeled without new external evidence.
