# CHATGPT REVIEW — CURRENT STATUS AND BLOCKERS

Single self-contained status report for the CourseMate (DeepSeek + TypeSafe Jev) recovery round.
Everything below names its revision, its command and its log path. Nothing here is a percentage, a
"PASS total", or a claim that a shadow receipt is a business effect.

**Audited at:** 2026-09-22 (local, +08:00), branch `fix/codex-dsh-audit-20260919`.
**Companion documents:** `docs/recovery/CURRENT_BLOCKER_LEDGER.md` (one row per open item with its
status class) and `docs/recovery/OWNER_ACTIONS_ONLY.md` (the four things only the owner can do).

---

## 1. Repository identity

| Item | Value |
|---|---|
| Git root | `D:\CourseMate_COMPLETE_ARCHIVE_20260918\01_SOURCE_REPOSITORY` |
| Branch | `fix/codex-dsh-audit-20260919` |
| HEAD at audit start | `7e2e4db7cf99d85f92a82c9f97d72729fdaa5162` ("Record round 30's final revision and correct three stale deliverable claims", 2026-09-22 13:31 +08:00) |
| Revision this round produced | `33c3fef` — everything in §5, with the gate in §6 re-run on that tree (`git diff HEAD -- services/rag-api benchmarks` is empty) |
| Working tree | clean at audit start |
| Remote | **42 commits ahead of `origin`, nothing pushed** (no push without approval) |
| Application SHA in production | `4ef5064` — **untouched by this work**; production has only ever been read |
| Schema | source `LATEST_V3_SCHEMA_VERSION = 30`; production live DB is **25** (026–030 not applied) |

This round's changes are committed on the same branch (see §6 for the exact SHAs and the evidence run
on each). No history was rewritten, nothing was reset, and no earlier failure evidence was deleted.

## 2. Report set read for this audit, and which version wins

24 report files were read in full and inventoried (path, internal date, named SHAs, modules, what each
supersedes, what each explicitly does not cover). The load-bearing facts:

| Question | Winning document | Note |
|---|---|---|
| What is the current revision? | `FINAL_COURSEMATE_JEV_DEEPSEEK_PRODUCTION_REPORT.md` §2 | It names the revision the release would ship; older `b8104d9`/`5be2d0a` references in it were corrected in round 30 |
| What is wired? | `JEV_CALLSITE_MATRIX.md` table 2 + `FINAL_COURSEMATE_JEV_STRUCTURED_ENHANCEMENT_REPORT.md` §5 | 12 case call sites + 13th (extraction field grounding) + all six modules + P2 |
| What is production? | `FINAL_COURSEMATE_JEV_DEEPSEEK_PRODUCTION_REPORT.md` §4 + `docs/jev-structured/MIGRATION_AND_ROLLBACK.md` | read-only verification 2026-09-22T01:59Z |
| What is the budget state? | `MINIMAL_OWNER_ACTION_CARD.md` §1b | **every figure is proposed, none approved**; USD left to the owner |

Historical documents (kept, not deleted, and now dated in place): `DSH_JEV_DEEPSEEK_PAUSE_AND_HANDOFF_REPORT.md`
(frozen at `6b85df7`, schema 28, production `5ba6a3a` — superseded), `FINAL_COURSEMATE_JEV_DEEPSEEK_RELEASE_REPORT.md`
(same era), `JEV_ABLATION_AND_PRODUCTION_ACCEPTANCE.md` (A/B/C/D only, 200/40/30 dataset *plan*).

Two files were found to be **internally inconsistent** and were corrected this round rather than
reconciled silently: `FINAL_COURSEMATE_JEV_STRUCTURED_ENHANCEMENT_REPORT.md` §7 quoted a stale mypy
count (1068/38) against its own §5 table (1074/39), and `LEARNING_AND_ASSESSMENT_STATE_SPEC.md` §2.5
implied the production migration target was 026–028 when `029` and `030` now exist.

## 3. What is actually finished (with the evidence that says so)

Claimed **finished and verified on a named revision**:

1. **12 case call sites wired and reachable** — single shared `SemanticDecisionService` threaded
   through `main.py` → orchestrator → UI extension mount → cm_update → adapter, plus the two internal
   APIs. Pinned by `test_jev_orchestrator_wiring.py`.
