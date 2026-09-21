# DSH_JEV_DEEPSEEK_PAUSE_AND_HANDOFF_REPORT

Pause report for the CourseMate next-version round. Everything below was read from the real
workspace during this pause; nothing is inherited from an earlier narrative. The full regression
that was running when the pause arrived was a read-only local pytest run; it was allowed to finish
naturally and **completed green after the pause** (§5, §10).

Generated: 2026-09-22 (local), pause instruction from the owner.

---

## 1. Executive Summary

The locally completable part of the round is **finished, verified and committed** in four commits;
the production part is **untouched and blocked on owner authorization, credentials and budget**.

* Work delivered this round: DeepSeek-only provider migration (five roles + agent-api, no Qwen
  fallback), the TypeSafe Jev semantic layer (12 definitions, all in `shadow`), the 16 V2 templates
  behind a versioned registry, the learning-start fact (migration 026) and its projection fix, the
  global retrieval fusion, the five-question assessment flow (migration 027) with the fullscreen
  workspace, a deterministic explicit-command router, the A/B/C/D ablation harness, a DeepSeek live
  canary with a pre-call cost ceiling, and a rollback-compatibility verifier.
* Verified locally: full backend regression **948 passed / 0 failed** on the delivered revision
  `6b85df7` (808 before the round-4 additions + 140 new tests); web **64/64** and agent **72/72** with
  both builds green; schema probe clean; V2 hashes 16/16; rollback verdict
  `ROLLBACK_SAFE_WITH_MIGRATED_DB`.
* **Not** verified, and not claimed: any live DeepSeek call, any live TypeSafe Jev call, the ablation
  *result*, browser journeys, production deployment, production acceptance. Zero model calls were
  made; zero cost was incurred.
* Production: `PRODUCTION_TOUCHED = no`.

**Do not read "implemented with fake transports and contract tests" as "production-integrated".**
The Jev layer is wired but every definition is `shadow`; the DeepSeek providers are migrated and
guarded but never executed against the live API.

---

## 2. Exact Git State (read at pause time)

| Item | Value |
|---|---|
| `SOURCE_ROOT` | `D:/CourseMate_COMPLETE_ARCHIVE_20260918/01_SOURCE_REPOSITORY` |
| `BRANCH` | `fix/codex-dsh-audit-20260919` |
| `HEAD` | `6b85df75257ede8b88b4034ceb08ca2e66654f90` |
| `WORKTREE_CLEAN` | **yes** at the moment of inventory (`git status --short` empty) |
| `UNCOMMITTED_FILES` | none |
| `UNTRACKED_FILES` | none |
| `REMOTE_STATUS` | `origin` = `https://github.com/xiao18825501901-rgb/coursemate-ai.git`; branch is **ahead 5**, nothing pushed |
| `AHEAD/BEHIND` | ahead 5, behind 0 |

`git log --oneline -15` (most recent first):

```
6b85df7 feat: deterministic command router, A/B/C/D ablation harness, DeepSeek live canary
3dd9d40 test: verify rollback compatibility for the 026-028 migration boundary
d4df8a2 docs: record delivered revision in the release report
bdb1aa7 feat: CourseMate next version - DeepSeek-only providers, Jev semantic layer, V2 templates, five-question assessment
b05fd29 fix: learning-start fact and global retrieval fusion (pack probes green)
c309219 style: clean production report whitespace
3ed05b4 docs: record four changes production release evidence
1e59c7a chore: add bounded four-change live Qwen canary
480a225 chore: manage synthetic release identities safely
dca07a8 fix: tolerate CRLF source metadata in release guard
5ea760c chore: guard Schema 13 production switch
4ef5064 Add guarded production backup window
c484bb9 Harden Qwen operation budget preflight
666fdb3 docs: record four-change release evidence
e6c77dc feat: apply CourseMate four product changes
```

Session delta against the round baseline `b05fd29`: **104 files changed, +16061 / −280**
(39 modified, 65 added). `b05fd29` itself was already local-only, so 5 commits are unpushed.

**Uncommitted after this pause: exactly two files**, both produced by this pause and neither
committed on purpose (the owner asked for no casual commits): this report, and the pause update to
`DSH_JEV_DEEPSEEK_EXECUTION_STATE.md`. No temporary file was added to the index to make the tree
look clean.

---

## 3. Goal Progress — where the total objective actually stands

