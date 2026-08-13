# CourseMate AI V2 Completion Audit

Audited: 2026-08-14 against the 92-section master request, current source, tests, migration copy,
and release documents on `feature/coursemate-v2-ai-tutor`. “Pass” means local source evidence;
“external” means the request cannot be honestly completed without credentials, budget, or live
runtime evidence.

## Executive result

| Scope | Result | Evidence boundary |
|---|---|---|
| Sections 0-4: truth, safety, baseline, branch | PASS | V2 baseline/spec/gap analysis and isolated branch |
| Sections 5-12: language/history | PASS locally | course defaults, owner-scoped history, refresh + fresh-context login equivalent |
| Sections 13-20: RAG-aware tutor | PASS (contract) | deterministic router, transparent grounding, progressive strategy |
| Sections 21-35: exact retrieval/teaching | PASS | structured metadata/locator, context builder, golden/eval tests |
| Sections 36-42: providers/benchmark/fallback | PARTIAL / EXTERNAL | abstraction, research and harness pass; live paid benchmark and winner do not |
| Sections 43-50: private courses/storage | PASS | ownership, upload validation, atomic quotas, isolated paths, safe deletion |
| Sections 51-56: teaching profiles | PASS | strict profiles, builder, immutable versions, restore-as-new-version |
| Sections 57-63: publication/community | PASS except optional clone | consent, withdraw, admin file review, lock/read-only; clone deferred for licensing |
| Sections 64-68: database models | PASS | additive schema versions 1-10 and migration-on-copy |
| Sections 69-76: tutor flows/UX | PASS | API/component/Chrome journeys and responsive test |
| Sections 77-86: evaluation/tests | PASS locally | 50-case data/harness plus 163/29/51/4 automated gates |
| Sections 87-90: production | LOCAL PASS / EXTERNAL BLOCKED | config/runbook/rollback pass; live deploy/smoke not executed |
| Sections 91-92: handoff/file packs | PASS | root handoff and `docs/file-request-packs/README.md` |

## Detailed requirement ledger

| Sections | Status | Primary evidence |
|---|---|---|
| 0-2 | PASS | Git/source treated as truth; production writes gated; no secret committed |
| 3-4 | PASS | `V2_BASELINE.md`, `V2_CURRENT_GAP_ANALYSIS.md`, feature branch |
| 5-7 | PASS | `tutor/language.py`, `courses.preferred_language`, conversation inheritance tests |
| 8-12 | PASS locally | CRUD/continuation/auto-title, refresh and fresh-context deterministic login; real Clerk relogin remains production smoke |
| 13-17 | PASS | router modes, general bypass, evidence/supplement labels and citation rules |
| 18-20 | PASS | strategy progression, bounded history, profile-pinned student context |
| 21-28 | PASS | reference parser, structured ingestion, parent/adjacent context, exact golden tests |
| 29-30 | PASS | retrieval evaluation and administrator diagnostics |
| 31 | PASS | history-aware query rewrite with stored original message preserved |
| 32-33 | CONDITIONAL-NOT-NEEDED | deterministic + hybrid evaluation did not justify multi-query/rerank cost/complexity |
| 34-35 | PASS | deduplicated context budget and fixed tutor prompt hierarchy |
| 36-38 | PASS | independent chat/embedding/Agent config and official-source research report |
| 39-41 | EXTERNAL-NOT-PASS | harness/data/report exist; paid provider calls were not authorized |
| 42 | CONDITIONAL-NOT-ENABLED | no unbenchmarked automatic provider fallback or duplicate charging introduced |
| 43-50 | PASS | central access, private creation, validated ingestion, hashed owner namespace, quotas, delete |
| 51-55 | PASS | structured enums/bounds, deterministic builder, editable preview, safe compiler hierarchy |
| 56 | PASS | version history and owner-safe restore that appends a new version |
| 57-62 | PASS | dual consent, pending withdrawal, admin file inspection/decision, public read-only lock |
| 63 | OPTIONAL-DEFERRED | file clone/fork requires a license, attribution and consent policy first |
| 64-68 | PASS | schema audit/models/migrations 1-10; owner, activity and audit relations covered |
| 69-72 | PASS | documented and tested grounded, exact, general and follow-up flows |
| 73-76 | PASS | grouped Course Home; file count/index/recent activity; QA and Settings workspaces |
| 77-79 | PASS locally | versioned 50-case dataset, rubric, deterministic regression threshold |
| 80-86 | PASS | conversation/course/publication/permission/injection/exact/general suites |
| 87-88 | PASS locally | current architecture retained; copy initialized twice with integrity/FK/count evidence |
| 89-90 | EXTERNAL-NOT-PASS | no live access/backup/runtime inventory; deployment and production smoke forbidden |
| 91-92 | PASS | handoff covers required themes; 14 minimal review packs listed |

## Final acceptance matrix

A-F and H-M pass locally. G (live model benchmark) and N (production deployment/smoke) remain
explicitly not passed. This branch is a locally verified release candidate, not a production-accepted
release. Do not change either label without current external evidence.

## Verified release evidence

- RAG/operations: 163 pytest, Ruff, strict Mypy (40 files).
- Web: 29 Vitest, TypeScript, production build (310.12 kB JS / 90.85 kB gzip).
- Agent: 51 Vitest, TypeScript and production build.
- Browser: Chrome 4/4, including three completed QA turns, refresh/fresh-context deterministic
  login recovery, and the private-course journey. Real Clerk logout/login remains part of
  production smoke.
- Supply chain: npm production dependency audit, 0 vulnerabilities.
- Migration copy: versions 1-10, eight activity triggers, integrity `ok`, zero foreign-key
  violations, two-run idempotence; 3 courses, 67 documents, 1,937 chunks, 19 conversations,
  38 messages.
- Full local recovery rehearsal: RAG DB + Agent DB + 68 uploads; restored paths/SHA-256 and row
  counts matched, both databases had integrity `ok` and zero foreign-key violations. The Agent
  source was a deterministic E2E sample, not an unknown production database.

## Required external next actions

1. Rotate the provider credential previously at risk and update only backend secret storage.
2. Supply redacted production inventory/access and prove a restorable RAG DB + Agent DB + uploads backup.
3. Authorize a bounded budget/model list before running the live 50-case benchmark.
4. Only then deploy incrementally, execute production smoke tests, monitor, and append evidence.