2. **All six structured modules wired with a consumer** — A extraction (query-side exact locator),
   B entity resolution (proposal-only relations + per-concept query expansion), C evidence consistency
   (per-source signal + conflict note into the teaching prompt), D claim/citation audit (pre-generation
   bundle + post-generation card audit), E capability router (consumes `skill_id` → `teaching_flow`),
   F tool-intent gate (opt-in, default `off`). Per-module entry points, authority boundaries and tests
   are tabulated in `JEV_CALLSITE_MATRIX.md`.
3. **P2 user feedback** — durable queue (migration 030), consent enforced by a schema CHECK, admin
   reader + own-list endpoint, shell entry.
4. **Local gates**: full backend regression and the four browser suites, re-run on the revisions this
   round produced — see §6 for the numbers and log paths.
5. **Frozen measurement assets preserved**: the 310-sample dataset and its split manifest are asserted
   unchanged by test (`content_hash 2af0f40d…`).

## 4. What is NOT finished, and why — by status class

The ledger carries 28 rows with full detail; the summary:

| Status | Count | Representative items |
|---|---|---|
| `RESOLVED_WITH_EVIDENCE` (this round) | 14 | module-D resolver type errors; missing QA-stream evidence bundle; `is_definitive` having no caller; the five module metrics being uncomputable; six documentation claims that did not match the code |
| `LOCAL_IMPLEMENTATION_GAP` (open, mine) | 1 | the `definitive` flag is in the API but the shipped UI does not render it yet |
| `WAITING_CREDENTIAL` | 2 | live Jev validation; live DeepSeek validation |
| `WAITING_BUDGET` | 1 | a real token/USD ceiling (all current figures are proposals) |
| `WAITING_PLATFORM_ACCESS` | 1 | one real sign-in for production acceptance |
| `WAITING_OWNER_DECISION` | 3 | document-side extraction surface; backup timer; Netlify publish method |
| `WAITING_PRODUCTION_APPROVAL` | 4 | boot-enable the two service units; the model switch; the migration/backup rehearsal; the push |
| `QUALITY_NOT_DEMONSTRATED` | 1 | no definition may leave `shadow` until a measured quality gate exists |
| `LIVE_PROVIDER_FAILED` / `UPSTREAM_UNAVAILABLE` | 0 | no live call has failed, because none has been attempted |

Distinctions the ledger keeps explicit, because collapsing them is how a report lies:

* **not implemented** vs **implemented but not verified** — e.g. the Jev adapter exists and fails typed
  without a key; that is not the same as a provider contract being verified.
* **provider call succeeded** vs **the business uses the result** — the six modules consume their
  decisions in code; none of that has been exercised against a live model.
* **shadow receipt** vs **`effect_applied`** — every deployment so far is `shadow`, so `used_jev` is
  `false` everywhere and the deterministic value is what the learner sees.
* **missing data** vs **a model that failed** — until this round five module arms had *no labels at
  all*; that is now fixed, and it was never evidence about model quality.
* **account lacks permission** vs **a wrong SDK call** — nothing suggests an SDK defect; no credential
  exists to test with.

## 5. What this round actually closed (the local work, not the report)

1. **Two real type errors, one of them a genuine bug shape** — `app/jev/citation_evidence.py` passed a
   plain `str` where `RetrievalAccess` requires `Literal["official","mine"]`, and returned `Any` from
   three functions. Fixed; the file is now mypy-clean (`mypy app/jev/citation_evidence.py` → no issues).
2. **`is_definitive` had no caller, and the API conflated two different things** — the assessment
   reference-solution gate returned `verified: true` when only layer 1 (existence/authorization) had
   run. With no credential layer 3 never runs, so **every** reference solution looked verified. It now
   reports `verified` (layer 1 clean) and `definitive` (a real `SUPPORTED`/`CONTRADICTED` verdict)
   separately, using `citation_audit.is_definitive` as the single source of that rule.
3. **Module D reached its second shipped path** — `QaService.stream` (`POST /api/qa/chat`, a live
   endpoint) produced citations with no evidence-bundle annotation. It now runs the same bundle
   (≤2 calls: select one span, judge that span) and marks the selected card. With the layer genuinely
   absent the cards are byte-identical; with a configured-but-uncredentialed layer they carry
   `UNVERIFIED`/`false` — the same honest shape the UI path has used since round 25.