| Goal element | State |
|---|---|
| Migrate generative AI to the latest stable DeepSeek | **DONE_LOCAL** (wiring + guards + tests); live calls **WAITING_ACCESS** |
| Integrate Jev as a backend semantic layer | **DONE_LOCAL** in `shadow`; live calls **WAITING_ACCESS** |
| Retrieval hit rate / evidence quality | merge + global ranking + exact-locator priority **DONE_LOCAL**; measured Recall/MRR **WAITING_ACCESS** |
| Teaching continuity / context | anchors vs filterable history **DONE_LOCAL**; Jev context selection **shadow only** |
| Coverage quality | coverage semantics + start fact **DONE_LOCAL**; Jev support signal **shadow only** |
| Assessment quality | five-question flow **DONE_LOCAL**; live grading **WAITING_ACCESS** |
| "开始学习但仍显示未学习" fix | **DONE_LOCAL**, verified by tests |
| "课程知识点数" → "课程知识点" | **DONE_LOCAL** (both titles; verified in `pages.jsx`) |
| Five-question fullscreen assessment | **DONE_LOCAL** |
| Unified answer input / upload / drafts | **DONE_LOCAL** |
| Per-step reference answers, marks, 详解 | **DONE_LOCAL** |
| Result written back to the node's 测评结果 | **DONE_LOCAL** |
| Replace the 16 prompts | **DONE_LOCAL**, manifest-verified 16/16 |
| Preserve existing architecture and production data | **DONE** (nothing on production was touched) |
| Prove Jev actually improves the project (A/B/C/D) | **NOT_STARTED as a result** — harness ready, no live data |
| Production release + acceptance | **WAITING_APPROVAL** |

Overall: the implementation layer is essentially complete; **every remaining item needs something
only the owner can give** (a credential, a budget, a labelled dataset, or production authorization)
except for the small local items in §9.

---

## 4. Completed Work (this round)

1. **Learning-start fact** — `migrations/026_learning_start_events.sql`, written from the accepted
   run in `_begin_learning`, projected by `_learning_start_fact`; NOT_STARTED→LEARNING on first real
   start; LEARNED still requires all REQUIRED coverage; legacy backfill only with a real artifact.
2. **Global retrieval fusion** — `app/learning/retrieval_orchestrator.py`: RRF across authorized
   scopes, per-scope recall caps, exact-target protection, boundary-aware budgeting, S-ids at
   projection; wired into `V3DomainAdapter._retrieve`.
3. **DeepSeek provider migration** — five roles + agent-api; contract verified live from official
   docs; host validation rejects non-DeepSeek base URLs; spy tests prove zero Qwen egress.
4. **16 V2 templates** — imported with manifest hash parity, versioned registry (V1 retained),
   题目/详解 and the `exercise.v2` hidden-answer contract untouched.
5. **Jev layer** — `app/jev/` gateway (off/shadow/on, injectable transport, typed errors, receipts,
   scoped cache) + 12 catalog definitions; retrieval rerank and coverage support wired in shadow.
6. **Five-question assessment** — migration 027 (6 tables, widened enum, 4 table rebuilds with data
   copy, 10 triggers dropped/recreated), real pool preparation replacing the permanent 409,
   fullscreen workspace with one composer, drafts, raw-score display, NEEDS_REVIEW never overwrites
   the last valid result.
7. **Deterministic explicit-command router** — `app/learning/intent_commands.py`; explicit commands
   never spend a Jev call; conservative (a command with a new object stays semantic).
8. **A/B/C/D ablation harness** — offline by default, twelve metrics, fail-closed against a fake
   transport, an unlabelled dataset and a placeholder baseline.
9. **DeepSeek live canary** — ten roles, native fields only, ceiling printed before any call,
   refusal without `--allow-billable`/key/prices/`--max-cost`.
10. **Rollback compatibility verifier + drift guard** — previous release runs against the migrated
    database; pre-027 column/table/enum snapshot frozen as a test.
11. **Fixes found by verification** (each with a negative control): the 027 trigger-loss bug; the V1
    template-version test pin; the hardcoded migration ceiling; the circular rollback check; the
    ablation's placeholder baseline and anchor mishandling.

---

## 5. Work In Progress / Interrupted

| Item | State | Where it stopped |
|---|---|---|
| Full backend regression on current HEAD `6b85df7` | **COMPLETED GREEN after the pause** — `948 passed, 0 failed, 2 warnings in 1312.19s (21:52)`, exit 0 | log `work/current-change/full_run_round4.log`. It is a read-only local pytest run, so it was left to finish naturally as the owner allowed; it ran on the frozen commit with no file change during the run. 808 (pre-round-4) + 140 (round-4 additions) = 948 |
| Everything else | nothing in flight | no build, no migration, no deploy, no model call was running |

The immediately preceding full run on the previous HEAD (`bdb1aa7` + docs) **completed green**:
`808 passed, 0 failed in 2074.86s`, exit 0, log `work/current-change/full_run_v.log`.

