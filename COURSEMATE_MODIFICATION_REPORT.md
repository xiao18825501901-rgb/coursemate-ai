# COURSEMATE_MODIFICATION_REPORT

Task: 14 professional templates + Thinking teaching + unified dual-pane history +
exercises & explanations + course sharing + student verification (DSH total-control prompt).

Modified project path: `D:\CourseMate_COMPLETE_ARCHIVE_20260918\01_SOURCE_REPOSITORY`
(ACTUAL_SOURCE_ROOT; original C-drive repository and all archived originals untouched).
Pre-change git marker: branch `archive-baseline/pre-change-20260918` at `c67904b`.
Local commits (no push — no authorization): `ef4d02d4` (features) + `f150615`
(claim-race fix + legacy contract test updates).

## 1. What the user asked (summary) and what was there before

| Ask | Before | After |
|---|---|---|
| Course name shows exactly what the user typed | course id carried a `-YYMMDDHHMMSS` suffix; DTO `code`=id; some historical names even embedded the id | name stored/displayed as typed; suffix stays only in the internal id; migration 025 repairs provable `<base> <id>` names; cards show `name` |
| Dynamic run status, no fixed pipeline text | hardcoded `CS3481 模板 → 千问撰写 Prompt → 千问教学` + `Shift + Enter 换行` | `正在思考中/正在输出中` per lane driven by SSE; idle hidden; hint removed |
| Thinking toggle (teach pane, red, default off) | `enable_thinking=False` hardcoded, no product switch | server field `teaching_mode normal|thinking`; red toggle with aria-pressed |
| normal mode = direct answer, no plan | every message ran plan→generate (two calls) | normal = single direct call (题目 Word prompt for problem lane); thinking = template→plan→work |
| 14 professional templates + OTHER, real full text | single CS3481 template only | 15-template registry from the actual Word files (full bodies, distinct hashes) |
| Course classification | none | WAITING_FOR_MATERIALS→CLASSIFYING→CLASSIFIED/OTHER/FAILED_RETRYABLE + manual correction; OTHER fallback; validation threshold |
| plan never visible | `GET /runs/{id}` returned `generated_prompt`; UI had 查看本次教学 Prompt | response whitelist; SSE length-only; UI button removed; old records equally blocked |
| Unified dual-pane history | per-lane conversations + `cmui_layout` | `cmui_pairs` (one history item restores both panes), unique node binding, ⋯ menu, migration without guessing |
| 做一题 / 显示答案 / 详解 | none | exercise generation with server-side hidden answer, idempotent reveal, per-step floating explanation windows with follow-ups |
| Campus course type | only official/user | `display_type` campus/shared/private separated from access rules (`requires_student_verification`) |
| Student verification (7-digit codes) | none (Clerk pending-session refusal only) | HMAC-stored codes, transactional redemption, rate limiting, admin issuance, grandfathered one-time snapshot |
| Inbox 共享课程 + snapshot sharing | DMs/notifications only | frozen snapshot shares (files copied, 3 history scopes, idempotent), join with provenance, verification preserved |

## 2. Changed files (backend)

- `services/rag-api/app/cm_update/app.py` — teaching_mode plumbing, pair endpoints,
  classification endpoints, verification endpoints, share endpoints, exercise/explanations
  endpoints + runners, run-response whitelist, campus gate (`course_gate`) on all content
  routes, pair-aware conversation creation, startup grandfathering, status labels.
- `services/rag-api/app/cm_update/provider.py` — mode-aware generators, template-based
  planner, direct/problem/exercise/explanation/classification calls, TestProvider mirrors.
- `services/rag-api/app/cm_update/db.py` — schema 5→6 (tables + amendments + `_migrate_pairs`).
- `services/rag-api/app/cm_update/social.py` (new) — verification/sharing/classification helpers.
- `services/rag-api/app/cm_update/templates.py` (new) — template registry.
- `services/rag-api/app/cm_update/steps.py` — `answer_steps_parse`.
- `services/rag-api/app/cm_update/models.py`, `config.py`, `auth.py` — DTOs, verification
  secret, auto-verify dev flag (production-forbidden).