4. **The five module metrics were not merely "data-poor" — they were uncomputable.** Investigating why
   `INSUFFICIENT_SAMPLES` persisted led to the real cause: the runner had **no result collection** for
   those definition families, so `extraction_false_acceptance`, `extraction_false_rejection`,
   `entity_false_merge`, `entity_missed_alias`, `entity_conflict_false_positive`,
   `condition_distinction`, `capability_misroute`, `tool_false_allow` and `tool_false_block` could not
   be produced for **any** dataset. All ten metrics (plus two for P2 feedback) are now implemented,
   each with its population stated in the docstring and its denominator published next to the rate, so
   a `0.0` with an empty denominator cannot be mistaken for a clean result.
5. **A companion labelled dataset removes the data gap without touching the frozen one** — 49 samples,
   7 per definition, for exactly the seven definitions that had none: 6 `OBJECTIVE_VERIFIED` (each
   naming a deterministic rule verified in the code, e.g. `entity_resolution._classify_pair` and
   `evidence_consistency._narrow_pairs`), 41 `SOURCE_REVIEWED`, 2 `DISPUTED` with both readings
   recorded, **0 `SILVER_DEEPSEEK`** because no model was called. ~73% negative/edge cases, 33 en / 16 zh.
   The frozen dataset and its split manifest are asserted unchanged by test.
6. **Six documentation claims that contradicted the code were corrected where they stood** — module C
   described as `MODULE_ONLY`/"no call site" though it was wired in round 24; entity relations
   introduced as an unwired stub; "pending catalog registration" stated as current for two definitions
   that are registered; three module status lines stale in the existing→new mapping; plus the two
   internal inconsistencies in §2. Two *suspected* defects were checked and found **not** to be
   defects, and that is recorded too: `image_transcription.v1` is a deliberately supported non-catalog
   case set (the harness validates it separately), and the capability catalog's `handler` strings are
   documented metadata, not dispatch.

Two of my own first-draft claims were wrong and were corrected in place rather than left standing: I
first recorded the retrieval re-rank as "40 calls per page, fixable by batching" — it is bounded at
**16**, and the batching I proposed is not available for that shape (`JevCall` shares one state across
its questions, and per-candidate scoring has a different state per candidate). And I first asserted the
QA stream would be byte-identical without a credential — `create_app` **always** builds a service, so
"no credential" is not "no layer"; only `jev=None` is byte-identical.

## 6. Evidence for this round

| Gate | Result |
|---|---|
| Full backend regression | **1252 passed / 0 failed** in 1681.27s (exit 0) — `work/current-change/full_run_round31.log` |
| Browser journeys (real Chrome, real three services, injected identity) | **32 journeys / 0 failed** — `ui-refresh` 19, `jev-structured` 6, `coursemate` 4, `learning` 3 |
| Measurement / module-metric suites | **113 passed** (`test_jev_module_metrics.py` 13 of them) |
| ruff | **1815 errors at the pre-change revision and 1815 after** — identical, measured against a `git worktree` of `7e2e4db` rather than asserted |
| mypy | `app/jev/citation_evidence.py` is now clean (`mypy app/jev/citation_evidence.py` → no issues); the whole-app count of pre-existing legacy errors is unchanged by this round |

The regression delta is exactly accounted for: 1235 → 1252 = the 4 new QA tests (25→29 in
`tests/test_qa_api.py`) plus the 13 new tests in `tests/test_jev_module_metrics.py`.

### 6.1 Backend regression

Command: `services\rag-api\.venv\Scripts\python.exe -m pytest -q -p no:randomly`
Log: `work/current-change/full_run_round31.log` → `1252 passed, 2 warnings in 1681.27s (0:28:01)`, exit 0.

### 6.2 Browser journeys

Command: `pnpm exec playwright test -c playwright.<ui|jev|config|v3>.config.ts` (four suites, real Chrome
via `C:\Program Files\Google\Chrome\Application\chrome.exe`, isolated injected identity — no production
Clerk). Result: 19 + 6 + 4 + 3 = **32 passed, 0 failed**. The journeys that exist, and the ones that
cannot yet exist because they need a live signal, are itemised in `JEV_CALLSITE_MATRIX.md`
§"Browser journeys: what exists, what cannot exist yet, and why".

## 7. External operations and money