---

## 6. Not Started

* Live DeepSeek validation (text, structured, vision, tool replay, pricing).
* Live TypeSafe Jev validation, threshold calibration, promotion from `shadow` to `on`.
* The A/B/C/D ablation **result** and every listed metric on labelled data.
* Production backup, isolated restore rehearsal, migrations 026–028 on production, immutable
  release, Netlify/backend update, post-release backup and monitoring.
* Real signed-in browser journeys (multi-user, private isolation, learning, five-question flow).
* Visual render validation of the V2 documents (the manifest itself declares it not performed).
* Push of the 5 commits; `mypy` on this round's new files; Playwright (not used in this repo).

---

## 7. Source Changes (by area)

* `services/rag-api/app/jev/**` (new) — gateway, catalog + `decision_catalog.json`, service, receipts,
  errors, models.
* `services/rag-api/app/learning/{knowledge,intent_commands,retrieval_orchestrator,assessments,orchestrator,compiler,models,testing,provider,coverage_review}.py`.
* `services/rag-api/app/evaluation/{deepseek_contract,deepseek_canary,jev_ablation}.py` (new).
* `services/rag-api/app/ui_extension/domain.py`, `app/api/learning.py`, `app/cm_update/*`,
  `app/rag/answers.py`, `app/config.py`, `app/db.py`, `app/main.py`.
* `services/rag-api/migrations/026_learning_start_events.sql`,
  `027_assessment_preparation_reference.sql`, `028_jev_decision_receipts.sql`.
* `services/rag-api/app/cm_update/prompts/*_V2.txt` (16 files) + `templates.py` registry.
* `apps/web/src/ui/{pages.jsx,api.js,styles-extra.css}` + `AssessmentWorkspace.test.tsx`.
* `services/agent-api/src/{config.ts,openai/client.ts}`.
* `scripts/{run_deepseek_canary,run_jev_ablation,verify_rollback_compat}.py`, `scripts/rehearse_v3_migration.py`.
* Tests: 11 new files (see §10) plus updates to 6 existing suites.
* Docs: the five required reports, `MINIMAL_OWNER_ACTION_CARD.md`, `DSH_JEV_DEEPSEEK_EXECUTION_STATE.md`,
  `docs/jev-deepseek/*` (7 files).

---

## 8. Schema Changes

| Item | Value |
|---|---|
| Source schema target | RAG **28**, UI **13**, Agent **1** |
| Test schema (isolated copies) | RAG 28 — identical to source, verified by init + replay |
| Production schema | **NOT verified this session** (no production access; assumed unchanged, see §12) |
| New migrations | `026` learning start events, `027` assessment preparation/reference, `028` Jev decision receipts |
| Migration idempotence | verified (double `initialize()`), no `*_new`/`*_old` leftovers |
| `integrity_check` | `ok` |
| `foreign_key_check` | 0 violations |
| Rollback | `ROLLBACK_SAFE_WITH_MIGRATED_DB` — previous release runs against Schema 28 |
| Old-client compatibility | verified: no missing/retyped column, no narrowed CHECK enum, identical pool filter |

---

## 9. Module Status

### A. DeepSeek migration

| Item | State |
|---|---|
| Current default generative model | `deepseek-flash` (RAG `v3_model`, `deepseek_chat_model`; agent-api `openaiChatModel` default) |
| Providers migrated | Learning provider (plan/work/teacher/problem/grader), Coverage Reviewer, RAG grounded QA, cm_update (classification/exercise/assessment explanation), agent-api client |
| Providers still Qwen | **none as a default**; the historical `qwen3.8-max` path remains reachable only by explicit configuration (`CMUI_PROVIDER_MODE=qwen`, or `AGENT_MODEL_NAME=qwen3.8-max` with the Model Studio allowlist). `qwen_*` settings and an unused `SCHEMA`-era constant remain in config |
| UI provider | `provider_mode` default `disabled`; the label for the test provider still reads `测试 Provider · 非真实千问` (cosmetic leftover, see §16) |
| Learning provider | DONE_LOCAL |
| Coverage Reviewer | DONE_LOCAL |
| RAG answer | DONE_LOCAL |
| Course classification | DONE_LOCAL |
| Exercise generation | DONE_LOCAL |
| Problem solving | DONE_LOCAL |
| Explanation | DONE_LOCAL |
| Assessment (reference + feedback) | DONE_LOCAL |
| Vision | DONE_LOCAL (native image part with `detail`) |
| Node Agent | DONE_LOCAL |
| Real DeepSeek calls | **0 — NOT RUN** (`WAITING_ACCESS`, `WAITING_BUDGET`) |
| Model / endpoint | `deepseek-flash`; `https://api.deepseek.com/chat/completions` and `/responses` |
| Qwen fallback | none (spy tests; no automatic switch anywhere) |
| Proof of zero new Qwen requests | 4 egress/spy tests passed, incl. `test_v3_default_model_is_deepseek_not_qwen`, `test_learning_provider_rejects_non_deepseek_host_for_deepseek_model`, `test_qa_answer_provider_rejects_random_base_url` |

