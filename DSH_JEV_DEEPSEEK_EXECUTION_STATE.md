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
| **B** CourseEntityResolution (`entity.relation.v1`) | `V3DomainAdapter._retrieve` (query expansion before the first recall; relation resolution after `fuse_scoped_candidates`) | accepted knowledge-node aliases expand the *query* (recall only, original query stays the prefix, explicit file/page targets skip expansion); resolved relations are written to the new **proposal-only** `entity_relations` store (migration 029, `status=PROPOSED`, `UNIQUE(left,right,relation)`, `used_jev`/`receipt_id` recorded, idempotent). Nothing merged/renamed/reordered/deleted. | `test_jev_entity_resolution.py` (18), `test_jev_shadow_invariance.py` (6) |
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

Every definition remains `shadow`; there is still no TypeSafe credential, so
`live evidence = NOT_RUN` for all 19 definitions and no quality claim is made for
any of them. Wiring a call site is not evidence of quality.

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