* **Live model calls made this round: 0.** Jev live: 0. DeepSeek live: 0. Embeddings: 0.
* **Money spent this round: 0.** The only external contact in this work has been read-only production
  inspection in an earlier round (recorded 2026-09-22T01:59Z, variable *names* only, never values).
* **Approved budget: none.** `MINIMAL_OWNER_ACTION_CARD.md` §1b lists proposed ceilings (≤1,700 paid
  calls / ≤7.0M tokens; USD 15 + 10 + 2 = 27 combined) and explicitly leaves the USD number to the
  owner. I did not treat any of it as approval, and I did not spend anything.
* **Credentials:** no `TYPESAFE_*` or `JEV_*` variable exists in `/etc/coursemate/*.env`; no DeepSeek
  key is present either. Nothing has been requested in chat; only variable names appear in the reports.

## 8. Production: touched? deployed? accepted?

**No / No / No.**

* No deployment, no migration, no service restart, no DNS change, no publish, no production data write.
* Production is still release `4ef5064`, schema 25, Qwen models, and the published CS3481/GE2324 trees
  were not regenerated. SRSZQ is untouched.
* Two production risks remain **recorded and unfixed by design** (they are owner actions): both
  `coursemate-rag` and `coursemate-agent` are `disabled` at boot although they declare
  `WantedBy=multi-user.target` (the next reboot is an outage), and no CourseMate backup timer exists,
  which is why `coursemate-monitor` reports `failed` on a 32-hour-old snapshot.
* Because nothing is live-verified and every definition is still `shadow`, the correct overall verdict
  for the release is **PARTIAL — release-ready locally, unverified in production**, not "deployed and
  accepted".

## 9. What is genuinely left for the owner

Exactly four actions, each with its scope, platform and reversibility spelled out in
`docs/recovery/OWNER_ACTIONS_ONLY.md`:

1. Put a **TypeSafe Jev credential** into the protected backend env (`TYPESAFE_API_KEY`) — unlocks live
   validation, calibration and the ablations.
2. Put a **DeepSeek key** in the same protected env and **confirm one ceiling** (calls / tokens / USD) —
   unlocks the live acceptance run. (One number, not a key, is needed from you.)
3. Approve or defer a **production window** — plus two 10-second decisions inside it: enable the two
   service units at boot, and add a backup timer (or relax the monitor threshold).
4. Answer one **product question** about the document-side extraction surface (leave it unwired / add a
   per-field review slot with a consumer / flag-only), because building an annotation nothing reads is
   the pattern this project refuses to count as integration.

I will not ask for keys, tokens or passwords in chat, for blanket admin rights, or for a production
database copy in a shared location.

## 10. Dependency order from here

1. Owner: action 1 + 2 (one message with a ceiling) → 2. Jev + DeepSeek canaries in `shadow` (bounded,
   logged with call/token counts) → 3. calibration on the calibration split only, thresholds
   pre-registered → 4. the A/B/C/D/E and module arms on the frozen + companion datasets, test split
   touched only once → 5. promotion decisions per definition (retrieval re-rank first, plus at least
   one of context/intent/pedagogy) → 6. owner: action 3 (production window) → 7. read-only production
   re-verification → consistent backup → isolated restore → migration 026–030 rehearsal → rollback check
   against `4ef5064` → immutable release → protected env → frontend build → publish → real acceptance →
   post-release backup and monitoring → 8. push and final report.

Everything in steps 1–2 of that chain is owner-gated; nothing else in the list is.

## 11. Facts I could not confirm

* **Live provider behaviour of any kind** — no credential, so no prompt conformance, no latency, no
  real cost, no failure-mode data. Any statement about how the live Jev or DeepSeek behaves is
  unverified, including that the SDK call shape is accepted by the real service.
* **Production state as of today** — the newest production facts I hold are from the 2026-09-22T01:59Z
  read-only pass; uptime, disk, backup age and service health may have changed since. They will be
  re-verified before any release step.
* **Whether the extended dataset is sufficient for calibration** — 7 samples per definition is a
  starting population. `entity.relation.v1` drew no calibration-split group at all, so its thresholds
  cannot be fitted until it has more groups. I am not claiming the dataset is adequate; I am claiming
  it is real, validated, and no longer empty.
* **Teaching-quality effect of anything** — unmeasurable without the live ablation. No threshold was
  invented, nothing was promoted, and no number in this report should be read as a quality result.