### B. Jev integration

| Module | Code | Unit tests | Integration test | Live call yet | Production enabled |
|---|---|---|---|---|---|
| JevGateway | yes | yes | yes (`test_jev_wiring`) | no | no (`shadow`) |
| SDK / API adapter (`SdkTransport`) | yes (lazy import) | yes | n/a | no | no |
| off/shadow/on | yes | yes | yes | n/a | all `shadow` |
| retrieval reranking | yes | yes | yes (wired) | no | shadow only |
| source support (`supports_claim`/`select_span`) | yes (helpers) | yes | no call site | no | no |
| context selection (`keep_segment`) | yes (helper) | yes | harness only | no | no |
| intent routing (`next_action`) | yes + deterministic router | yes | harness only | no | no |
| teaching strategy (`next_method`) | yes (helper) | yes | no case family | no | no |
| coverage review (`item_support`) | yes | yes | yes (provenance only) | no | shadow only |
| assessment criterion review | yes (helper) | yes | harness only | no | no |
| template classification | yes (helper) | yes | no | no | no |
| prerequisite selection | yes (helper) | yes | no | no | no |
| corpus quality | yes (helper) | yes | no | no | no |
| cache | yes (scope + invalidation) | yes | yes | n/a | active in shadow |
| receipts | yes (migration 028) | yes | yes | n/a | active in shadow |
| metrics | harness only | yes | n/a | no | no |
| fallback | yes (typed errors → deterministic) | yes | yes | n/a | active |

### C. Retrieval chain

official/private/workspace merge **DONE_INTEGRATED**; global ranking (RRF) **DONE_INTEGRATED**;
exact locator priority **DONE_INTEGRATED**; query rewrite **DONE** (existing, reused); structured
retrieval **DONE**; Jev rerank **DONE_LOCAL (shadow, reorder-only)**; evidence bundle / chapter pack
**DONE_LOCAL**; parent/adjacent expansion — not changed this round (existing behaviour preserved);
real Recall/MRR/NDCG **NOT RUN**; proof of improved hit rate **NOT RUN** (and explicitly not claimed).

### D. Learning progress

learning start event **DONE**; `started_at` **DONE**; NOT_STARTED/LEARNING/LEARNED **DONE**;
zero coverage + started ⇒ **LEARNING** (verified by updated regression suites); coverage semantics
unchanged; legacy migration of existing history **DONE** (backfill only with a real artifact);
UI refresh on entering the node **DONE_LOCAL**; SSE — not part of this change set; reload/relogin
projection **DONE_LOCAL** (server projection); composite node projection **DONE_LOCAL**.

**Answer to the direct question:** after a user genuinely starts learning a node, the page can now
show 学习中 — that is the fix, and it is covered by tests. It has **not** been observed in a real
browser against production.

### E. Assessment system

| Item | State |
|---|---|
| Node 开始测评 entry | DONE_LOCAL (third line of the node panel) |
| Fullscreen Assessment Workspace | DONE_LOCAL |
| 5 questions shown at once | DONE_LOCAL |
| Question pool | DONE (existing pool rules reused) |
| Pool-under-5 preparation flow | DONE_LOCAL (migration 027; idempotent/resumable/cancellable; replaces the 409) |
| Marks 10/15/20/25/30 = 100 | DONE (existing MARK_SCHEME, unchanged) |
| Reference solution | DONE_LOCAL |
| 题目 prompt / 详解 prompt | DONE (retained, unchanged) |
| Rubric | DONE (existing) |
| Jev criterion review | DONE_LOCAL (helper, shadow, not authoritative) |
| DeepSeek grader | DONE_LOCAL (never called live) |
| Image answers | DONE_LOCAL (payload path); live vision **NOT RUN** |
| OCR / vision transcription | DONE_LOCAL (contract); live **NOT RUN** |
| Unified answer input / upload | DONE_LOCAL |
| Drafts | DONE_LOCAL (draft ≠ submission) |
| Submit | DONE_LOCAL |
| Grade snapshot | DONE (existing `grade_snapshots` reused) |
| Raw score display (`78 / 100 · AI 自测`) | DONE_LOCAL |
| Node result refresh | DONE_LOCAL |
| Latest valid / independent result separation | DONE_LOCAL |
| Per-step 详解 + ExplanationWindow | DONE_LOCAL (existing component reused) |
| Retry / idempotency | DONE (existing request-id rules; preparation idempotent) |
| Hidden-answer protection | DONE (unchanged `exercise.v2` contract) |
| Reused vs new | Reused: `AssessmentService`, blueprint, `grade_snapshots`, performance evidence. New: preparation jobs, reference solutions, drafts, submission revisions, grading receipts, explanation contexts (all additive tables) |

