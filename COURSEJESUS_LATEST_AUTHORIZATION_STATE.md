# Latest authorisation state

**What this file is:** the state of the owner's latest revision, item by item, with the evidence for
each one. It is written to be read first and to be checkable: every claim names a file, a test count
or a command that was actually run.

**Owner revision:** `D:\UserData\Downloads\DSH_COURSEJESUS_PAT_LOGO_CAMPUS_MODELS_PROMPT.md`
(462 lines) plus `C:\Users\Hp\Desktop\1.doc`, both read in full.
**Source revision:** `0e50252` at the last checkpoint (2026-09-24), tree otherwise clean apart from
the campus change landing in this same round.
**Nothing has been pushed, deployed or published.** `origin` is 140 commits behind this branch.

---

## 1. The eight items, and where each stands

### 1.1 Canvas as a user-authorised one-off import task — `CANVAS_TRANSIENT_PAT_IMPLEMENTED`

A pasted Canvas token is now held for **one import task**, in the service process only, and is
destroyed as soon as that task's Canvas reads are finished — before any parsing or indexing.

| Property the revision asked for | Implementation | Measured |
| --- | --- | --- |
| Held for the task, not stored | `app/canvas/transient_credential.py`, `bytearray` so `destroy()` zeroes it in place | `token_anywhere_in_database: false`; the app's own response contains no token; two receipt rows and neither holds one |
| Unusable immediately after the reads | the worker fetches in one pass, releases, then parses and indexes in a second | event log from the real worker: `["release:canvas_reads_complete", "indexing", "indexing"]`, `release_before_indexing: true` |
| Correct on success / warning / cancel / expiry / restart | six states, receipts per transition | success and cancel through the worker; `EXPIRED` (idle 30 min, hard 24 h) and `LOST_ON_RESTART` through the store; each with its own reason |
| No background sync | no reaper thread; expiry is applied on access and by an explicit `sweep()` | by construction, and the module has no `logging` import at all |
| Owner testing unblocked by the Developer Key | the path needs no school-side key | routes + store + worker + screen, all with tests; the **live** run is §1.7 |
| PAT capability vs public policy recorded separately | `docs/coursejesus/CANVAS_ACCESS_POLICY_STATUS.md` | `PAT_CODE_AND_OWNER_TEST` vs `PAT_PUBLIC_ROLLOUT_ELIGIBILITY = NOT_ELIGIBLE_WITHOUT_INSTITUTION_PERMISSION` |

Gates, all three enforced in code: `CANVAS_TASK_CREDENTIAL_ENABLED` (**default false**), a listed
account (`CANVAS_TASK_CREDENTIAL_USERS`, defaulting to the administrators), and the institution
registry. `ImportSelection` now sets `extra="forbid"`, so a credential posted to any other route is
a 422 rather than a silently ignored field.

Evidence: `docs/coursejesus/CANVAS_TRANSIENT_PAT_DESIGN.md`,
`CANVAS_CREDENTIAL_LIFECYCLE_EVIDENCE.md`, `work/current-change/canvas-credential-lifecycle-evidence.json`.

### 1.2 The two chat-pasted tokens — `OWNER_CANVAS_CREDENTIAL_REPLACED` (pending the owner)

They were **not** copied into any prompt, file, command, test, log or report: the values exist only
in the owner's chat history and must be revoked there. When the replacement is supplied through a
local hidden prompt, the live test runs with one command (§1.7). Nothing in this repository contains
either value, and a search of the tree for a token-shaped string finds none.

### 1.3 Official logo — `OFFICIAL_LOGO_INTEGRATED`

The owner's real artwork (`Codex 图像 2026年9月23日 01_20_02.png`, sha256 `ae536df4…be14e5`) is
stored unchanged, derived deterministically into seven served assets, wired into every brand slot of
the refreshed shell, the legacy header, both documents and the manifest, and guarded by 6 file-level
checks plus a browser journey. `docs/coursejesus/LOGO_ASSET_MANIFEST.md`.
**Honest limit:** this model cannot view images, so appearance was established by measurement (ink
bbox, colour histogram, per-asset hashes, rendered box sizes) and the screenshots exist for a human.
No human has looked at it yet.

### 1.4 Campus courses and student qualification — `CAMPUS_TYPE_AND_VERIFICATION_ENFORCED`

Campus courses stay `campus` with `requires_student_verification = 1`. The registration
**auto-grant is removed from both call sites** — including the one that was *inside* the access
check, where asking for a course is what opened it. `ensure_user` no longer accepts an
`auto_qualify` parameter, so no caller can reintroduce the grant, and `current_user` no longer reads
`campus_qualification_policy` when deciding who is granted anything.