- `services/rag-api/app/cm_update/prompts/*` — 20 resource files (14 templates + OTHER +
  3 Word prompts + plan writer + classification instruction; original CS3481 kept).
- `services/rag-api/app/ui_extension/domain.py` — DTO display_type/verification fields,
  `course.create_shared`, `verification.grandfather_candidates`.
- `services/rag-api/app/db.py` + `migrations/025_campus_display_and_verification.sql` —
  V3 schema 25: `learning_pairs`, course display columns, one-time data repair.
- `services/rag-api/app/models.py` — `Course.display_type` / `requires_student_verification`.
- `services/rag-api/.env` → renamed to `.env.archived-redacted-hold` (the archive-time
  redacted dev env leaked `<REDACTED>` literals into test settings; dev runs use env vars).
- `pnpm-workspace.yaml` (new) — pnpm workspace + esbuild allowBuilds (dev tooling).

## 3. Changed files (frontend, cmui shell)

`apps/web/src/ui/`: `api.js`, `pages.jsx`, `App.jsx`, `icons.jsx`, `styles-extra.css` —
Thinking toggle + 做一题, dynamic run status, exercise/reveal/详解 windows, unified pair
history with binding menu, display-type badges + verification gating, account 学生认证,
inbox 共享课程 wizard + received/sent shares + join. (Detail in the frontend agent's
report; all texts in Chinese; no new dependencies.)

## 4. Tests run

- New contract suite: `tests/test_current_change_features.py` — 11 tests — **11 passed**.
- **Full rag-api regression: 542 passed, 0 failed** (final run; legacy contract
  suites updated to the new defaults; one real backend bug found and fixed —
  see TEST_REPORT.md).
- Web: `tsc -b && vite build` exit 0; vitest **55 passed** (13 files).
- Agent: `tsc` exit 0; vitest **66 passed** (10 files).
- Local HTTP smoke (standalone uvicorn + TestProvider): course "x" naming, pair,
  normal-mode run, no-plan-leak run response, exercise/reveal/explanation,
  verification status — all green.

## 5. Verified locally vs real model vs not run

- LOCAL_TESTED (deterministic test provider): everything above — zero billable calls.
- REAL_MODEL_VERIFIED: NOT_RUN — qwen3.8-max classification/teaching/exercise/explanation
  quality and the native reasoning-parameter question need an explicit paid budget
  approval; nothing here calls the real provider.
- PRODUCTION_DEPLOYED: NOT_PERFORMED — no production writes, no migrations on the live
  DB, no push. `SOURCE_MODIFIED: yes (D: workspace only)`.

## 6. Migration & rollback

See `docs/current-change/MIGRATION_AND_ROLLBACK.md` (additive schema 25 + UI schema 6,
idempotent; application rollback compatible; data restore independent; deployment
prerequisites listed).

## 7. Reports

- `docs/current-change/BASELINE_AND_SOURCE_ROOT.md`
- `docs/current-change/REQUIREMENTS_TRACEABILITY.md`
- `docs/current-change/TEMPLATE_REGISTRY_AND_CLASSIFICATION.md`
- `docs/current-change/PLAN_WORK_AND_PRIVACY.md`
- `docs/current-change/UNIFIED_HISTORY_AND_NODE_BINDING.md`
- `docs/current-change/EXERCISE_AND_EXPLANATION.md`
- `docs/current-change/COURSE_SHARING_SNAPSHOT.md`
- `docs/current-change/STUDENT_VERIFICATION.md`
- `docs/current-change/MIGRATION_AND_ROLLBACK.md`
- `docs/current-change/TEST_REPORT.md`
- this report.

## 8. Remaining gaps (honest)

- Integrated-mode share JOIN copies history in the UI DB and creates a real V3 course,
  but deep V3 document/workspace file remapping for shared course files is NOT implemented
  (declared in COURSE_SHARING_SNAPSHOT.md).
- Auto-classification in integrated mode classifies on file metadata only (bounded);
  deeper corpus sampling needs the deployment round.
- Real-model quality checks and any paid verification are NOT_RUN by design.