### F. The 16 templates

14 professional V2 **imported**; EXERCISE V2 **imported**; OTHER V2 **imported**. Manifest hash parity
**16/16 verified**; text hashes and file hashes recorded in the registry; current active version
**V2**; V1 retained on disk so old conversations keep their version; 题目 prompt and 详解 prompt
**retained unchanged**; `exercise.v2` runtime contract **retained** (hidden private reference answer
still generated; "首轮不给答案" is a display rule only). Original DOCX hashes: the pack's manifest is
the authority and was verified; the DOCX files themselves were not re-read this round.

### G. UI changes

课程知识点 **DONE**; 学习进度 **DONE**; 测评结果 **DONE** (raw-score fallback); 开始测评 **DONE**;
全屏测评 **DONE**; unified answer input **DONE**; upload **DONE**; result display **DONE**;
详解 **DONE**; dark/light — unchanged (existing theme preserved); reasoning strength — unchanged;
history — preserved and filterable; mobile — unchanged; accessibility — unchanged (existing labels
and ARIA attributes preserved). **No visual/browser acceptance was performed.**

### H. Data and schema

See §8. Additionally: the published CS3481/GE2324 trees were **not regenerated**; no delete path was
added for chats, grades, bridges, template versions or learning evidence; the four 027 table
rebuilds copy rows before the rename (verified `INSERT INTO …_new SELECT`).

---

## 10. Tests — real numbers only

Nothing here is inherited from an earlier round; each line was executed in this session. Rows marked
NOT RUN were not executed.