Real verification is now distinguishable from the old registration-auto source:
`qualification_origin()` classifies a row as `real` (`code`/`admin`/`grandfathered`) or
`registration_auto` (`registered`), and `qualification_origin_counts()` counts the three classes
plus accounts with none — without naming anybody. No row was rewritten, downgraded or deleted: a
historical `registered` row keeps access under the unchanged default policy ("stop granting, do not
revoke"), and `verified_only` is available when the owner decides otherwise.

**The one decision, with its number unmeasured rather than estimated:** the count of accounts a
switch to `verified_only` would newly refuse must come from the deployment's own database, which
this round did not open. The read-only command is in
`docs/coursejesus/CAMPUS_VERIFIED_ONLY_MIGRATION.md` §6, and because a code redeemed after an
auto-grant leaves `method='registered'` for good, that number is an upper bound on "never really
verified" and should be cross-checked against `cmui_verification_codes`.

Verified: **162 campus-related tests pass** (51 + 111 across the suites this touches), the change
adds **zero** ruff findings against HEAD, and the diagnostic's read-only claim was checked by
hashing a seeded database before and after it ran. `docs/coursejesus/CAMPUS_VERIFIED_ONLY_MIGRATION.md`.

### 1.5 Model credentials — `MODEL_SPENDING_POLICY_APPLIED`, `DEEPSEEK_LIVE`

Parsed locally from the Word document through its piece table (the obvious text range gave 187
characters; the two candidates were disambiguated by asking each provider and reading the status
code, never by guessing at a prefix), installed into the protected store, never printed, never in
Git, never in the frontend. This round's necessary calls ran under
`owner_authorized_unlimited_for_this_workflow`, with the ceiling still recorded and no `99999`
anywhere. Live result: **10/10 roles completed**, USD 0.0079908 against a USD 0.0620016 ceiling.
`docs/coursejesus/MODEL_SECRET_IMPORT_AND_LIVE_RESULTS.md`.

### 1.6 Jev live validation — `JEV_LIVE_AND_EFFECT = PARTIAL`

`typesafe-sdk==0.7.0` was installed and three real decisions were run through the real gateway:
Choice **ok** (`ANSWER_AND_RESUME`), Noul **ok** (`0.9`), Score **`invalid_response`** — the provider
returns a continuous value (`3.99`, `3.92`, `1.3`, `0.0`), never one of the five level keys the
catalogue declares. The values are semantically right, and the level boundaries were deliberately
**not** invented: the catalogue's own `thresholds` says
`UNSET_UNTIL_CALIBRATED_ON_LABELLED_DATA`. Jev's live effect on user-visible behaviour is not
measured and is not claimed.

### 1.7 The owner's own small-sample live Canvas test — `CANVAS_OWNER_LIVE_TEST` awaiting a token

The runner exists and is tested: `scripts/canvas_owner_smoke_test.py` reads the token through a
hidden prompt (never argv), reads the identity, the readable courses, one course's file list and at
most three files under a size cap, hashes what it received, discards it, and destroys the credential.
It parses nothing, indexes nothing and creates no course, so a live run cannot change the product.
**It has not been run against a real school**, because that needs the replacement token.

### 1.8 Backup, migration, publish, acceptance — `PRODUCTION_DEPLOYMENT` / `PRODUCTION_ACCEPTANCE`: not started

Production has not been contacted: no deploy, no DNS change, no Clerk change, no database touched.
The sequence is backup → migration rehearsal (done locally at schema 34→35 for the rollback check) →
same-site publish → acceptance → final report, and it starts only when the owner asks for it.

---

## 2. What changed in this round, in order

| Revision | What it did |
| --- | --- |
| `c4ce32e` | Kept the brand screenshots a passing test deletes |
| `183c1f9` | The transient credential store and schema 35 |
| `dd02064` | One route may take a pasted token; the worker drops it before indexing |
| `bb9fbfc` | The owner's five-step screen, offered only when the server offers it |
| `61553c9` | The three Canvas documents |
| `0e50252` | The owner's live small-sample runner |
| `2d9efde` | Execution state: the new statuses, and a corrected "no credential input" claim |
| `a2ed067` | The live model results, including the Jev Score finding |
| `7e736fc` | The latest authorisation state, item by item |
| `57cd19c` | Campus: stop granting at registration, make the origin visible, keep every row |

Targeted results on this round's revisions (the full gate is owed once the tree is frozen with the
campus change):

| Suite | Result |
| --- | --- |
| `tests/test_canvas_transient_credential.py` | 17 passed |
| `tests/test_canvas_import_worker.py` | 32 passed |
| `tests/test_canvas_api_routes.py` | 36 passed |
| `tests/test_canvas_owner_smoke.py` | 8 passed |
| canvas + schema + database selection | **319 passed, 1 skipped** |
| Jev / gateway / structured | **391 passed** |
| campus + qualification suites after the change | **162 passed** (51 + 111) |
| web (vitest) | **107 passed** (23 files) |
| `tsc -b` (web, incl. node-side tests) | exit 0 |
| production build + PAT scan | exit 0 — `no token field, notice present` |
| `ui-refresh` browser journeys (Canvas + brand) | 4 passed |

---

## 3. The owner's own blockers, and nothing else

Two cards, both things only the owner can do:

1. **Revoke the two Canvas tokens pasted into chat, and supply a replacement through a local hidden
   prompt.** Until then the live small-sample test cannot run. Nothing else in this round is blocked
   by it.
2. **The school's Developer Key** remains the gate for the *public* Canvas OAuth path
   (`CANVAS_OAUTH_LIVE = WAITING_INSTITUTION`). No local work substitutes for it, and the new
   one-off path is the owner's own testing route rather than a replacement for it.

Plus one decision that is not a blocker, recorded where it belongs: whether the campus policy should
move to `verified_only` (which would require existing registration-auto users to verify), and how
the Jev `Score` level boundaries should be calibrated. Both are decisions, not defects, and both are
stated with the numbers in their own documents.

---

## 4. What is deliberately not claimed

* **No school approved the token path for students.** No institution has been asked, and the default
  configuration offers it to nobody.
* **The Canvas live paths are not verified against a real school** beyond the owner's own testing;
  the OAuth path has never completed a real callback.
* **Jev's live effect is not measured**, and the `Score` primitive cannot be used live until its
  level boundaries are a decision rather than a guess.
* **Nothing is deployed.** The production environment is exactly as it was.
* **The full backend gate has not been re-run on this round's revision.** Targeted suites passed;
  the full run happens once, on the frozen revision, and its number will be reported then.
