# DSH_JEV_DEEPSEEK_EXECUTION_STATE

Stage-by-stage state of this implementation round in the real work tree
`D:\CourseMate_COMPLETE_ARCHIVE_20260918\01_SOURCE_REPOSITORY` (branch
`fix/codex-dsh-audit-20260919`). Written so a later round can resume without
re-initialising anything.

## Identity

| Symbol | Value |
|---|---|
| ARCHIVE_SHA (package-declared source) | `c309219ef7fbaa28ce203ef21e3fe02d3eee716f` |
| WORKTREE_SHA (implementation baseline) | `b05fd29417bf306e3615e2cb6e9117ab85e333cb` + this round's uncommitted work |
| APPLICATION_SHA (package's reported run) | `4ef50642c0b2336e64c384752ea262901a32d81d` |
| PRODUCTION_SHA (live release, not re-verified this round) | `5ba6a3a` |
| Schema after this round | RAG **28**, UI **13**, Agent **1** |

> **Historical record (rounds 1–30).** The identities above are the round-30 snapshot, not the current
> tree: HEAD is now `2fd532b`, the RAG schema is **30**, and rounds 31–42 are recorded in
> `docs/recovery/CURRENT_BLOCKER_LEDGER.md` and `CHATGPT_REVIEW_CURRENT_STATUS_AND_BLOCKERS.md`, which
> are the current authority (this file's stage sections describe the round they were written in). The
> per-round sections resume at "Round 27" and end at "Round 30"; the resume instructions at the end
> still apply.

## Stage 0 — source reality and input validation · DONE

* Read the whole pack: master prompt, audit plan, `SOURCE_EVIDENCE.md` (S01–S21), both probes,
  the Jev catalog, the V2 template manifest, and `reproduce_source_findings.py`.
* Cross-check: every quoted code window still matches the work tree, same identifiers and line
  numbers → **no stale quotes**. `PACKAGE_MANIFEST.md` exists only in the delivery package, not in
  the source tree.
* **Both pack probes converted into permanent regressions** in
  `services/rag-api/tests/test_jev_deepseek_gap_regressions.py`; they were executed on the
  pre-fix tree (2 failing, 2 negative controls passing) and are green after the fixes.
* Four source identities separated (table above); the archive snapshot was never used to
  overwrite the live source line, and the earlier merged work is preserved
  (`ef4d02d…` is an ancestor of the baseline).

## Stage 1 — deterministic fixes and shared service extraction · DONE

* **Learning start fact**: migration `026_learning_start_events.sql` (+ legacy backfill with real
  artifacts only), written from the accepted run in `_begin_learning`, projected by
  `_learning_start_fact`; `_atomic_learning` now returns `started/started_at/start_source` and
  reports started+zero-coverage as `LEARNING`. Coveraged semantics unchanged (LEARNED still
  requires accepted evidence).
* **Global retrieval fusion**: `app/learning/retrieval_orchestrator.py` (RRF across authorized
  scopes, per-scope recall cap, exact-target protection, boundary-aware budgeting) wired into
  `V3DomainAdapter._retrieve`, reusing the legacy query rewrite + structured locator.
* **Assessment projection**: newest-valid vs newest-independent vs active session separated;
  `raw_score`/`assessment_display` exposed so a raw score never reads as 未测评.
* Tests: `test_jev_deepseek_gap_regressions.py` (4), `test_retrieval_fusion_unit.py` (7),
  plus updated legacy expectations in the coverage/closure suites.

## Stage 2 — DeepSeek and templates · DONE (live NOT_RUN)

* Verified contract read live on 2026-09-21: `deepseek-flash` = DeepSeek-V4.1-Flash, base
  `https://api.deepseek.com`, `/chat/completions` + `/responses`, native vision, 1M context.
* Five roles migrated with explicit per-role protocol and **no Qwen fallback**; Model Studio
  validation retained for the historical path only. Host-spy tests prove zero Qwen egress.
* 16 V2 templates imported with manifest-hash verification and a versioned registry; 题目/详解 and
  the `exercise.v2` contract untouched.
* Live text/vision/structured/tool-replay/pricing: **NOT_RUN** (no credential/budget).

## Stage 3 — Jev foundation, retrieval and memory · DONE in shadow (live NOT_RUN)

* `app/jev/` gateway (off/shadow/on, injectable transport, bounds, typed errors, receipts,
  cache with scope + invalidation) + the 12 catalog definitions + migration `028`.
* Wired: retrieval re-rank (reorder-only, exact targets protected) and coverage item-support
  (provenance signal). Intent/context/pedagogy/assessment helpers implemented and tested.
* All 12 decisions **shadow**; thresholds UNSET; live TypeSafe **NOT_RUN**.

## Stage 4 — five-question service extension · DONE (live generation NOT_RUN)

* Migration `027`: widened `verification_method` enum (`AI_REVIEWED` diagnostic channel),
  six new tables (preparation jobs, reference solutions, drafts, submission revisions, grading
  receipts, explanation contexts), and the two model-call ledgers extended with
  reference/preparation/explanation roles.
* Pool preparation is idempotent/cancellable/resumable and replaces the permanent 409; two
  explicit channels (deterministic/validated vs AI_REVIEWED diagnostic); `MODEL_ONLY` still
  excluded; nothing seeded or relabelled.
* Unified answer mapping to the five stable blueprint ids with confirmation instead of guessing;
  drafts are not submissions; grading failure keeps the previous valid result and marks
  NEEDS_REVIEW; reference solutions are compiled before seeing student answers and exposed only
  after submit.

## Stage 5 — fullscreen UI and user loop · DONE (visual acceptance NOT_RUN)

* Both tree titles are exactly 课程知识点; the node panel has three lines (学习进度 / 测评结果 with
  raw-score fallback / 开始测评); COMPOSITE nodes show a child-node selector first.
* Fullscreen `AssessmentWorkspace`: all five questions at once, fixed unified composer
  (paste/upload/draft/submit/confirm-unanswered), post-grading per-question answers, marks,
  per-criterion reasons, step-by-step reference solution and 详解 windows reusing the existing
  explanation component with an assessment-keyed context resolver.

## Stage 6 — full-scale verification · DONE (local); live/browser gates NOT_RUN

| Check | State |
|---|---|
| Targeted suites (per workstream) | green (see the final report table) |
| Full backend regression | **948 passed, 0 failed** in 1312.19s (exit 0) on the delivered revision `6b85df7` — 808 before the round-4 additions plus 140 new tests; the two clusters behind the earlier `789 passed / 17 failed` run were fixed (V1 template pin; migration-count ceiling) and two new guards added. It completed after the owner's pause, on the frozen commit, with no file change during the run — log `work/current-change/full_run_round4.log` |
| Web build + vitest | **exit 0**, 17 files / 64 tests passed |
| Agent build + vitest | **exit 0**, 10 files / 72 tests passed |
| Migration init + replay probe | `integrity=ok`, `fk_violations=0`, max migration 28, no `*_old`/`*_new` leftovers, all 17 assessment triggers present |
| Migration rehearsal governance coverage | extended to migrations 026–028; a fresh-init regression now pins the ten rebuild-sensitive triggers from 027 |
| Rollback compatibility | `ROLLBACK_SAFE_WITH_MIGRATED_DB` (previous release runs against Schema 28); pre-027 column/table/enum snapshot frozen as a test, both negative-controlled |
| Round-4 additions (router, ablation harness, canary, rollback guard) | **140 passed**; both CLIs exercised offline (ablation exit 0 / verdict NOT_INTERPRETABLE, canary preflight exit 0, canary refusal exit 2) |
| Real browser journeys | **NOT_RUN** (needs production/live authorization and a real login) |
| DeepSeek/Jev live canary | **NOT_RUN** (credentials/budget); the runner exists and is fail-closed |

### Stage 6b — owner-requested pause (2026-09-22)

The owner paused the round to freeze state. Feature work stopped immediately; a read-only inventory
was taken and the full handover report is
**`DSH_JEV_DEEPSEEK_PAUSE_AND_HANDOFF_REPORT.md`**. At pause: `HEAD=6b85df7`, branch
`fix/codex-dsh-audit-20260919`, worktree clean apart from that report, 5 commits unpushed,
`PRODUCTION_TOUCHED = no`, model/Jev/embedding/Clerk calls = 0, spend = 0. The only thing mid-flight
was the read-only full regression, left to finish naturally.

## Stage 7 — controlled release · NOT STARTED (blocked, correctly)

No production authorization in this session, so nothing was deployed, no production database was
touched, and no DNS/Clerk/Netlify change was made. The single consolidated request is
`MINIMAL_OWNER_ACTION_CARD.md`. Commit `6b85df7` is the candidate revision to release; `scripts/run_deepseek_canary.py`
and `scripts/run_jev_ablation.py` are the two commands a credential would unlock.

## Round 6 — Laya direction stopped, Jev path restored (2026-09-22)

The owner tried a self-hosted Laya semantic layer, then stopped it ("阿里云当前可用服务器性能不适合部署
Laya") and restored TypeSafe Jev. Commit `44e9e5d` archives the Laya-only work under
`archive/laya-superseded-20260922/`, reverts the Laya-only edits (including the retired `SdkTransport`,
which is live again) and keeps the model-agnostic measurement assets for Jev. The archive README lists
exactly what was archived and why; every archived document carries a `SUPERSEDED_BY_JEV_DECISION`
header and is **not** a production source of truth.

**Final architecture (fixed):** DeepSeek → generation, vision, plan/work, problems, explanations,
grading feedback, Agent generation. TypeSafe Jev → fast typed semantic decisions
(choice / score / noul). CourseMate backend → permissions, state machine, retrieval, transactions,
mark scoring, learning state, final writes. Jev is not a generator; DeepSeek does not replace Jev's
lightweight judgments; Qwen is never an automatic production fallback.

`LAYA_PRODUCTION_RESOURCE_CREATED = false` — no ECS instance, node, port, DNS entry or billable
resource was ever created for Laya; no Laya service is running. The only leftovers are a CPU-only venv
and a 654 MB model snapshot outside the repository (documented in the archive README).

### Production baseline — re-verified read-only in round 6 (not inherited from the pause report)

| Item | Verified value |
|---|---|
| Frontend | `https://qqttai.com` on Netlify project `coursemate-ai-qqtt` (GitHub-linked to `main`), current deploy `6ab02278b7fae664934df25d`, live bundle `/assets/ui-UCeSo0VK.js`; the Netlify CLI on this machine is authenticated (Qiu Tian / team `Q_WCTJ`) |
| Backend hosts | `rag.qqttai.com` and `agent.qqttai.com` → `47.114.34.175` (instance `i-bp1f0vqhds2341pdqqiy`, `cn-hangzhou-k`, private `172.20.170.40`, **2 vCPU / 3 GiB**) |
| Live release | `/srv/coursemate/current` → `/srv/coursemate/releases/4ef5064` (the pause report's `5ba6a3a` was stale) |
| Services | `coursemate-rag.service` (uvicorn on `127.0.0.1:28000`), `coursemate-agent.service` (node on `127.0.0.1:28001`), nginx |
| Live RAG database | `/srv/coursemate/data/releases/20260919T202006Z/rag.sqlite3` → **schema 25**, migrations 1–25, `integrity_check=ok`, 76 tables |
| Live data volumes | courses 20 (18 private, **2 published**), documents 67, chunks 1 963, learning_workspaces 16; UI store `…/ui-extension/ui.sqlite3` (3.3 MB, actively written); uploads 119 MB |
| Production generative models today | **Qwen only** (`V3_MODEL=qwen3.8-max`, `RAG_CHAT_MODEL=qwen3.8-max`, `OPENAI_CHAT_MODEL=qwen3.7-plus`, `AGENT_MODEL_NAME=qwen3.8-max`); embeddings `text-embedding-v4` |
| Backups | `/srv/coursemate/backups` (1.3 GB), latest `20260921-four-changes-final-before-schema13` |
| Env files (paths only) | `/etc/coursemate/{rag,agent,monitor}.env` (640, `root:coursemate`), `secrets/`, `env-backups/` |
| Out of scope, untouched | SRSZQ on `8.210.58.22` (`api.srszq.com`) and its local processes; the idle `47.237.179.69` |

Migration/direction consequences: production must go **25 → 28** (migrations 026–028; there is no 029 —
it was withdrawn with Laya), and the release must switch the generative path from Qwen to DeepSeek. The
rollback release to rehearse against is the real one (`4ef5064`), not an assumed schema-28 build.
Published CS3481/GE2324 trees (the 2 published courses) must not be regenerated.

> **Superseded (round 30).** This is a round-6 record, written before migrations 029 and 030 existed.
> As of the current revision production must go **25 → 30** (026 learning-start events, 027 assessment
> preparation reference, 028 Jev decision receipts, 029 proposal-only `entity_relations`, 030 durable
> feedback queue), and the release plan in
> `FINAL_COURSEMATE_JEV_DEEPSEEK_PRODUCTION_REPORT.md` rehearses 026–030 on an isolated restore. The
> rollback target (`4ef5064`) and the "do not regenerate the published trees" rule still stand.

### Round-6 work in flight

| Workstream | State |
|---|---|
| Real Jev business call sites for all 12 definitions (incl. the citation / context / pedagogy / classification / prerequisite / corpus-quality gaps the pause report named) | in progress |
| Promotion of the Laya-era measurement assets to Jev (310-sample judgment dataset, calibration maths, A/B/C/D/E arms) + a guard test keeping Laya out of the production tree | in progress |
| Mypy, local Playwright journeys, full regression on the frozen SHA | queued |
| DeepSeek live canary, Jev live validation + calibration, A/B/C/D/E results | **blocked**: DeepSeek key + TypeSafe credential/budget |
| Production release + real acceptance | **blocked**: credentials + the release window |

## Round 7 — Jev call sites landed; structured enhancement started (2026-09-22)

Commit `9a87cd6` closes the two in-flight workstreams and promotes the measurement layer.

**Verified by the orchestrator, not taken from agent reports:**

| Item | Evidence |
|---|---|
| 12 Jev call sites wired, all `shadow` | `tests/test_jev_callsites.py` **16 passed**; `JEV_CALLSITE_MATRIX.md` delivered |
| No regression in the surrounding product | Jev + intent + retrieval fusion + coverage + learning closure: **113 passed** |
| Measurement promoted to Jev names, data unchanged | `benchmarks/jev-judgments.dataset.json` (310 samples; splits 196/47/67; hash `2af0f40d…`), `app/evaluation/{jev_calibration,jev_semantic_ablation}.py`, `scripts/{build_jev_dataset,calibrate_jev,run_jev_semantic_ablation}.py`, **43 passed** |
| A/B/C/D/E harness really runs | offline CLI exit 0, verdict `NOT_INTERPRETABLE`, arms differentiated (E raises citation accuracy, D/E lower criterion error) — plumbing only, **not a result** |
| Zero Laya in the production tree | new `tests/test_no_laya_in_production.py` (**3 passed**) found and forced the fix of a real leftover comment in `app/jev/service.py` |
| Syntax/typing | all 10 agent-touched files parse; ruff clean after two import-sort fixes; mypy adds **no** new errors — the only 4 are pre-existing in `gateway.py` |
| Browser journeys (local, isolated identity) | `coursemate.spec.ts` **4 passed**, `learning.spec.ts` **3 passed** in real Chrome; `ui-refresh.spec.ts` (19 journeys) **cannot run as configured** — it serves a prebuilt bundle through `scripts/serve_web_dist.mjs`, which has no `/api` proxy, so the shell's same-origin `/api/ui/v1` calls return HTML (this is a pre-existing harness gap, not a product regression; the failing assertion is an API response parse error) |

Naming note: the new A–E semantic harness is `jev_semantic_ablation.py` / `run_jev_semantic_ablation.py`
because `run_jev_ablation.py` already exists as the older A–D plumbing CLI. The old pair is untouched
and documented as superseded for reporting only.

### Structured enhancement (new this round)

`docs/jev-structured/CASE_ADOPTION_MATRIX.md` records the disposition of the twelve cases: adopted
(entity alignment P1, passage conflict P0, citation checking P0, capability routing P1, tool-intent
check P1, ticket triage P2-last, extraction cascade P0-highest), merged (Paper Trellis into citation
checking) and explicitly **not** adopted (GEO/brand mentions, website expression scoring, CatBoost
student prediction, Browser Use in the request path).

The referenced Word file (`85462d42…m(3).doc`) is **not present** in this workspace or any readable
download folder, and the 60-case collection it cites was never provided, so the matrix is built from
the task specification's own case list and says so. No claim is made about unread material and no
quoted URL is treated as an API path.

Two P0 workstreams are running: module A `ExtractionVerification` and modules C+D
`EvidenceConsistency` + `ClaimCitationAudit`, each implementing against the existing gateway with a
recorded request for any new catalog definition rather than editing the catalog themselves.

## Round 23 — the three structured modules reach real business paths (2026-09-22)

Commit `034e3aa` closes the "helper exists but nothing reaches it" gap for three of
the six structured modules. The rule applied throughout: a decision that is only
written to the receipt ledger is **not** an integration, and a module whose result
is discarded does not count as wired.

| Module | Real business entry point | Effect that actually happens | Test |
|---|---|---|---|
| **B** CourseEntityResolution (`entity.relation.v1`) | `V3DomainAdapter._retrieve` (query expansion before the first recall; relation resolution after `fuse_scoped_candidates`) | accepted knowledge-node aliases expand the *query* (recall only, original query stays the prefix, explicit file/page targets skip expansion); resolved relations are written to the new **proposal-only** `entity_relations` store (migration 029, `status=PROPOSED`, `UNIQUE(left,right,relation)`, `used_jev`/`receipt_id` recorded, idempotent). Nothing merged/renamed/reordered/deleted. | `test_jev_entity_resolution.py` (20), `test_jev_shadow_invariance.py` (6) |
| **E** TeachingCapabilityRouter (`teaching.capability.v1`) | `cm_update/app.py::run` → `run_capability` | the resolved `skill_id` is **consumed**: only the capabilities this endpoint serves are offered, the code-owned baseline equals the previous flow, and `teaching_flow` decides whether the run binds the V3 journey through the orchestrator or answers without advancing. An explicit "answer only" is now really honoured at **0 Jev cost** instead of being discarded. The decision is reported on the create-run response. | `test_jev_capability_router.py` (17), `test_jev_capability_business_dispatch.py` (10, incl. an end-to-end run), `test_jev_shadow_invariance.py` |
| **F** ToolIntentCheck (`tool.intent.v1`) | `services/agent-api` `ToolExecutor.execute` → `JevToolIntentGate` → `POST /api/jev/tool-intent` → `ToolIntentCheck.authorize` | the guard now sits at the real model-proposed write boundary. `JEV_TOOL_INTENT_MODE=off` (default) makes **no** call and leaves the path byte-identical; `advisory` records the verdict and still executes; `enforce` blocks a non-`ALLOW` write. `searchTask` is read-only and never gated. The internal endpoint fails closed without a configured token. | `test_jev_tool_intent.py` (12), `test_api_tool_intent.py` (8), agent-api `intent-gate` (8) + `executor-intent-gate` (6) |

Also landed: **one shared semantic-decision layer** built in `app/main.py::create_app`
and threaded through `mount.py` → `integration.py` → `create_app(jev=…)` →
`V3DomainAdapter(jev=…)`, reused by the feedback and tool-intent routes (no second
gateway anywhere), and **migration 029** (`entity_relations`, `LATEST_V3_SCHEMA_VERSION`
28 → 29). Verified on an isolated database: `integrity=ok`, `fk_violations=0`,
`max_migration=29`, no `*_old`/`*_new` leftovers.

**Still `MODULE_ONLY` (no business effect claimed):** module **A** ExtractionVerification,
module **C** EvidenceConsistency, and the three-layer claim→citation audit of module
**D** (its two reused definitions *are* on the `_annotate_evidence` path). These are
implemented and tested but not yet invoked from ingestion/parse, the evidence-pack
step, or post-generation citation binding. `JEV_CALLSITE_MATRIX.md` marks each row
`MODULE_ONLY` / `PARTIAL` rather than `DONE`.

> **Superseded (rounds 24–30).** This paragraph is a round-23 record. C was wired in
> round 24, D in round 25, and **A in round 30** — see "Round 30" below for why A's
> `MODULE_ONLY` decision was wrong and what replaced it. Today no structured module is
> left without a consumer.

### Round 23 verification (real runs, not agent reports)

| Gate | Result |
|---|---|
| Full backend regression on `034e3aa` | **1135 passed / 0 failed** in 1572.69s (exit 0); `git diff 034e3aa..HEAD -- services/` is empty, so it still describes the backend at HEAD `544a97d` |
| Migration 029 on an isolated database | `integrity=ok`, `fk_violations=0`, `max_migration=29`, no `*_old`/`*_new` leftovers |
| agent-api | `vitest` **92 passed / 12 files**, `tsc --noEmit` exit 0, build exit 0 |
| Web app | `vitest` **64 passed**, `tsc` exit 0, build exit 0 |
| Browser journeys (real Chrome, real three services, injected identity) | `ui-refresh.spec.ts` **19/19**, `jev-structured.spec.ts` **2/2** (new), `coursemate.spec.ts` **4**, `learning.spec.ts` **3** — **28 journeys, 0 failed** |
| ruff / mypy | clean on every touched file; only the 4 pre-existing `gateway.py` mypy errors remain |

The browser gate earned its keep: `ui-refresh.spec.ts` had never actually run, and once
it did it found a **real product bug** — a `GET /layout` in flight when the learner moved
a reasoning-strength slider overwrote the new value and the next save wrote the stale
value back, so the control visibly snapped back. Fixed in `apps/web/src/ui/pages.jsx`
(plus three stale test expectations and one assertion that had matched a textarea's own
value instead of the persisted comment). It also produced the two new module journeys,
which run with **no TypeSafe credential on purpose**, making the suite double as the
Jev-unavailable acceptance.

Every definition remains `shadow`; there is still no TypeSafe credential, so
`live evidence = NOT_RUN` for all 19 definitions and no quality claim is made for
any of them. Wiring a call site is not evidence of quality.

## Round 24 — module C reaches the evidence pack; alias expansion made precise (2026-09-22)

Commit `7186d17` adds one more module to the "really wired" set and closes an
over-broad retrieval change from round 23.

| Item | What changed | Evidence |
|---|---|---|
| **C** EvidenceConsistency (`evidence.consistency.v1`) | `V3DomainAdapter._retrieve` now calls `check_evidence_consistency` over the already-authorized fused candidates and annotates every source with a deterministic `jev_consistency` signal; a genuine `SAME_CONTEXT_CONTRADICTION` additionally carries `jev_conflict_with`, which `provider.conflict_note` turns into a bounded instruction in all three teaching prompt builders — DeepSeek explains **both** sides and no source is dropped. Version/assumption differences are never called conflicts. | `test_jev_evidence_consistency_wiring.py` (4): byte-identical sources across off/shadow/unavailable/no-Jev; a real contradiction keeps both sources, unchanged ids/order, and adds exactly one note; version and assumption differences add none |
| **B** alias expansion precision | Expansion is now per concept: a group (canonical term + accepted aliases) is used only when the query itself names a member, in both directions. Round 23 appended *every* course alias to *every* query, which spent retrieval budget on terms the learner never asked about. | `test_jev_entity_resolution.py` (20) + `test_real_course_golden.py`: on the **real GE2324 corpus**, "聚类分析是什么意思" has no lexical hit and with the registry's accepted alias "clustering" reaches `assignment_2.pdf` |
| **A** ExtractionVerification | Investigated and left `MODULE_ONLY`: no production surface produces an `ExtractionRecord`-shaped record (free-text pages, generated model text, deterministic regex question labels with no per-field persistence slot or consumer). Each candidate surface and the reason it is ruled out is recorded in `docs/jev-structured/SOURCE_EXTRACTION_AND_ENTITY_RELATIONS.md` §9.4. | the module's types appear nowhere outside `app/jev/extraction.py` (`grep` cross-check) |
| mypy | A comment that began with `# type:` was read by mypy as a type comment, aborting the whole run — the app had never been type-checked as a whole. Fixed, and the honest number is now on record: **1068 pre-existing errors in 38 files** (legacy `ui_extension`/`cm_update`); the entire Jev layer has 6, all pre-existing in `gateway.py`/`receipt_store.py` | `work/current-change/mypy-app-round24b.log` |

**Verified on one frozen SHA (`7186d17`):** backend regression **1142 passed / 0 failed**
(1400.37s, exit 0); browser **28 journeys / 0 failed** across four suites
(`ui-refresh` 19, `jev-structured` 2, `coursemate` 4, `learning` 3); agent-api 92
tests with clean typecheck and build; web 64 tests with clean typecheck and build.

Every definition remains `shadow`; there is still no TypeSafe credential, so
`live evidence = NOT_RUN` for all 19 definitions and no quality claim is made for
any of them. Wiring a call site is not evidence of quality.

## Round 25 — module D bound to the teaching path (2026-09-22)

Commit `35ef493` closes the last structured module that had a real surface but no call
site. All six modules now either reach a business path with a consumer (B, C, D, E, F,
plus the P2 feedback module) or are honestly `MODULE_ONLY` with the investigation
recorded (A).

| Item | What changed | Evidence |
|---|---|---|
| **D** layer 1 — production resolver | `app/jev/citation_evidence.py::DocumentEvidenceResolver` answers `ok`/`missing`/`unauthorized` against the real store instead of raising, is read-only, version- and locator-aware, bounded, and never returns another course's or user's text. It reuses the canonical ACL (`can_read_document_version` → `_authorize_document_version`) and chunk scope (`ChunkRepository.resolve_document_chunks` → `_source_access`) rather than copying either. | `test_jev_citation_evidence.py` (12) on a real migrated DB: cross-user and cross-course `unauthorized`, version/locator resolution, text bound, and a before/after write check |
| **D** layer 2 — deterministic | `missing_claim_numbers(claim, evidence_text)`: a figure the claim asserts that the source never states is `NOT_ADDRESSED_IN_AVAILABLE_EVIDENCE` at **zero** model cost. While wiring it, a real defect was found and fixed: the unit regex listed `percent` before `percentage points`, so "7 percentage points" parsed as "7 percent" and could **fabricate** a numeric `CONTRADICTED`. | `test_percentage_points_are_never_read_as_percent`, `test_missing_claim_number_is_detected_deterministically` |
| **D** layer 3 — bound to the message revision | `cm_update.app.audit_answer_citations` runs after generation, extracts the sentence(s) that actually cite each `[Sn]`, audits them (≤6 cards per answer) and records verdict/layer/claim on the citation card the client already receives. Nothing is dropped, reordered or rewritten; with no semantic layer the cards are **byte-identical**; an audit failure records itself instead of losing the answer. | `test_citation_audit_binding.py` (7): zero-Jev deterministic verdict, shadow annotation, rejection, budget enforcement, failure survival, unchanged cards |
| **D** consumer | The shipped shell marks only a *real* negative verdict (warning chip + explanatory title) next to the citation; verified/partial/unchecked/legacy cards render exactly as before. | `apps/web/src/ui/citationSupport.test.ts` (4) |

**Verified on one frozen SHA (`35ef493`):** backend regression **1163 passed / 0 failed**
(1404.46s, exit 0); browser **28 journeys / 0 failed** (`ui-refresh` 19,
`jev-structured` 2, `coursemate` 4, `learning` 3, in real Chrome against the real
three services); web 68 tests with clean `tsc` and build; agent-api 92 tests with clean
`tsc` and build.

Still open and deliberately not claimed: `is_definitive` (audit the assessment
reference solution **before** presenting it) is implemented but not bound to the
assessment path; module A was reversed out of `MODULE_ONLY` in round 30 (wired to the
query-side exact-locator surface); every definition remains `shadow`, so
`live evidence = NOT_RUN` and no quality claim is made for any of them.

## Round 26 — high-impact gate, the last three call sites, and receipt safety (2026-09-22)

Commit `42d83ee` closes the last two local integration gaps and fixes a wiring defect the
tests could not see.

| Item | What changed | Evidence |
|---|---|---|
| High-impact gate (spec: verify the reference solution **before** the result is presented) | `app/learning/assessments.py` verifies a stored reference solution before grading uses it: layer 1 deterministic (every `source_ref` chunk still exists, is authorized and belongs to the current version — reusing `chunk_source_versions` + the module-D resolver, no copied ACL), layer 3 the semantic support decision, bounded to 8 refs per question. A **negative** verdict marks that question `needs_review` with a machine-readable reason and is re-presented by `_session_view`. No mark/weight/total/grade/coverage value is touched and no submission is blocked. | `test_reference_evidence_verification.py` (6): clean submission unflagged; stale ref flags with its reason and an identical score; shadow/unavailable byte-identical to no-Jev; a real `CONTRADICTED` flags; an empty-ref reference is recorded unverified, not contradicted |
| **Wiring defect: three of the twelve call sites were unreachable in production** | The shared service was threaded into the UI extension, the run endpoint and both internal APIs, but **never into `LearningOrchestrator`** — where call site 6 (pedagogy), 8 (criterion review) and 11 (prerequisite) live. `app/main.py` now passes it. | `test_jev_orchestrator_wiring.py` asserts the orchestrator, its `assessments` and its `knowledge` all hold the *same* service object |
| Receipt writes can no longer stall or fail a business operation | The criterion review runs inside the grading write transaction, so a receipt INSERT on a second connection would wait the full 10 s `busy_timeout` and then raise `database is locked` — inside a learner's grading request. `SqlReceiptStore` keeps its own 250 ms timeout and treats a lock/busy conflict as a **dropped receipt** (observability, not authority); a real NOT NULL/CHECK/UNIQUE error still raises. | the same test file: the contended write returns in well under 2 s without raising while another connection holds `BEGIN IMMEDIATE`, and a genuine constraint violation still surfaces |
| Component ablation for the six modules (spec §10) | Six component arms (`M-EXTRACT`, `M-ENTITY`, `M-CONSISTENCY`, `M-CITATION`, `M-CAPABILITY`, `M-TOOL`) run alongside the untouched A–E. **Only `M-CITATION` has labelled samples**; the other five report `INSUFFICIENT_SAMPLES` and emit no number, because the frozen dataset has zero samples for their definitions. | `test_jev_semantic_component_ablation.py` (14) + an offline `--arm all-components` run tagged `NON_INTERPRETABLE_PLUMBING_ONLY` |

Honest limitations recorded with this round: the semantic half of the high-impact gate is **inert in
production today** only in the sense that no credential exists — the orchestrator now genuinely receives
the service, so the calls happen and stay in `shadow`. Receipts written from inside a business
transaction are best-effort and may be dropped under contention; moving those semantic calls out of the
write transaction (or writing receipts on the caller's connection) is the recorded follow-up.

## Round 27 — receipts become part of the business transaction; deliverables de-staled (2026-09-22)

Commit `b8104d9`.

| Item | What changed |
|---|---|
| Receipt atomicity | `SqlReceiptStore` can now be handed the caller's open transaction (`receipt_connection(...)`), so a decision made inside assessment grading writes its receipt **on that connection**: it commits with the grade and rolls back with it. The ledger can no longer describe a decision whose business change did not happen, and there is no lock contention at all in the grading path. Outside such a transaction the write stays best-effort (250 ms, dropped on a lock conflict, never stalling or failing the operation). `tests/test_jev_orchestrator_wiring.py` (6) proves commit, rollback atomicity and that the lending is context-scoped only |
| Deliverables de-staled | `JEV_BACKEND_ARCHITECTURE_FINAL.md` claimed a four-mode system (`off\|shadow\|on\|advisory`) that the gateway and the receipt CHECK constraint both reject, said the layer writes only receipts (it also writes proposal-only relations), described the pre-module retrieval chain, and still called the call-site wiring "the active workstream". All corrected; the doc now states that `shadow` **is** the advisory state the task describes (the call is made and recorded, the deterministic value is used) and that promotion to `on` is the only behaviour-changing step |
| New deliverable | `FINAL_COURSEMATE_JEV_DEEPSEEK_PRODUCTION_REPORT.md` — the release-candidate state: frozen revision and its full local evidence, exactly what the release would change in production, the production facts recorded read-only (to be re-verified before the release), everything still `NOT_RUN`, and the ordered release plan with its rollback. Marked at the top as **not** a production acceptance report |

**Verified on one frozen SHA (`b8104d9`):** backend regression **1189 passed / 0 failed**
(1471.55s, exit 0); browser **28 journeys / 0 failed** across the four suites, in real
Chrome against the real services.

## Round 29 — the feedback queue becomes durable, and its consent gate is fixed (2026-09-22)

Commit `5be2d0a`. Schema **29 → 30**.

| Item | What changed |
|---|---|
| Durable queue (spec §5's "review queue") | The P2 module classified a report and kept it in process memory, so the queue a reviewer was meant to work through vanished on every restart and nothing could read it back. Migration 030 adds `feedback_reports`: one row per submission, idempotent by report key, carrying the identifiers, the triage suggestion and its Jev receipts, with `status` starting `OPEN`. |
| Privacy is now structural | A CHECK constraint refuses any body text unless the submitter set `attach_body`, so no future code path can store a question/answer body without consent — the endpoint and the triage module enforce the same rule earlier, and the shipped form only enables the free-text field once the box is ticked. |
| The queue has a reader | `GET /api/feedback/queue` (admin only, most severe first) and `GET /api/feedback/mine` (the caller's own reports). The store exposes read/append methods only — a test pins that surface so adding a mutating method has to be a conscious design step, which is what keeps "no auto-grade, no auto-ban, no auto-delete" true. |
| Product bug fixed | The shell's report form sent the user's free-text note while the consent box was unchecked, so describing a problem and submitting it was rejected with `400 BODY_NOT_OPTED_IN`. The form now gates the note on the checkbox, matching the task spec, the server rule and the form's own helper text. |
| Two bugs caught by the new tests | `_public` iterated a `sqlite3.Row` (which yields *values*, not column names) and broke as soon as two suites ran together; and the queue-name assertion in my first test guessed the module's naming instead of reading it. Both fixed in the code/test, not by weakening an assertion. |

**Verified on one frozen SHA (`5be2d0a`):** backend regression **1195 passed / 0 failed**
(1473.95s, exit 0); browser **29 journeys / 0 failed** (the `jev-structured` suite gained
the report-dialog journey, which drives the real shell in real Chrome); the isolated
migration probe reports `expected_schema=30`, idempotent replay, `integrity=ok`,
no foreign-key violations, `max_migration=30` and no leftovers.

Recorded while doing it: writing that browser journey is what exposed the consent-gate
bug — the suite would have passed forever if it had only asserted that the dialog opens.

## Round 30 — module A wired to the exact-locator surface, and the round-26 decision reversed (2026-09-22)

Commit `ff1cfa9` (module-A wiring) and `6e65396` (the definition de-duplication that
followed, with the whole gate re-run on the final revision). No schema change (still
**30**). Module **A** was the last structured module marked `MODULE_ONLY`; it is now
wired, and the reason the earlier decision was wrong is part of the record.

| Item | What changed |
|---|---|
| **The missed surface** | Round 26 looked for a *document-side* field record and concluded none existed. The surface it missed is the **query-side** parser `app/tutor/references.py::parse_query_reference`: its `question_number`/`question_part` are not annotations but **hard filters** — `ChunkRepository.structured_search` adds `json_extract(metadata_json,'$.question_number'/'$.question_part') = ?` in the official scope *and* the learner's private scope, and puts its hits at the head of the candidate list. `QaService.stream` also derives `example_mode` from the same label. |
| **A real parser defect, reproduced first** | The old sub-part pattern was optional and unterminated, so **the word following the number donated its first letter** as a phantom sub-part, and the roman-numeral alternative matched the first letter of the next word. Five of six prose probes invented a label: `question 5 have …` → `question_part='h'`, `q mean in this context` → `question_number='M'` + `part='e'`, `question 3 marks …` → `part='m'`. The phantom filter suppressed the legitimate exact hits for question 5 and could pin retrieval onto a wrong sub-question. A sub-part is now read only when **delimited** (parenthesised, or a standalone token not glued to a following word) and a roman numeral must not be followed by a word character. Every pinned real-corpus case still parses. |
| **The wiring** | `app/jev/reference_verification.py` projects a present label into an `ExtractionRecord` (source = the learner's own normalised message, locator = the character span it was read from) and runs the module-A pipeline over it. The judgment goes through a new **13th call site** `callsites.verify_extraction_field` → `SemanticDecisionService.field_grounded`, whose candidate vocabulary is read from the catalog entry; `ExtractionVerifier` gained an optional `service` and now routes through it, and `field_grounded_definition()` is projected from the catalog with the module constants asserted against it. |
| **Disposal — the answer to the round-26 objection** | Only a deterministic failure or an affirmative defect (`WRONG_FIELD`/`NEGATION_LOST`/`CONSTRAINT_LOST`/`SOURCE_INSUFFICIENT`) drops a label. `UNCERTAIN`, `off`, `shadow`, no-service and timeout keep the deterministic reference **exactly as it was** and report `NEEDS_REVIEW`, so nothing changes behaviour until a decision is calibrated and enabled. Dropping can only ever *remove* a filter, so this module can never widen what a learner may read, add a source, or reach an unauthorized chunk. |
| **Consumers** | `V3DomainAdapter._retrieve` attaches `jev_reference` to every returned source; `QaService.stream` adds `referenceVerification` to the SSE `meta` event and the stored message metadata. A message that names no question label costs **zero** calls and reports `questioned: false`. |
| **Two further real defects found while testing** | (1) **Cross-user cache leak**: the first version took the cache scope from the *optional* decision service, so a run without one fell back to a single server-internal scope and served one learner's judgment to another. `owner_user_id`/`authorization_scope` are now required and the scope is derived from the caller; `test_cache_scope_is_owner_scoped_and_never_crosses_users` reproduces the leak and pins the fix. (2) **The layer could fail a learner request**: `SqlReceiptStore.lookup` raised `sqlite3.OperationalError: no such table: jev_decision_receipts` when its own ledger was absent (a V2-only schema, or new code running before migration 028) — it surfaced as two `test_qa_api.py` failures in the first full regression of this round. An absent ledger is now a cache miss plus a dropped receipt, while every other SQLite error still propagates. |
| **One more latent hazard closed** | The module's single default repair allowance left the *second* label unplanned, so an exhausted allowance could have kept a label the model called wrong as a filter. Disposal is **verdict-driven** rather than status-driven, and the surface is built with one allowance per label. |
| **A third definition was still a duplicate of its catalog entry** | `evidence_consistency.py` built its own `DecisionDefinition` and sent `{relation: relation}` as the criteria labels, so the model was shown bare ids while the catalog registered descriptions — and a calibration run would have measured the duplicate rather than the registered entry. The module now projects the catalog definition and sends its criteria/instructions, with the relation vocabulary asserted against the catalog; `test_the_registered_definition_is_the_one_the_model_is_shown` pins both. The three documentation sections still describing a "pending registration request" are corrected. |

> ## Current state — read this before the table below
>
> **Added 2026-09-22 (rounds 31–37).** The verification table further down is the record for the
> revision `6e65396`; it is **not** the current state, and one of its rows was wrong. Re-measured on
> later revisions:
>
> | Gate | Now | Then (`6e65396`) |
> |---|---|---|
> | Backend regression | **1293 passed / 0 failed**, 1577.08s, exit 0 — `work/current-change/full_run_round35.log`, frozen revision `169bd57`, with `git diff 169bd57 -- services rag-api benchmarks` empty | 1235 passed / 0 failed |
> | Browser journeys | **46 journeys / 0 failed across five suites**: `ui-refresh` 19, `jev-structured` 6, `coursemate` 4, `learning` 3 (re-run on `6ba70b0`) and **`codex-audit` 14** (run on `d656bf7`, isolated run dir `work/codex-audit/browser-1790085060907-11488`, its own report recording 14 expected / 0 unexpected / 0 flaky) | 32 journeys |
> | Web app | `tsc` 0, **73 tests** (19 files), build 0 | 68 tests |
> | agent-api | `tsc --noEmit` 0, **92 tests**, build 0 | 92 tests |
> | ruff | **1815** for `app` + `tests`, unchanged | 1815 |
> | mypy | **1004 errors in 32 files**, and **`app/jev/` + `app/evaluation/` are at zero** | the row below reads 1074/39 |
> | Schema | still **30**; all **19** definitions still `shadow`; no live call made | same |
>
> **The wrong row, stated plainly:** the table's mypy line claims "1074 errors in 39 files, none in a
> file this round changed or added". Re-measuring showed **1077 in 38**: the round-31 module-metric
> collectors had themselves added seven errors to `app/evaluation/jev_semantic_ablation.py`. Those, and
> five more found later, are fixed; the accounting is `docs/recovery/CURRENT_BLOCKER_LEDGER.md` B-10.
> The same "unchanged" wording appeared in `CHATGPT_REVIEW_CURRENT_STATUS_AND_BLOCKERS.md` and in
> `FINAL_COURSEMATE_JEV_STRUCTURED_ENHANCEMENT_REPORT.md`, and was corrected in both.
>
> Two further pieces of evidence were produced after this table was written and are not in it: the
> **25 → 30 migration rehearsal** on a database built by the production release's own code
> (`old_rows_unchanged: true`, every fingerprinted table byte-identical by SHA-256), and the
> **rollback-compatibility check against release `4ef5064`** (`ROLLBACK_SAFE_WITH_MIGRATED_DB`).
> Both are recorded in `docs/recovery/CURRENT_BLOCKER_LEDGER.md` B-27, and the publish path's local
> half in B-35.

> **Added 2026-09-24 (round 90) — the four journeys exist now, and building them found two defects
> that had kept the modules from reaching anyone.** Revision **`d824a5b`**.
>
> Round 89 ended with "the fixtures do not exist yet". They do now
> (`scripts/seed_structured_fixture.py`), and the journeys did not merely become possible: they
> exposed two real defects, both of which looked like working code from every angle a unit test
> usually checks.
>
> | Defect | How it looked | What it was | Effect on a learner |
> |---|---|---|---|
> | **Module D audited against the wrong database** | `audit_answer_citations` was called with `database=db`, which on the teaching path is the UI extension's own `ui.sqlite3`. The unit tests pass a **stub** resolver, or a test database that really has the tables, so nothing noticed | `DocumentEvidenceResolver` queries `document_versions` / `learning_workspaces` / chunks; the UI store has none of them. Every card raised `OperationalError: no such table: document_versions`, the `except` recorded it and returned the cards un-annotated — by design, "an audit failure can never lose an answer" | **No citation verdict ever reached a reader.** Layer 2 (the code-decided missing-figure check) also died, because the handler abandoned the loop on the first failure and took every later card's verdict with it. The UI's own `citationVerdict` renderer (`apps/web/src/ui/citationSupport.js`) could never fire |
> | **The `test` provider emitted no citation markers** | `mentioned=set(re.findall(r'\[(S\d+)\]',output))` was always empty in the local acceptance shape, so `citations` was `[]` in every browser run | The live DeepSeek provider writes `[S1]` markers — that is why the audit exists — but the labelled double did not, so the entire citation path was unreachable in local acceptance | Nothing user-visible; it made the *acceptance* blind. Recorded in the spec's own header since round 25 as a limitation rather than fixed |
>
> Both are fixed in `d824a5b`: the store is an explicit `evidence_database` parameter passed from the
> adapter, the resolver is built lazily (so a layer-2 verdict works with no store at all), the failure
> handler is per-card, and the double writes one cited sentence per offered source quoting the
> learner's own words — which is also what lets a journey drive the deterministic layer from the
> question alone. The `problem` lane is untouched: its output is parsed into numbered steps.
>
> **The fixture** (`scripts/seed_structured_fixture.py`) ingests, through the product's own
> `IngestionService`, an English-only page a Chinese question can only reach via an accepted alias
> (`密度聚类` → `DBSCAN`), one word in two unrelated senses (`kernel`), the same quantity under
> different assumptions (`5%` two-sided vs `10%` one-sided) and under the *same* assumption with
> different values (`5%` vs `20%`, the contradiction pair), and a markdown page whose two headings put
> two fragments in different chunks of one document. It goes into the learner's **own workspace
> corpus**, because the product's ingestion *refused* the official course — `Course content is locked
> by publication review` — which is the guardrail working, and is why the fixture is not shaped the way
> round 89 first assumed.
>
> | Journey | Configuration | Result |
> |---|---|---|
> | A Chinese question reaches English material through an accepted alias | none needed | **passes**: the fixture page is a citation card, the learner's original query is `user_text` verbatim, and the chip is visible in the pane |
> | One word in two senses is not merged, and the tree is untouched | none needed | **passes**: both pages are separate cards with different `document_id`, and the knowledge tree's node identity/title/parent/position is byte-identical before and after the run |
> | Fragments from different tasks are reported as such, both kept | none needed | **passes**: two chunks of the one markdown document carry `VERSION_OR_TASK_DIFFERENCE` with distinct locators, and neither is dropped |
> | A figure no cited source states is flagged, and the source is still shown | none needed | **passes**: every card is `NOT_ADDRESSED_IN_AVAILABLE_EVIDENCE` at layer `quote` with `['42%']`, the answer still renders all of them with the unverified marker, and the control question about `5%` leaves the page that *states* 5% unflagged |
> | A genuine contradiction is surfaced with both kept | live key + `evidence.consistency.v1=on` | **passes** (29.1 s): at least two cards carry `jev_conflict_with` and both fragments survive |
> | A write whose intent check cannot answer is not executed | `JEV_TOOL_INTENT_MODE=enforce` + deliberately unreachable endpoint | **passes**: `fallback:unavailable`, `REQUIRE_CONFIRMATION`, `jevCalls: 0`, and the task board is byte-identical before and after |
> | An explicit authorised write is not over-blocked | enforce + live key + `tool.intent.v1=on` + raised timeout | **passes**: the task is created |
>
> **The live run's own receipt store is where its cost comes from** — not an estimate:
> **169 decisions, every one `outcome=ok` and every one carrying a `model_version`** (so no fallback
> answered any of them), across 14 definitions: `retrieval.support.v1` 42,
> `source.supports_claim.v1` 31, `evidence.consistency.v1` **18 (mode `on`)**, `coverage.item_support.v1`
> 14, `teaching.capability.v1` 14, `context.keep_segment.v1` 11, `source.select_span.v1` 10,
> `entity.relation.v1` 9, `intent.next_action.v1` 7, `pedagogy.next_method.v1` 7,
> `extraction.field_grounded.v1` 3, `feedback.category.v1` 1, `feedback.severity.v1` 1, `tool.intent.v1`
> **1 (mode `on`)**. Observed decision latency **0.68–1.35 s**. This is inside the §16 ask (≤300
> decisions) and it is the figure the owner's budget card should be read against.
>
> **One finding worth acting on, recorded rather than smoothed over:** the tool-intent guard's default
> budget is **1.5 s** (`JEV_TOOL_INTENT_TIMEOUT_MS`, bounded 100–10 000) and the measured decision
> takes **0.68–1.35 s**. On the first attempt at the explicit-write journey the guard gave up before
> the answer arrived, the verdict became `fallback:unavailable`, and a perfectly legitimate write was
> refused. Fail-closed is the right behaviour, but the margin is thin: a deployment that enforces this
> gate should raise the budget (the journey now *requires* ≥5 s instead of racing the default), or the
> gate will occasionally ask a learner to confirm something they already asked for unambiguously.
>
> **Four invocation traps, each of which cost a run and is now written down:** the agent refuses to
> start when `JEV_TOOL_INTENT_TIMEOUT_MS` is an **empty string** (`?? ""` in a Playwright config sends
> exactly that; the config now sends the agent's own default), and PowerShell *deletes* an env var
> assigned `""`, so the same thing cannot be reproduced by hand in the shell — which is how a manual
> check said "it starts fine" while the suite died on `Expected an integer between 100 and 10000`;
> Playwright's webServer logs to stderr, so PowerShell reports a non-zero exit for a **passing** run
> (`$LASTEXITCODE` must be captured explicitly); and a UI assertion on "the last `.citation-row` in the
> pane" can match the *previous* answer while the new one is still appending, so the chip count passes
> against a stale row and the verdict assertion on that row then fails — every UI assertion now anchors
> on a string only the new answer contains.
>
> Also this round: `services/rag-api/tests/test_structured_e2e_fixture_shape.py` pins the properties
> each journey depends on (the alias page never contains the Chinese term; the two kernel pages do not
> mention each other's field; `42%` is in no page while `5%` is in exactly one; the markdown page has
> two distinct headings) so a journey cannot quietly become a test of nothing.
>
> **The gate, run on the one frozen revision `d824a5b` that includes everything above.** Every number
> is from a run against that tree; nothing here is carried over from an earlier revision.
>
> | Gate | Result |
> |---|---|
> | Backend full regression | **1717 passed / 2 skipped / 0 failed** in 2019.92 s (33:39), exit 0 — `work/current-change/full_run_d824a5b.log`. The **+7** over the `263c620` gate (1710) are exactly the tests this round added: 5 fixture-shape + 2 citation-audit. The two skips are the same environmental ones (a symlink needs a privilege this account lacks; POSIX permission bits are not the Windows mechanism) |
> | Browser, shipped shape (no credential, nothing promoted, gate off) | `ui-refresh` **23 passed**, `coursemate` **4 passed**, `v3-learning` **3 passed**, `jev-structured` **10 passed / 4 skipped / 0 failed** — all exit 0. The four skips are the live-gated journeys, each naming its own precondition |
> | Browser, live promoted shape | `jev-structured` **11 passed / 3 skipped / 0 failed**, exit 0 (the three skips are the no-credential journeys, which a promotion deliberately invalidates); plus the two tool-intent configurations run separately, **1 passed / 1 skipped** each, exit 0 both times |
> | Web app | **107 tests passed** (23 files), `tsc -b` exit 0, production build + PAT scan exit 0 (`no token field, notice present`) |
> | Agent service | **92 tests passed** (12 files), `tsc --noEmit` exit 0, build exit 0 |
> | mypy | **0 errors added** in either changed module, measured in a worktree of HEAD with the same interpreter (`app/cm_update/app.py` 730 → 730, `provider.py` 56 → 56) |
> | ruff | **0 findings added** in either changed module (597 → 597, 66 → 66); the new seeder carries only the five inert `noqa: E402` markers its two sibling seeders already carry, and the `F821` and `ISC004` findings it started with are fixed |
>
> **Not claimed:** the quality gate still does not pass and **nothing is promoted in the committed
> configuration** — the promotions in the table above exist only for the measurement, and
> `playwright.jev.config.ts` promotes nothing by default. §15 (production) has not begun: no
> production system was contacted, no migration was run against a live database, and the release
> sequence still waits on the owner's native approvals, one real login, and the Jev USD figure.

> **Added 2026-09-24 (round 89) — the four browser journeys the task asks for, and exactly where each
> one attaches.**
>
> §12 of the task lists seven new browser journeys. Three exist: extraction verification (module A) and
> the Jev-unavailable fallback have their own journeys, and the promoted-capability journey added in
> round 88 covers Skill selection. **Four are missing — alias retrieval, condition conflict,
> unsupported citation, and tool-intent misuse — and the reason is not effort, it is content.**
>
> The e2e environment has no content that those modules can act on: `playwright.jev.config.ts` builds a
> fresh data directory per run and prepares it with `scripts/prepare_full_e2e.py`, which delegates to
> `scripts/prepare_v3_e2e.py` (`seed_assessment_fixture`). So the seeding script is the attach point,
> and each journey needs one concrete fixture plus one promoted definition:
>
> | Journey | Fixture needed in the prepared data | Promoted definition | What the journey can assert |
> |---|---|---|---|
> | Alias retrieval | one concept with a Chinese term in one document and its English form in another (same course) | `entity.relation.v1=on` | the Chinese query retrieves the English material, and the learner's original query and the exact locator survive |
> | Same-word, different meaning | one word used in two unrelated senses in two documents | `entity.relation.v1=on` | the two are **not** merged, and no tree id changes |
> | Condition conflict | two fragments stating the same quantity under different assumptions, and a third pair that genuinely contradict in the same context | `evidence.consistency.v1=on` | a contradiction is surfaced with **both** fragments kept (neither deleted), a condition difference is reported as a scope difference |
> | Unsupported citation | a claim and a span that does not address it | `source.supports_claim.v1=on` | the run's evidence annotation is not `SUPPORTED`, and no source is removed |
> | Tool-intent misuse | a side-effecting tool proposed from an ambiguous message, and an explicit authorised one | `tool.intent.v1=on` | the ambiguous one is refused or clarified, the explicit one is **not** over-blocked |
>
> Two constraints the implementer must respect, both already established: the suite runs
> `test.describe.configure({ mode: "serial" })`, so a new journey that leaves a run in flight breaks the
> next one; and the deterministic provider never emits citation markers, so a citation journey must
> assert through the run's `meta` evidence (as the module-A journey already does) rather than through a
> rendered citation list.
>
> Not done this round, and not claimed: the fixtures do not exist yet, so these four journeys are
> **NOT_RUN** and `BROWSER_ACCEPTANCE` does not include them.

> **Added 2026-09-24 (round 88) — the browser acceptance can now tell a promotion apart from shadow,
> and it has been run both ways.**
>
> Round 87 added `JEV_DEFINITION_MODES`; round 88 uses it to make the claim the suite could not
> previously make. `capability_router.py` honours `mode == "on"` explicitly, so promoting
> `teaching.capability.v1` makes `used_jev` observable in the shipped shell — which is exactly what
> the round-86 note said was missing.
>
> | Configuration | `jev-structured` result |
> |---|---|
> | Committed default (no key, nothing promoted) | **6 passed, 1 skipped**, exit 0 (`browser_jev_round88.log`) — the skipped one is the promotion journey, stating its own precondition |
> | Live key + `JEV_DEFINITION_MODES=teaching.capability.v1=on` | the promotion journey **passed**, 53.2 s (`browser_jev_promoted_round88b.log`): the run the client reads back reports `used_jev: true`, a legal `skill_id`, and a completed run |
>
> That second row is the first browser evidence that a promotion is *used* by the product rather than
> merely recorded, and it is why `BROWSER_ACCEPTANCE` is no longer limited to the no-credential shape.
> It is **not** a claim that any definition *should* be promoted: the quality gate still does not pass
> (§9 of `JEV_CALIBRATION_AND_ABLATION_REPORT.md`), the promotion existed only for the measurement, and
> the committed configuration promotes nothing.
>
> One thing left unexplained, recorded rather than smoothed over: the **first** attempt of that journey
> answered **409 on run creation** and the immediate re-run passed. The two candidates are a run
> conflict while a previous run was still active, and contention with the backend gate that was running
> on the same machine at the time; neither is proven. The QA helper now reports the response body when
> run creation is not a 202 (it previously asserted the status alone), so the next occurrence will name
> itself instead of repeating this ambiguity. Both journeys that assert "no Jev signal" now skip, with
> the reason, when a promotion is active — otherwise they would fail correctly and confusingly.

> **Added 2026-09-24 (round 86) — a false alarm corrected, and what a live browser run can and
> cannot show.**
>
> A first attempt to run the `jev-structured` suite with `TYPESAFE_API_KEY` present failed at the
> first journey (`.workspace-columns` never appeared, 20.9 s) and, because the suite is serial, the
> other five did not run. **The cause was mine, not Jev's:** the §12 web-build step had replaced the
> E2E-shaped `apps/web/dist` with a production-shaped one, so the shell had no test identity and
> never got past `GET /config` — the service log showed that request and nothing else, with no error
> at all, which is what pointed at the client. Rebuilding the E2E dist and re-running gave
> **6 passed / 0 failed in 1.9 min** (`browser_jev_live_round86b.log`).
>
> The lesson is recorded because the same trap will recur: **the browser suite needs the E2E-shaped
> build**, and the §12 production build overwrites it. Rebuild with `VITE_AUTH_TEST_TOKEN`,
> `VITE_UI_API_BASE` and `VITE_V3_ENABLED` set (as `docs/ui-refresh/UI_AND_BACKEND_TEST_REPORT.md`
> documents) before any browser run.
>
> **What that run does not prove, stated plainly: it does not prove Jev was live in the browser.**
> The journey that would notice — "with no TypeSafe credential every decision degrades" — asserts
> `run.capability.used_jev === false`, and that is false in **shadow** mode whether or not a
> credential exists (`_decide` sets `used = mode == "on" and suggestion is not None`, and the
> catalogue's `default_runtime_mode` is `shadow` for every definition). So the assertion cannot
> distinguish "shadow with a live key" from "no credential", and the 1.9 min runtime against 58.8 s
> without a key is suggestive rather than conclusive. **`BROWSER_ACCEPTANCE` therefore still
> describes the no-credential shape**, and the honest next step is a browser assertion that is
> credential-sensitive: a receipt's `model_version`, or a test deployment with one definition
> promoted to `on`, which the task's §14 gates on a quality result that does not yet exist.
>
> The Playwright config's RAG `webServer` now **pipes** its output instead of discarding it (it was
> `stdout: "ignore", stderr: "ignore"`, which is why the first failure was undiagnosable from the
> run); read it with `DEBUG=pw:webserver`.

> **Added 2026-09-24 (round 85–88) — the local gate, on one frozen revision.** The current revision is
> **`263c620`**; every earlier number below is kept as the record of what was measured on the revision
> it names, and a gate is never reused across a code change (three were discarded and re-run for
> exactly that reason rather than reported).
>
> | Gate | Result |
> |---|---|
> | Backend full regression | **1710 passed / 2 skipped / 0 failed**, 2006.74 s (33:26), exit 0 — `work/current-change/full_run_263c620.log` on revision `263c620`. The +9 over the previous gate are the `JEV_DEFINITION_MODES` tests (`test_jev_definition_modes.py`). Earlier: `bb04101` **1701 passed / 2 skipped / 0 failed** in 2017.45 s (`full_run_bb04101.log`), `8556440` the same totals in 1992.48 s (`full_run_8556440.log`). The two skips are environmental: creating a symlink needs a privilege this account lacks, and POSIX permission bits are not the Windows mechanism |
> | Browser journeys | `ui-refresh` **23 passed**; `jev-structured` **6 passed, 1 skipped, 0 failed** in the committed default shape (`browser_jev_round88.log`), and the same suite with a live credential plus `JEV_DEFINITION_MODES=teaching.capability.v1=on` has its **promotion journey passing** (`browser_jev_promoted_round88b.log`) — see the round-88 note for what that does and does not establish |
> | Web app | **107 tests passed** (23 files), `tsc -b` exit 0, production build + PAT scan exit 0 (`no token field, notice present`) |
> | Agent service | **92 tests passed** (12 files), `tsc --noEmit` exit 0, build exit 0 |
> | mypy | **0 errors in `app/jev/` and `app/evaluation/`**; the 11 reported while type-checking those two directories are all in transitively-imported files (`app/course_access.py`, `app/learning/workspaces.py`, …), unchanged by this work |
> | ruff | **0 findings added** against HEAD across every changed file |
>
> Three invocation traps worth recording, because each produced a false result first: `vitest run
> --root apps/web` from the repository root reports **33 failures** (the config's `setupFiles`
> resolve differently), while running it from `apps/web` reports **107 passed**; the browser suite
> needs the **E2E-shaped** build, so the §12 production build must not be left in `apps/web/dist`
> (round 86); and a full gate must not be started before the last code change.
>
> **What this gate does not cover**, so it is not read as more than it is: the Jev layer is still
> `shadow` in every arm of it (the live quality comparison is a separate run, §9 of
> `JEV_CALIBRATION_AND_ABLATION_REPORT.md`), no production system was contacted, and the release
> sequence in §15 of the task has not begun.

> **Added 2026-09-24 (rounds 83–84).** The most consequential thing since the table above: **the
> Jev layer has now been called live, and the quality gate does not pass.** Nothing is promoted;
> every definition is still `shadow`.
>
> | What ran | Result |
> |---|---|
> | All **19 catalog definitions** called live through the real gateway, caching disabled, positive + negative case each | **31 cases, 31 valid answers, 30 met the expectation, 19/19 definitions covered** (`work/current-change/jev-live-cases.json`) |
> | The Score primitive | Found to be **unusable live**: the service answers with a decimal on the definition's own scale (`3.99` on 0..4, `2.0` on 0..2), not a level key, so the typed validator refused it as `invalid_response`. Fixed by carrying the number as `JevAnswer.score_value` **without inventing a level**; out-of-scale values are still refused (`f6d6311`) |
> | A–E ablation, live Jev, calibration split (47 samples) | Verdict `NOT_INTERPRETABLE` — arm A abstained on everything because no production baseline was injected |
> | A–E ablation, live Jev **and live DeepSeek baseline**, baseline asked once per sample | Verdict **`INTERPRETABLE`**, and unfavourable: Jev improves citation support 0.667→0.833 and the unsupported-claim rate 0.667→0.500; **regresses** `criterion_error` 0.000→0.333 (one case of three) and `key_fact_retention` 1.000→0.000 (one case of two); **ties** on `intent_accuracy` 0.667 both sides and elsewhere. DeepSeek calls fall by 9/17/27 across arms C/D/E (`work/current-change/jev-ablation-live-baseline3.json`, §9 of `JEV_CALIBRATION_AND_ABLATION_REPORT.md`) |
> | Two corrections made while measuring | (a) the arms were each re-asking the baseline, so they were not a controlled difference — a definition **no arm arms** differed between arms (`corpus_quality_mae` 0.125 vs 0.250); fixed by `memoise_predictor` and confirmed by the two metrics becoming ties. (b) an earlier summary reported an `intent_accuracy` regression by subtracting arm E's number in one run from arm A's number in another; the per-case record shows **every arm at 0.667**, so it is a tie — the rule "never subtract two runs" is now written into the report |
> | Per-case records | `intent`, `pedagogy`, `span_selection`, `exercise`, `prerequisite` and `context` now publish each case (label, prediction, agreement) beside the rate, and `metric_denominators` publishes the population of **every** definition-level rate — because these populations are 1–8 samples and one case moves a rate by 12–100 points |
> | Test split (67 samples) | **Not run, deliberately**: thresholds are tuned on calibration and the test set is looked at once, after they are frozen |
>
> Consequences, stated rather than softened: **no promotion**, including the retrieval-rerank
> promotion the task lists as first priority (the calibration split has no `retrieval.support.v1`
> samples, so that definition has no live quality number at all yet); the two regressions sit on
> `assessment.criterion_review.v1` and `coverage.item_support.v1`, the two definitions the task
> allows only ever to be advisory; and the per-metric sample counts are not yet in the artefact, so
> how much of each swing is real versus small-n is **unknown**, not assumed.
>
> Also added in these rounds: `live_jev_predictor` (the semantic ablation harness could not run live
> at all before) and `app/evaluation/jev_deepseek_baseline.py` (the missing baseline — without it
> the comparison was measured against abstention).

**Verified on one frozen SHA (`6e65396`)** — every number below comes from a run on the
tree that was committed, and `git diff HEAD -- services/rag-api tests` is empty:

| Gate | Result |
|---|---|
| Full backend regression | **1235 passed / 0 failed** in 1467.07s (exit 0) — `work/current-change/full_run_round30_final2.log`. The first run of this round was **1226 passed / 2 failed**, and both failures were the absent-ledger defect above, fixed in the layer rather than in the test |
| Browser journeys (real Chrome, real three services, injected identity) | **32 journeys / 0 failed**: `ui-refresh` 19, `jev-structured` **6** (three new), `coursemate` 4, `learning` 3 |
| ruff | **1815 errors at the previous revision and 1815 in the tree** — identical, so this round added none (measured against a `git worktree` of `69e6f19`) |
| mypy | **1074 errors in 39 files**, none in a file this round changed or added (runs before and after each fix agree exactly; the +6 since round 24's recorded 1068 belongs to rounds 25–29) |
| New tests | 29 module-contract (`test_jev_reference_verification.py`, which carries the prose regression cases for the parser defect), 4 business-path over the real chunker and real `context.retrieve` (`test_jev_reference_business_path.py`), 6 absent-ledger (`test_jev_absent_ledger.py`) and 1 registered-definition (`test_jev_evidence_consistency.py`) — **40 new tests**, which is exactly the regression delta 1195 → 1235 |

The three new browser journeys needed real deployment work rather than a fake: the
shipped *legacy* pages resolve the RAG API from the value baked into the build
(`localhost:8000`), so the acceptance config serves the same build output once more on
that origin with the same proxy; and the shell **aborts the answer stream** as soon as it
sees the terminal event, so `response.text()` always rejects with `AbortError` — the
journey tees the page's own response incrementally and reads the report off the first
frame instead. Both are local-test plumbing, no product or release artifact.

Honest limitations recorded with this round: module A's semantic half is **inert in
production** — with no TypeSafe credential every field reports `fallback:jev_shadow`
with `used_jev=false`, so a verdict that actually drops a label has never been produced
by a live decision and is covered only by the offline transport. The *document-side*
surface `app/rag/structure.py::extract_structured_blocks` remains unwired with its
original reasons (a metadata annotation with no per-field review slot and no consumer).
Every definition remains `shadow`; `live evidence = NOT_RUN` for all 19, and wiring a
call site is still not evidence of quality.

## Resume instructions for a later round

1. Work in `D:\CourseMate_COMPLETE_ARCHIVE_20260918\01_SOURCE_REPOSITORY`, branch
   `fix/codex-dsh-audit-20260919`; keep the pack files read-only.
2. Verify the tree first: `work/current-change/mig_probe.py` (schema/idempotency) and
   `work/current-change/verify_template_v2.py` (16 template hashes), then the targeted suites.
3. If credentials arrive: fill the env values yourself per the action card, then run the DeepSeek
   canary (text → structured → vision → tool replay) and the Jev calibration harness in
   `shadow` before switching any definition to `on`.
4. Only with explicit production authorization: back up the three databases, run migrations
   026–028 on an isolated restore first, then deploy an immutable release and execute the real
   browser acceptance.