| Suite | Command (from `services/rag-api` unless noted) | Code SHA | Result | Duration | Log |
|---|---|---|---|---|---|
| RAG full regression (previous HEAD) | `.\.venv\Scripts\python.exe -m pytest -v --ignore=work -o faulthandler_timeout=240` | `bdb1aa7`+docs | **808 passed, 0 failed**, exit 0 | 2074.86s | `work/current-change/full_run_v.log` |
| RAG full regression (current HEAD) | same with `-o faulthandler_timeout=300` | `6b85df7` | **948 passed, 0 failed**, exit 0 (finished after the pause) | 1312.19s | `work/current-change/full_run_round4.log` |
| Pre-fix full regression (evidence for the two fixes) | `pytest -q --ignore=work` | pre-fix tree | 789 passed / **17 failed** | 1262.63s | job output |
| Round-4 additions bundle | `pytest tests/test_deepseek_canary.py tests/test_jev_ablation.py tests/test_jev_ablation_baselines.py tests/test_intent_commands.py tests/test_schema_rollback_compat.py -q` | `6b85df7` | **140 passed** | 10.64s | this session |
| Migration-adjacent batch | `pytest tests/test_schema_rollback_compat.py tests/test_v3_migration_rehearsal.py tests/test_assessment_preparation_contract.py tests/test_assessment_runtime.py -q` | `3dd9d40` | **33 passed** | 132.91s | this session |
| Jev suites | `pytest tests/test_jev_{catalog,gateway,service,wiring}.py -q` | `bdb1aa7` | 23 passed | — | this session |
| Gap regressions (pack probes) | `pytest tests/test_jev_deepseek_gap_regressions.py -q` | `bdb1aa7` | 4 passed | — | this session |
| Retrieval fusion unit | `pytest tests/test_retrieval_fusion_unit.py -q` | `bdb1aa7` | 7 passed | — | this session |
| V2 template registry | `pytest tests/test_jev_deepseek_template_v2.py -q` | `bdb1aa7` | 21 passed | — | this session |
| V1 template integrity (fixed) | `pytest tests/test_codex_template_integrity.py -q` | `bdb1aa7` | 22 passed | — | this session |
| Migration rehearsal (extended) | `pytest tests/test_v3_migration_rehearsal.py -q` | `bdb1aa7` | 4 passed | 5.87s | this session |
| Assessment preparation contract | `pytest tests/test_assessment_preparation_contract.py -q` | `bdb1aa7` | 10 passed | — | this session |
| DeepSeek contract + roles | `pytest tests/test_deepseek_contract.py tests/test_deepseek_provider_roles.py -q` | `bdb1aa7` | 53 passed (+4 egress spies) | — | this session |
| DeepSeek canary regression batch | `pytest tests/test_deepseek_contract.py tests/test_deepseek_provider_roles.py tests/test_v3_model_canary.py tests/test_model_benchmark.py -q` | `6b85df7` | 74 passed (99 combined) | 30.11s / 35.42s | this session |
| Coverage + closure | `pytest tests/test_ui_extension_coverage_submission.py tests/test_ui_extension_learning_closure.py -q` | `bdb1aa7` | 49 passed | — | this session |
| Registry/publication/integration batch | targeted batch | `bdb1aa7` | 42 passed | — | this session |
| cmui features | `pytest tests/test_current_change_features.py -q` | `bdb1aa7` | 13 passed | — | this session |
| Schema probe (init + replay) | `python work/current-change/mig_probe.py` (repo root) | `6b85df7` | `integrity=ok`, `fk=0`, max 28, no leftovers, 17 assessment triggers | — | this session |
| Rollback verifier | `python scripts/verify_rollback_compat.py --release-tree <b05fd294 export>` | `6b85df7` | `ROLLBACK_SAFE_WITH_MIGRATED_DB`, exit 0 | — | `work/current-change/rollback-compat.json` |
| Ablation harness (offline) | `python scripts/run_jev_ablation.py --arm all --transport deterministic_fake --out <fresh>` | `6b85df7` | exit 0, verdict `NOT_INTERPRETABLE`, 4 arms × 12 metrics | — | `work/current-change/jev-ablation-verify3.json` |
| DeepSeek canary preflight | `python scripts/run_deepseek_canary.py --preflight-only` | `6b85df7` | exit 0, 10 calls, ceiling 46665 tokens | — | `work/current-change/canary-preflight.txt` |
| DeepSeek canary refusal | same `--allow-billable`, no key | `6b85df7` | exit 2, missing `DEEPSEEK_API_KEY` | — | this session |
| V2 template hashes | `python work/current-change/verify_template_v2.py` | `6b85df7` | 16/16 | — | this session |
| Ruff (all 12 new/changed files) | `ruff check <files>` | `6b85df7` | `All checks passed!` | — | this session |
| Web vitest | `pnpm --filter @coursemate/web test` | `bdb1aa7` | **17 files / 64 tests passed** | 34.12s | `work/current-change/web-test2.log` |
| Web build | `pnpm --filter @coursemate/web run build` | `bdb1aa7` | **exit 0**, built in 271ms | — | `work/current-change/web-build2.log` |
| Web TypeScript | covered by the build (tsc via vite); no separate `tsc --noEmit` run | `bdb1aa7` | see build | — | — |
| Agent vitest | `pnpm --filter @coursemate/agent-api test` | `bdb1aa7` | **10 files / 72 tests passed** | 2.49s | `work/current-change/agent-test3.log` |
| Agent typecheck/build | `pnpm --filter @coursemate/agent-api run build` | `bdb1aa7` | exit 0 | — | `work/current-change/agent-build3.log` |
| Mypy | — | — | **NOT RUN** | — | — |
| Playwright / browser journeys | — | — | **NOT RUN** (no real login available; no captcha bypass attempted) | — | — |
| Restore tests | covered by the full suite (`tests/test_backup_restore.py`), not run separately | `bdb1aa7` | passed within the 808 | — | — |
| Real DeepSeek canary | `scripts/run_deepseek_canary.py --allow-billable …` | — | **NOT RUN** (no credential/budget) | — | — |
| Real Jev canary / calibration | — | — | **NOT RUN** (no TypeSafe access) | — | — |

---

## 11. External Calls and Cost

| Channel | Actual calls this round | Notes |
|---|---|---|
| DeepSeek (any model) | **0** | no credential; the canary's preflight makes no network call (returns before any client is built) |
| TypeSafe Jev | **0** | no credential; `SdkTransport` raises `JEV_NOT_CONFIGURED` |
| Embedding | **0** | embeddings untouched; no re-index |
| Clerk API | **0** | no auth call; no test account created |
| Netlify operations | **0** | no deploy |
| SSH / production operations | **0** | no production host contact |
| GitHub push | **0** | 5 local commits unpushed |
| Production DB writes | **0** | no production database was opened |
| Model / region / token usage | none | no usage to report |
| Estimated cost | **0** | no paid call |
| Budget approval | **none requested/obtained** — see `MINIMAL_OWNER_ACTION_CARD.md` |

Offline fakes were used only inside tests and the offline harness; they are never presented as real
calls. The ablation artifact is stamped with the "EXAMPLE_NOT_LABELLED_FOR_RESULTS" dataset status.

---

## 12. Production State

**`PRODUCTION_TOUCHED = no`.**

