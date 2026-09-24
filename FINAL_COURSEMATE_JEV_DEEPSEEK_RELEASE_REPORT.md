# FINAL_COURSEMATE_JEV_DEEPSEEK_RELEASE_REPORT

Next-version CourseMate implementation and release report, written on top of the **existing
production source line** (no rebuild, no reverted feature, no regenerated course tree).

> **Dated snapshot, 2026-09-24 (round 96).** This report describes the revision its §1 table names
> (`bdb1aa7` on top of `b05fd294`, RAG schema 28) and is kept as the record of that round. Three of its
> `NOT_RUN` items have since moved: live DeepSeek validation (now ten roles completed against the real
> provider, human review outstanding — `DEEPSEEK_LIVE_ACCEPTANCE.md`), live TypeSafe Jev (now run and
> `PARTIAL` — Choice/Noul verified, `Score` refused by design), and the A/B/C/D→A–E ablation (now run
> live, verdict `INTERPRETABLE` and unfavourable). The production release is still `NOT_RUN`.

## 0. Verdict first

**Delivered locally:** every part of the 13 requirements that can be executed without a
credential, a paid budget, or production authorization — implemented on the live source line,
with additive migrations, permanent regressions, and an independently re-run local verification
(§4).

**Not delivered, and not claimed:** everything that needs the owner — live DeepSeek validation,
live TypeSafe Jev, the A/B/C/D ablation, browser acceptance, and the production release itself
(§6). Nothing was deployed in this round, no production database was read or written, and no
status below is marked PASS on the strength of an SDK returning a typed object.

The single consolidated request is `MINIMAL_OWNER_ACTION_CARD.md`.

## 1. Identities and scope