All changes from this round exist only in the local workspace and in isolated temporary databases
under `%TEMP%`. Nothing was changed on the production server, the release directory, the three
production databases, the schema running in production, Netlify, DNS, Clerk, any production model or
env file, backups, or rollback artifacts. No backup was taken because no migration was applied.

Production facts recorded from earlier rounds for the next agent (not re-verified now, no access):
host `admin@47.237.179.69`, releases under `/home/admin/coursemate-v3-releases/`, DBs under
`/srv/coursemate/{rag,agent,data}`, backups under `/srv/coursemate/backups/`.

---

## 13. Known Bugs / Limitations

| ID | Item | Status |
|---|---|---|
| L1 | Live DeepSeek behaviour (streaming, structured, vision, tool replay, pricing) unverified | KNOWN_LIMITATION (WAITING_ACCESS) |
| L2 | Live Jev behaviour and thresholds unverified; all 12 definitions in `shadow` | KNOWN_LIMITATION (WAITING_ACCESS) |
| L3 | Ablation result unknown; no metric may be quoted as a quality claim | KNOWN_LIMITATION (WAITING_BUDGET) |
| L4 | `source.supports_claim.v1` / `select_span` are not armed by any frozen A/B/C/D arm, so citation-support accuracy is not measurable under the owner's arm definitions | OWNER_DECISION |
| L5 | `pedagogy.next_method.v1` is armed by C/D but the example dataset has no pedagogy case family, so it contributes no observations | LOCAL_CODE_WORK |
| L6 | UI test-provider label still reads `测试 Provider · 非真实千问`; historical `qwen_*` settings and the `qwen3.8-max` enum value remain for the legacy path | LOCAL_CODE_WORK (cosmetic) |
| L7 | `mypy` never run on the new modules | TEST_WORK |
| L8 | ~~Full regression on `6b85df7` incomplete at pause~~ — **resolved**: it completed after the pause with `948 passed, 0 failed`, exit 0 | CLOSED |
| L9 | V2 DOCX visual render validation not performed (declared by the manifest) | KNOWN_LIMITATION |
| L10 | An earlier post-fix full run stalled once (`pytest` idle, holding a loopback socket); the re-run completed green, so it is recorded as an environment observation, not a product failure | KNOWN_LIMITATION (unreproduced) |
| L11 | 5 commits unpushed | WAITING_APPROVAL |

---

## 14. Blockers and Required Owner Actions

All remaining blockers reduce to one card: **`MINIMAL_OWNER_ACTION_CARD.md`**.

1. **DeepSeek credentials + budget** — key + confirmed alias + a bounded batch ceiling, placed by the
   owner in the backend env (never in chat). Unlocks `DEEPSEEK_TEXT/VISION/AGENT`, `LIVE_MODEL_VALIDATION`.
2. **TypeSafe Jev access + budget + data-scope confirmation** — plus `pip install typesafe-sdk==0.7.0`
   (deliberately not a default dependency). Unlocks the live Jev path and calibration.
3. **A labelled ablation dataset** (the plan's 200 judgements / 40 trajectories / 30 image cases) and a
   decision on L4. Without it, no ablation result can be produced even with credentials.
4. **Production authorization** — backup, migrations 026–028, immutable release, Netlify/backend
   update, post-release backup and monitoring.
5. **A real login** for the browser acceptance journey (no captcha bypass will be attempted).

---

## 15. Direction-Drift Check (explicit answers)

| Question | Answer |
|---|---|
| Rebuilt an unnecessary new system? | **No.** New code is confined to the required layers (Jev package, evaluation tooling, one router). The assessment flow reuses `AssessmentService`, blueprint and `grade_snapshots`. |
| Introduced an unrequested database/queue/Neo4j? | **No.** No new datastore, no queue, no Neo4j. The neo4jev idea was applied over the existing knowledge graph only. |
| Deleted old functionality? | **No.** V1 templates retained, history never deleted, 027 rebuilds copy rows, no delete path added. |
| Re-introduced Qwen? | **No** as a model or fallback. The legacy explicit-config path and a cosmetic test label remain (L6). |
| Used Jev as a generative model? | **No.** Choice/Noul/Score only; there is no free-text channel. |
| Let Jev write grades or LEARNED? | **No.** The only table it writes is `jev_decision_receipts`; a failed call writes nothing. |
| Presented fake model results as real? | **No.** Fake transports are tagged `NON_INTERPRETABLE_PLUMBING_ONLY`; the canary was never executed; every live item is marked NOT_RUN. |
| Wrote shadow as production-enabled? | **No.** All 12 definitions are `shadow`; documented in every report. |
| Rewrote Assessment as a second system? | **No.** Additive tables and existing services. |
| Broke `exercise.v2`? | **No.** Contract file unchanged and its parse path is tested. |
| Overwrote user history, grades, knowledge trees or course files? | **No.** Production untouched; published CS3481/GE2324 trees not regenerated. |
| Any secret in Git, logs or reports? | **No.** The archived env hold file is gitignored; canary/ablation artifacts were checked for key tokens. |
| Unauthorized paid call? | **No.** 0 calls. |
| Unauthorized production change? | **No.** See §12. |

---

## 16. Resume Instructions

```
RESUME FROM:
Stage 6 (local verification) → Stage 7 (controlled release). Local implementation is done;
the open work is: finish the current-HEAD regression, then the credential-gated and
authorization-gated steps.

FIRST FILES TO READ:
  FINAL_COURSEMATE_JEV_DEEPSEEK_RELEASE_REPORT.md      (status of all 16 markers)
  MINIMAL_OWNER_ACTION_CARD.md                          (what only the owner can give)
  DSH_JEV_DEEPSEEK_EXECUTION_STATE.md                   (stage-by-stage state)
  docs/jev-deepseek/DECISION_CATALOG_AND_CALIBRATION.md (Jev modes/thresholds)
  LEARNING_AND_ASSESSMENT_STATE_SPEC.md                 (learning + assessment state model)
  JEV_ABLATION_AND_PRODUCTION_ACCEPTANCE.md             (§3.2 harness + baseline fidelity)
  DEEPSEEK_AND_JEV_RUNTIME_CONTRACTS.md                 (provider contracts + canary)

FIRST COMMANDS (read-only):
  git rev-parse HEAD; git status --short; git log --oneline -5
  services\rag-api\.venv\Scripts\python.exe -m pytest -q --ignore=work          (from services\rag-api)
  .\services\rag-api\.venv\Scripts\python.exe work\current-change\mig_probe.py
  .\services\rag-api\.venv\Scripts\python.exe work\current-change\verify_template_v2.py
  .\services\rag-api\.venv\Scripts\python.exe scripts\run_deepseek_canary.py --preflight-only
  .\services\rag-api\.venv\Scripts\python.exe scripts\verify_rollback_compat.py --release-tree <b05fd294 export>

NEXT CODE TASK (only if the owner wants local work before credentials):
  L5 — add a pedagogy case family to benchmarks/jev-ablation-cases.example.json and to
  app/evaluation/jev_ablation.py's loader so `pedagogy.next_method.v1` (armed by C/D) is
  actually observed; and decide L4 (whether citation support gets an arm).

NEXT TEST:
  services\rag-api\.venv\Scripts\python.exe -m pytest tests/test_jev_ablation.py \
      tests/test_jev_ablation_baselines.py tests/test_intent_commands.py -q
  then the full suite above.

DO NOT REDO:
  * the two pack probes (already permanent regressions, green);
  * the V1/V2 template pinning, the migration-count derivation, the 027 trigger fix;
  * the rollback-compat verifier/drift guard and its negative controls;
  * the DeepSeek provider migration, the Jev gateway/catalog/receipts, the five-question flow;
  * the ablation harness, the canary, the intent router (all committed at 6b85df7).

DO NOT TOUCH:
  production host / releases / the three production DBs / Netlify / DNS / Clerk / ECS;
  published CS3481 and GE2324 knowledge trees; existing chats, grades, bridges, template
  versions, learning evidence; any secret value (env files stay backend-side);
  the read-only implementation pack under
  D:\UserData\Downloads\CourseMate_Jev_DeepSeek_DSH_Implementation_Pack\
```

If a live credential arrives, the safe order is: `run_deepseek_canary.py --preflight-only` →
billable canary with an approved `--max-cost` → Jev stays `shadow` → ablation on labelled data →
only then consider promoting a definition to `on`.

---

## 17. Working-Tree Inventory at Pause

| Path | Kind |
|---|---|
| everything under `work/current-change/` | **generated evidence / temporary** (gitignored): logs, probes, commit-message files, JSON artifacts. Not committed, deliberately kept. |
| `DSH_JEV_DEEPSEEK_PAUSE_AND_HANDOFF_REPORT.md` (this file) | **finished change**, uncommitted by choice |
| `DSH_JEV_DEEPSEEK_EXECUTION_STATE.md` | **finished change**: pause section added; the edit is uncommitted (the previous version is in `6b85df7`) |
| all other tracked files | **finished change**, committed in `bdb1aa7` / `d4df8a2` / `3dd9d40` / `6b85df7` |

No in-progress change was left half-edited: the last full-suite run is the only thing that was
mid-flight, and it writes nothing but its log.