| Symbol | Value |
|---|---|
| ARCHIVE_SHA (package-declared source) | `c309219ef7fbaa28ce203ef21e3fe02d3eee716f` |
| WORKTREE_SHA (implementation baseline = `HEAD`) | `b05fd29417bf306e3615e2cb6e9117ab85e333cb` |
| Implementation commit of this round | **`bdb1aa7`** — 92 files (38 modified, 54 added); the report and doc updates following it are a documentation-only commit |
| Branch | `fix/codex-dsh-audit-20260919` (not pushed; no remote write was authorized) |
| APPLICATION_SHA (package's reported run) | `4ef50642c0b2336e64c384752ea262901a32d81d` |
| PRODUCTION_SHA (live release) | `5ba6a3a` — **not re-verified this round** (no production access) |
| Schema after this round | RAG **28**, UI **13**, Agent **1** |
| Work tree | `D:\CourseMate_COMPLETE_ARCHIVE_20260918\01_SOURCE_REPOSITORY` (single tree used by all workstreams) |
| Change size | 38 tracked files modified (**+2795 / −280**), 54 files added (92 files in the commit) |

The implementation pack under
`D:\UserData\Downloads\CourseMate_Jev_DeepSeek_DSH_Implementation_Pack\CourseMate_Jev_DeepSeek_DSH_Plan\`
was read-only throughout: `DSH_MASTER_IMPLEMENTATION_PROMPT.md`,
`SOURCE_AUDIT_AND_FINAL_PLAN.md`, `SOURCE_EVIDENCE.md/json` (S01–S21),
`ISOLATED_SOURCE_PROBES.json`, `JEV_DECISION_CATALOG.json`, `TEMPLATE_V2_MANIFEST.json`,
`reproduce_source_findings.py`, `template_text_v2/*.txt`.

## 2. Status markers

Legend — **PASS** = a real check was executed in this round and is reproducible from the tree;
**PASS_LOCAL** = the deterministic/contract behaviour passes, but the third-party live gate was not
executed (fake transport or deterministic provider only); **NOT_RUN** = never executed;
**BLOCKED** = cannot start without owner authorization.

| # | Marker | Status | Evidence (executed this round) |
|---|---|---|---|
| 1 | DETERMINISTIC_FIXES | **PASS** | Both pack probes converted to permanent regressions (`tests/test_jev_deepseek_gap_regressions.py`, 4 passed); learning-start fact + global retrieval fusion implemented; full suite green (§4) |
| 2 | DEEPSEEK_TEXT | **NOT_RUN** | Five roles migrated to the DeepSeek contract with host-spy tests proving zero Qwen egress; no credential/budget → no live text call was made |
| 3 | DEEPSEEK_VISION | **NOT_RUN** | Native image path + payload contract tested locally (`test_deepseek_contract.py`, `test_problem_runtime.py`); no live image call |
| 4 | DEEPSEEK_AGENT | **NOT_RUN** | agent-api client/base-URL guard migrated, 72/72 vitest, build exit 0; no live tool call |
| 5 | PROMPT_V2_REGISTRY | **PASS** | 16/16 V2 body hashes equal `TEMPLATE_V2_MANIFEST.json`; versioned registry with V1 retained; `test_jev_deepseek_template_v2.py` 21 passed, `test_codex_template_integrity.py` 22 passed |
| 6 | JEV_GATEWAY | **PASS_LOCAL** | `app/jev/` gateway in off/shadow/on with injectable transport, bounds, typed errors, receipts (migration 028), cache + invalidation; 23 Jev tests passed. All 12 definitions are **shadow**; live TypeSafe NOT_RUN (`SdkTransport` raises `JEV_NOT_CONFIGURED`) |
| 7 | JEV_RERANK | **PASS_LOCAL** | Reorder-only rerank over server-supplied ids wired into `V3DomainAdapter._retrieve`; exact targets protected; unit + wiring tests green; live TypeSafe NOT_RUN |
| 8 | JEV_CONTEXT_AND_INTENT | **PASS_LOCAL** | Context keep/drop + ambiguous-intent helpers implemented and tested with the fake transport; typed-output failure degrades to the deterministic path; live NOT_RUN |
| 9 | JEV_COVERAGE_REVIEW | **PASS_LOCAL** | Item-support provenance signal wired; coverage semantics unchanged (LEARNED still needs accepted evidence); live NOT_RUN, thresholds UNSET |
| 10 | JEV_ASSESSMENT_REVIEW | **PASS_LOCAL** | Criterion-review + template/exercise-quality helpers implemented and tested; never authoritative over grades; live NOT_RUN |
| 11 | LEARNING_PROGRESS | **PASS** | `课程知识点` titles, NOT_STARTED/LEARNING/LEARNED, first real start recorded idempotently (migration 026 + `_begin_learning`), LEARNED gated on all REQUIRED coverage; legacy regression suites updated and green |
| 12 | FIVE_QUESTION_ASSESSMENT | **PASS_LOCAL** | Pool preparation (migration 027, idempotent/resumable/cancellable, no seed, `MODEL_ONLY` still excluded), 5-at-once fullscreen workspace, unified composer, drafts, raw-score display, NEEDS_REVIEW never overwrites the last valid result, per-step 详解; local tests + 64 web tests green. Live generation NOT_RUN |
| 13 | LOCAL_REGRESSION | **PASS** | §4: backend **948 passed / 0 failed** (exit 0) on the delivered revision `6b85df7`, agent 72/72, web 64/64, both builds exit 0, schema probe clean, V2 hashes 16/16 |
| 14 | LIVE_MODEL_VALIDATION | **NOT_RUN** | Blocked on the owner's DeepSeek key/budget (action card §1) |
| 15 | PRODUCTION_DEPLOYMENT | **BLOCKED** | No production authorization in this session; nothing deployed, no DB touched |
| 16 | PRODUCTION_ACCEPTANCE | **BLOCKED** | Requires an authorized release plus a real login for the browser journey (action card §3) |

No marker is PASS because a provider, SDK or health endpoint returned successfully.

Ready but unexecuted, so a credential is the only thing between this build and real evidence:
the DeepSeek canary (`scripts/run_deepseek_canary.py`, ten roles, ceiling printed before any call)
and the Jev A/B/C/D ablation harness (`scripts/run_jev_ablation.py`, four arms, twelve metrics,
fail-closed against a placeholder baseline). Neither has been run against a live provider.

## 3. Requirement-by-requirement mapping

| # | Requirement | What was implemented | Status |
|---|---|---|---|
| 1 | All new generative AI on the runtime-verified latest DeepSeek stable model; no Qwen production model, no auto-fallback; embeddings stay an independent contract | Contract read live on 2026-09-21: `deepseek-flash` = DeepSeek-V4.1-Flash, base `https://api.deepseek.com`, `/chat/completions` + `/responses`, native thinking disabled, structured output only via Responses `text.format`, images via `detail`. Five roles migrated (`cm_update/{config,provider}.py`, `learning/provider.py`, `coverage_review.py`, `rag/answers.py`, agent-api client). `validate_deepseek_base_url` rejects non-DeepSeek hosts; the Model Studio validator is retained **only** for the historical read-only path. No Qwen-only field remains on any live path. Embeddings: Alibaba `text-embedding-v4` unchanged, no dimension change, no re-index | Wiring PASS_LOCAL, live NOT_RUN |
| 2 | TypeSafe Jev as a backend semantic-judgment layer with safe degradation | `app/jev/` (catalog of 12 definitions, gateway, `SemanticDecisionService`, receipt store, typed errors) covering retrieval rerank, evidence support, context keep/drop, ambiguous intent, next teaching strategy, REQUIRED coverage support, assessment criterion review, template classification, exercise prototype/corpus quality, prerequisite candidates. Every call degrades to the existing deterministic behaviour on timeout, typed-error, budget exhaustion or mode `off` | PASS_LOCAL (all shadow) |
| 3 | Knowledge-node learning state | Both tree titles are exactly `课程知识点`; NOT_STARTED → LEARNING → LEARNED; the first real teaching start is written as an idempotent fact (migration `026_learning_start_events.sql`, written from the accepted run, with a legacy backfill that requires a real artifact); LEARNED only when all REQUIRED coverage is validated | PASS |
| 4 | Full `开始测评` flow | Three-line node panel (学习进度 / 测评结果 with raw-score fallback / 开始测评), COMPOSITE nodes ask for the child node first, fullscreen workspace with all five questions at once, one fixed bottom composer (paste/upload/draft/submit/confirm-unanswered), drafts are not submissions, existing AssessmentService/blueprint/`grade_snapshots` reused, real pool preparation replaces the permanent 409 with no seed and no `MODEL_ONLY` relabelling, raw score shown as e.g. `78 / 100 · AI 自测` (never 未测评), a needs-review outcome keeps the last valid result, per-step 详解 reuses the existing explanation component | PASS_LOCAL |
| 5 | Merge official/private/workspace candidates → global ranking → Jev rerank; deterministic exact locator priority; real chapter evidence packs | `app/learning/retrieval_orchestrator.py`: RRF across authorized scopes (rank constant 60), per-scope recall cap, exact-target protection, boundary-aware budgeting, sequential S-ids assigned only at projection; structured locator path via `parse_query_reference` + `retrieve_structured`; Jev rerank reorders only | PASS |
| 6 | Fixed learning anchors vs filterable history; permanent history never deleted; deterministic handling of explicit commands | Anchors stay fixed while history is filterable; history rows are never deleted (no delete path added in any migration); explicit commands are now answered by a deterministic, I/O-free router (`app/learning/intent_commands.py`) **before** any semantic call — it fires only when the message *is* the command ("继续讲一下 K-means" stays semantic), and a fixed anchor is never offered to Jev for dropping | PASS |
| 7 | Replace with the 16 V2 prompts; keep 题目/详解 prompts and the exercise.v2 hidden private answers | 16 V2 files imported (14 professional + OTHER + EXERCISE), manifest hashes verified 16/16, versioned registry (`registry("V2")` default, V1 loadable), `problem_prompt()`/`explanation_prompt()`/`exercise_runtime_contract()` untouched, first round shows only the question while the private reference answer is still generated through `exercise.v2` | PASS |
| 8 | Apply selected Jev ecosystem patterns; no 20 production dependencies | Only one third-party package is involved at all: `typesafe-sdk` **0.7.0** (MIT), and it is deliberately **not** a default dependency — the live transport imports it lazily. No ecosystem bulk import. Selection and rejection reasoning in `JEV_APPLICATION_DECISION_MATRIX.md` and `docs/jev-deepseek/JEV_SKILL_DECISIONS.md` | PASS |
| 9 | Unified JevGateway → SemanticDecisionService for retrieval/context/intent/pedagogy/coverage/assessment/classification; versioned questions; probabilities never grades or permissions | One gateway façade, one decision service, receipts persisted (migration 028) with scope + invalidation, question revisions versioned (`027`), `probability_is_grade=false`, thresholds UNSET until calibrated; Jev can only select server-supplied ids and never writes state, grades, LEARNED, permissions or budgets | PASS_LOCAL |
| 10 | A/B/C/D ablation with the listed metrics | **Result NOT_RUN**, but the harness now exists and runs offline with zero credentials: `scripts/run_jev_ablation.py --arm all --transport deterministic_fake` executes the four arms through the real wired paths and computes the twelve metrics. It is fail-closed against exactly the ways a comparison could flatter Jev: a fake transport can never be interpretable, a live run needs a labelled dataset, and a **placeholder baseline** (abstention, or the service's `OTHER` default) makes the verdict `NOT_INTERPRETABLE` until the real production baselines are injected. No ablation number is claimed as a quality result, and **no claim of improved teaching quality is made** | NOT_RUN (harness ready) |
| 11 | Latest official SDK/API docs; keys backend-only; batch cost ceiling before real tests | DeepSeek and TypeSafe contracts verified against current official docs (recorded in `DEEPSEEK_AND_JEV_RUNTIME_CONTRACTS.md`); keys are read only from backend config and never logged or sent to the browser; the batch cost ceiling must be fixed before any live batch (blank fields in the action card) | PASS (wiring), live NOT_RUN |
| 12 | Isolated-copy migration verification; never overwrite the production DB; never regenerate the published CS3481/GE2324 trees; never delete old chat/grades/bridge/template versions/evidence | Migrations are additive and were exercised only on isolated copies; the rehearsal now covers the governance objects of migrations 019–021 **and** 026–028; the four table rebuilds in 027 copy rows before the rename (verified `INSERT INTO …_new SELECT`); V1 templates remain on disk; published course trees were not regenerated; no old chat, grade, bridge, template version or evidence row is deleted anywhere. **Rollback path verified, not assumed** (§4.4): the previous release runs against the migrated Schema-28 database with `integrity=ok`, no column drift and no narrowed CHECK enum, and both the test guard and the verifier were negative-controlled | PASS |
| 13 | Full pipeline, then controlled release; without authorization deliver all local work plus one minimal action card; never fake acceptance with a fake provider or `health=200` | All locally executable work delivered; release steps prepared but **not executed**; one consolidated action card; no fake provider, no shadow output presented as a live result, no health check presented as acceptance | PASS for local delivery; deployment BLOCKED |

## 4. Verification log (re-run by the orchestrator, not taken from agent reports)

### 4.1 Full backend suite

| Run | Result |
|---|---|
| First full run on the pre-fix tree | **789 passed, 17 failed** in 1262.63s (exit 1) |
| Authoritative run on the frozen post-fix tree | **808 passed, 0 failed** in 2074.86s (34:34), exit code 0, 2 pre-existing warnings |
| Authoritative run on the delivered revision `6b85df7` (after the round-4 additions) | **948 passed, 0 failed** in 1312.19s (21:52), exit code 0, 2 pre-existing warnings; 808 + 140 new tests = 948, log `work/current-change/full_run_round4.log` |

The count is self-consistent: 789 + 17 = 806 tests were collected before the fixes, and this run
collected 808 — the two additions being the new guards described below.

Operational note, recorded rather than hidden: one earlier attempt at the post-fix run stalled with
the pytest process idle (0.0s CPU over 60s) while holding a loopback listening socket, so it was
abandoned and re-run verbosely with `-o faulthandler_timeout=240`. The re-run completed the whole
suite green, including the socket-serving test, so this is recorded as a local-environment
observation (the machine was concurrently serving this DSH session), not as a reproducible product
failure — no test failed in either attempt.

All 17 failures were two contained causes, both fixed without weakening any guarantee:

1. **`test_codex_template_integrity.py` (16 failures).** The file pins the V1 Word-source body
   hashes but called `template_body()` / `exercise_prompt()` without a version, so it followed the
   new V2 default. Fixed by passing `V1` explicitly at every lookup; a new
   `test_both_template_versions_are_served_side_by_side` asserts V1 and V2 both resolve and return
   different bodies, so the pin cannot silently start comparing V2 against V1 hashes. The V2 files
   are pinned separately against the manifest, and the V1 files are unchanged on disk.
2. **`test_v3_migration_rehearsal.py` (1 failure).** The test hardcoded `list(range(1, 26))` while
   migrations 026–028 now exist. Fixed by deriving the ceiling from
   `db.LATEST_V3_SCHEMA_VERSION`, which is what the rehearsal script itself already checks — the
   test now also asserts `max(versions) >= 26` so the new migrations cannot silently stop applying.

### 4.2 Suites and gates executed in this round

| Gate | Command | Result |
|---|---|---|
| Gap regressions (converted pack probes) | `pytest tests/test_jev_deepseek_gap_regressions.py -q` | 4 passed |
| Retrieval fusion unit | `pytest tests/test_retrieval_fusion_unit.py -q` | 7 passed |
| Jev catalog/gateway/service/wiring | `pytest tests/test_jev_{catalog,gateway,service,wiring}.py -q` | 23 passed |
| V2 template registry | `pytest tests/test_jev_deepseek_template_v2.py -q` | 21 passed |
| V1 template integrity (fixed) | `pytest tests/test_codex_template_integrity.py -q` | 22 passed |
| Migration rehearsal + fresh-init regression (extended) | `pytest tests/test_v3_migration_rehearsal.py -q` | 4 passed |
| Assessment preparation contract | `pytest tests/test_assessment_preparation_contract.py -q` | 10 passed |
| DeepSeek contract + provider roles | `pytest tests/test_deepseek_contract.py tests/test_deepseek_provider_roles.py -q` | 53 passed |
| DeepSeek egress/spy guard | included in the provider-role suite | 4 passed (zero Qwen egress) |
| Coverage + learning closure | `pytest tests/test_ui_extension_coverage_submission.py tests/test_ui_extension_learning_closure.py -q` | 49 passed |
| Registry / publication / integration batch | targeted batch | 42 passed |
| cmui feature tests | targeted batch | 13 passed |
| Web app | `pnpm --filter @coursemate/web run build` + `test` | build exit 0; **17 files / 64 tests passed** |
| Agent API | `pnpm --filter @coursemate/agent-api run build` + `test` | build exit 0; **10 files / 72 tests passed** |
| Schema probe (init + replay, isolated copy) | `python work/current-change/mig_probe.py` | `integrity=ok`, `fk_violations=0`, `max_migration=28`, `leftover_old_tables=[]`, 17 assessment triggers present |
| Rollback compatibility (previous release vs migrated DB) | `python scripts/verify_rollback_compat.py --release-tree <b05fd294 export>` | `ROLLBACK_SAFE_WITH_MIGRATED_DB` (exit 0): old code opens Schema 28, `integrity=ok`, `fk_violations=0`, no missing/retyped column, no narrowed enum |
| Schema drift guard | `pytest tests/test_schema_rollback_compat.py -q` | 5 passed (negative-controlled: narrowing an enum makes it fail) |
| Explicit-command router | `pytest tests/test_intent_commands.py -q` | 70 passed (Chinese + English commands, politeness tolerance, semantic messages deliberately unrouted) |
| A/B/C/D ablation harness (offline) | `python scripts/run_jev_ablation.py --arm all --transport deterministic_fake --out <fresh path>` | exit 0; 4 arms, 12 metrics, `verdict=NOT_INTERPRETABLE`, `interpretation=NON_INTERPRETABLE_PLUMBING_ONLY`, no key token in the artifact |
| Ablation harness + baseline fidelity | `pytest tests/test_jev_ablation.py tests/test_jev_ablation_baselines.py -q` | 40 passed (raw harness 30 + baseline/anchor guards 10) |
| DeepSeek live canary (preflight, no key) | `python scripts/run_deepseek_canary.py --preflight-only` | exit 0: 10 provider calls, 2 on `/chat/completions` + 8 on `/responses`, input-token ceiling 46665, no monetary figure invented without explicit prices |
| DeepSeek live canary (refusal path) | same with `--allow-billable`, no key | exit 2, `Missing credential environment variable: DEEPSEEK_API_KEY`, before any client is built |
| DeepSeek canary contract | `pytest tests/test_deepseek_canary.py -q` | 25 passed |
| V2 template hashes | `python work/current-change/verify_template_v2.py` | 16/16 verified, no problems |

### 4.3 Migration 027 — the defect found and fixed inside this round

The first cut of `027_assessment_preparation_reference.sql` rebuilt four tables via
`<name>_new` + `DROP` + `RENAME`. SQLite rewrites **every** trigger that references a renamed
table, so ten triggers were silently retargeted at `…_new` and the next migration touching them
failed with `no such table: main.assessment_question_revisions_old` — which broke every
database-backed test. The fix drops all ten affected triggers (including the four defined on
*other* tables) before any table work, rebuilds the tables, recreates the ten triggers verbatim,
and runs with `legacy_alter_table=ON`.

Two permanent guards now exist so this cannot regress silently:

* `test_fresh_initialize_applies_every_migration_without_rebuild_artifacts` — every declared
  migration applies, replay is idempotent, `integrity_check=ok`, `foreign_key_check` empty, **no
  `*_new`/`*_old` leftovers**, all governance objects present, and the ten rebuild-sensitive
  triggers all exist.
* the rehearsal's governance set was extended to migrations **026–028** (with commented-out DDL
  ignored and transient `_new`/`_old` names excluded), so a lost trigger or table now fails the
  rehearsal itself.

### 4.4 Rollback compatibility: the previous release against the migrated database

Migration 027 rebuilds four tables, which is the one migration shape that can break an
already-deployed release. Requirement 12's "保数据回滚路径" was therefore verified rather than
asserted:

* Method — `scripts/verify_rollback_compat.py` exports the previous release
  (`git archive b05fd294`), builds a fully migrated database with the current code, then runs the
  **previous release's own code** against that file in a subprocess, and compares the release's
  *own* schema (captured from a database the release creates itself) with the migrated schema. The
  first version of this tool compared the release's view of the migrated file with that same file,
  which is circular and could only ever report "safe"; it was rewritten before the result was used.
* Result — verdict `ROLLBACK_SAFE_WITH_MIGRATED_DB`, exit 0: the old code imports, opens the
  Schema-28 database and reports `integrity=ok` / `fk_violations=0`; the release's own schema is
  Schema 26 while it sees 28; **no table missing, no column missing, no column retyped, no CHECK
  enum narrowed**; the assessment pool filter string is identical, so old and new code select the
  same question pool. *(Round 42: this clause was **unmeasured** when written — the tool's
  `pool_filter_unchanged` field was read from the current tree only and could not have reported a
  difference (ledger B-41); it now compares both trees. Re-run with the corrected tool, against a
  database built by the current code — schema 30 rather than 28, the same comparison shape — for
  `b05fd294` **and** for `4ef5064`: both give `pool_filter_verdict: UNCHANGED`, detail
  "byte-identical predicate", both extracted predicates recorded and `rollback_concerns` empty,
  verdict `ROLLBACK_SAFE_WITH_MIGRATED_DB`, exit 0
  (`work/current-change/rollback-compat-{b05fd294,4ef5064}-r42.json`).)*
* Permanent guard — `tests/test_schema_rollback_compat.py` (5 passed) freezes the pre-027 column,
  table and enum snapshot, so a later migration that drops a column or narrows an enum fails the
  suite.
* Negative controls (both guards were made to fail on purpose): deleting `HUMAN_REVIEWED` from the
  `verification_method` CHECK made the test fail with
  `values no longer accepted ['HUMAN_REVIEWED']` and made the verifier return
  `ROLLBACK_REQUIRES_DB_RESTORE` (exit 3). The migration file was then restored and the tree checked
  clean.

A related clarification belongs with this evidence: prepared questions are stored with
`validation_status='VALIDATED'` **and** an honest `verification_method` (`DETERMINISTIC` or
`AI_REVIEWED`). The two columns are separate axes — pool admission versus verification strength and
grading channel — and `MODEL_ONLY` is never written or relabelled. See
`LEARNING_AND_ASSESSMENT_STATE_SPEC.md` §2.5.1.

## 5. What is explicitly NOT verified

* **Live DeepSeek** text / vision / structured / tool-replay / pricing: NOT_RUN (no key, no budget).
* **Live TypeSafe Jev**: NOT_RUN; all 12 definitions remain `shadow`, thresholds UNSET.
* **A/B/C/D ablation and every listed metric** (Recall@K, MRR, locator accuracy, citation support,
  coverage FP/FN, criterion error, image transcription, latency, per-provider cost, failure rate):
  NOT_RUN. The 200 judgements / 40 trajectories / 30 image cases are a *plan*, not results.
* **Real browser journeys and production acceptance**: NOT_RUN / BLOCKED.
* **Visual render validation of the V2 documents**: NOT_RUN (the manifest itself declares
  `visual_render_validation_performed_this_turn=false`).

Therefore the following statements may **not** be made about this round — and are not made:
that teaching quality improved; that Jev improved marks, coverage or grading accuracy; that the
model identity was observed at runtime beyond the configured alias; that acceptance passed; that a
successful typed SDK response proves any of the above.

What *may* be stated: the deterministic defects are fixed and pinned by regressions; the provider
boundary is DeepSeek-only with zero Qwen egress proven by spies; the Jev layer exists in shadow
with typed output, safe degradation and receipts; the V2 prompt set is byte-verified; the schema is
additive and verified on isolated copies; and the local suite is green.

## 6. Release procedure — prepared, not executed

Nothing below has been run. It requires the owner's authorization (action card §3).

1. Back up all three live databases (`/srv/coursemate/{rag,agent,data}`) into
   `/srv/coursemate/backups/<timestamp>/` and verify each backup restores.
2. Restore the backups into an isolated directory and apply migrations 026–028 **there**, checking
   `integrity_check`, `foreign_key_check`, trigger set, row counts and the rehearsal invariants.
3. Build an immutable release from the committed SHA and place it under
   `/home/admin/coursemate-v3-releases/`; publish the web artifact through Netlify.
4. Enable the canary first: `scripts/run_deepseek_canary.py --preflight-only` (prints the ten-call
   plan and the ceiling), then the same command with `--allow-billable --max-cost <approved>` and
   explicit per-million prices; then Jev in `shadow`, and compare shadow decisions against the
   deterministic path (`scripts/run_jev_ablation.py`) before switching any definition to `on`.
5. Run the real signed-in browser journey (login by the owner — no captcha bypass), then record
   `PRODUCTION_ACCEPTANCE` from the observed result, including failures.
6. Rollback: re-point to the previous release directory and restore the pre-migration database
   backups; migrations are additive, so no down-migration is needed for the documented path.

## 7. Deliverables

| File | Contents |
|---|---|
| `FINAL_COURSEMATE_JEV_DEEPSEEK_RELEASE_REPORT.md` | This report: identities, 16 markers, requirement mapping, verification log, explicit non-verified list, release procedure |
| `JEV_APPLICATION_DECISION_MATRIX.md` | The 12 Jev definitions mapped to the requested judgments: call site, input contract, output use, authority limit, default mode, degradation, and the rejected ecosystem patterns |
| `DEEPSEEK_AND_JEV_RUNTIME_CONTRACTS.md` | Live-verified DeepSeek and TypeSafe contracts: endpoints, request/response shapes, capability matrix, key handling, cost policy |
| `LEARNING_AND_ASSESSMENT_STATE_SPEC.md` | Authoritative state model: NOT_STARTED/LEARNING/LEARNED, start-fact precedence (UI_RUN/BACKFILL/LEGACY_JOURNEY), coverage sources, and the assessment result/session rules |
| `JEV_ABLATION_AND_PRODUCTION_ACCEPTANCE.md` | A/B/C/D arms, metric definitions, sample sizes, cost ceiling, acceptance gates and the honesty rules for reporting |
| `DSH_JEV_DEEPSEEK_EXECUTION_STATE.md` | Stage-by-stage execution state and resumption instructions |
| `MINIMAL_OWNER_ACTION_CARD.md` | The single consolidated owner request (credentials, budgets, production authorization) |
| `docs/jev-deepseek/*.md` | Supporting notes: source baseline and gaps, learning state and evidence, retrieval and context, template V2 migration, provider capability matrix, decision catalog and calibration, Jev skill decisions |
| `scripts/run_deepseek_canary.py` | Fail-closed DeepSeek live canary: ten roles, native fields only, ceiling printed before any call, one call per role, no retry |
| `scripts/run_jev_ablation.py` | A/B/C/D ablation CLI: offline plumbing by default, twelve metrics, refuses an interpretable verdict from a fake transport, an unlabelled dataset or a placeholder baseline |
| `scripts/verify_rollback_compat.py` | Runs the previous release against the migrated database and returns `ROLLBACK_SAFE_WITH_MIGRATED_DB` or `ROLLBACK_REQUIRES_DB_RESTORE` |

## 8. Resuming in a later round

Start from `DSH_JEV_DEEPSEEK_EXECUTION_STATE.md` §"Resume instructions": verify the tree with
`work/current-change/mig_probe.py` and `work/current-change/verify_template_v2.py`, run the
targeted suites, then the full suite; only after the owner supplies credentials run the live
canaries (DeepSeek first, Jev in `shadow`), and only with explicit authorization perform the
release in §6.
