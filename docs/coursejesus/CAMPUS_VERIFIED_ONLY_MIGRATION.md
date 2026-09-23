# Campus qualification: stop the auto-grant, keep the history, name the gap

**Status:** `CAMPUS_TYPE_AND_VERIFICATION_ENFORCED` — the registration auto-grant is removed, real
verification is distinguishable from the old registration-auto source, every historical row is kept
exactly as it was, and the one decision the owner has to make is stated below with the command that
measures it.

**Revision:** working tree on top of `7e736fc`, measured 2026-09-24.
**Verifier:** the numbers in §4 were produced by the delegating round's own runs, not taken from a
description of them.

---

## 1. What the owner asked for

> New campus courses stay `campus` type and require valid student qualification; **stop auto-granting
> qualification to new registrations**; distinguish real verification from the old registration-auto
> source; keep historical evidence; delete no users/grades; distinguish origins or state the data gap
> and give one card.

## 2. What changed, and where

| Change | File | Why this is the right place |
| --- | --- | --- |
| The registration auto-grant is gone; `ensure_user` no longer takes an `auto_qualify` parameter at all | `services/rag-api/app/cm_update/auth.py` | The parameter existed only to call the auto-grant, so removing it makes reintroducing one impossible from any caller rather than merely unlikely |
| `current_user` no longer reads `campus_qualification_policy` | same file | The policy selects how *strict the gate* is. It must never decide who is granted a qualification, and that coupling is what produced the auto-grant |
| The campus access check no longer grants — it only reads | `services/rag-api/app/ui_extension/mount.py` | The old code called `ensure_registered_qualification` **inside the access check**, then read `verified`. An access check that writes is the defect, not a side effect |
| `campus_qualified()` added, and the shell gate uses it | `services/rag-api/app/cm_update/app.py` | One place decides, and it is read-only by construction |
| The refusal message changed | same file | It used to say "注册登录后将自动开通学生资格", which is now false. It now says a 7-digit code completes verification |
| `qualification_origin()` and `qualification_origin_counts()` added | `services/rag-api/app/cm_update/social.py` | Both are pure reads. The first classifies one row; the second counts the classes without naming anybody |
| `ensure_registered_qualification()` kept, documented as having **no production caller** | same file | Kept so the removal is auditable and any out-of-tree caller can be found by name. A grep of the repository finds only docstring references to it |
| `campus_qualification_policy` accepts `verified_only`, default unchanged | `services/rag-api/app/cm_update/config.py` | The default stays `registered_active`, so a deployment that changes nothing behaves as before |
| `verified_only` respected by **both** gates | `mount.py`, `app.py` | Both paths that can reach campus content honour the same policy, and the strict refusal uses the existing `STUDENT_VERIFICATION_REQUIRED` code rather than inventing one |
| A read-only diagnostic | `services/rag-api/app/cm_update/qualification_origin_report.py` | Opens the database with `mode=ro` **and** `PRAGMA query_only=ON`, refuses `write=True`, and prints three aggregate counts — never a subject id, a name or a code |

New tests: `services/rag-api/tests/test_codex_campus_qualification_origin.py`.

## 3. The deliberate decision: stop granting, do not revoke

A historical row with `method='registered'` **keeps campus access** under the default policy. That is
not an oversight; it is the decision this change takes deliberately, because the alternative would
revoke access from real students on the strength of a column that cannot prove they were not
verified (see §5).

`verified_only` exists for when the owner decides otherwise. It changes the gate, not the data:

| Policy | A `code`/`admin`/`grandfathered` row | A `registered` row | A new registration |
| --- | --- | --- | --- |
| `registered_active` (default, unchanged) | allowed | **allowed** | refused |
| `verified_only` | allowed | refused | refused |

Nothing in either setting makes an access check write a qualification.

## 4. What was measured

| Claim | How it was checked | Result |
| --- | --- | --- |
| A new registration is unverified and campus content is refused | the new test file drives the real routes | `{"verified": false, "method": null, "verified_at": null}`, no row in `cmui_verification`, campus content routes refused, metadata still `200` |
| A redeemed code still grants, and keeps `method='code'` | same file | refused before redemption (403) → redeemed → allowed (200), `method == "code"` |
| Origin classification is right | same file, five row shapes | `code`/`admin`/`grandfathered` → `real`; `registered` → `registration_auto`; no row, `verified=0`, or `verified=1` with no method → `none` |
| `verified_only` refuses a registration-auto row and allows a code row, through both gates | same file, a strict-policy app | the legacy route answers `403 STUDENT_VERIFICATION_REQUIRED`; the redeeming user is allowed; the strict run leaves `method='registered'` on the other actor's row untouched |
| The default policy still allows a historical auto row, and does not modify it | same file | allowed through both gates, classified `registration_auto`, and the rows read back byte-identical before and after |
| The counts name nobody | same file | the aggregate contains no owner id; the rows are unchanged by counting |
| The diagnostic is genuinely read-only | my own run of `work/current-change/verify-origin-report-seeded.py` on a database seeded through the package's own bootstrap | `{"none": 2, "real": 4, "registration_auto": 2, "total": 8}` against an expected 8, **`database unchanged by the report: True`** (SHA-256 before and after), and the in-process helper agrees. The seeded set includes an orphan verification row (owner absent), which the report counts through its `UNION` branch |
| The diagnostic copes with a database that predates the qualification table | the new test file | `{"real": 0, "registration_auto": 0, "none": 3, "total": 3}`, a message saying there is no `cmui_verification` table, and the file byte-identical afterwards |
| No regression in the surrounding behaviour | my runs: `test_current_change_features`, `test_codex_campus_access`, `test_codex_sharing`, `test_codex_identity_verification`, `test_codex_campus_qualification_origin` → **51 passed**; `tests/ui_extension`, `test_codex_grandfather_directory`, `test_codex_qualification_snapshot`, `test_four_change_migration`, `test_course_display_and_verification`, `test_codex_directory_upstream` → **111 passed** | **162 passed, 0 failed** |
| The change adds no lint finding | `work/current-change/ruff-delta-vs-head.py`, comparing `ruff --statistics` per rule against the same file at HEAD | **0 added**; the two new files are clean; three files lost one finding each |

## 5. The data gap, stated precisely

`cmui_verification` alone **cannot** prove real verification for one class of user: someone who
redeemed a 7-digit code **after** having been auto-granted. `redeem_code` deliberately refuses to
overwrite an existing verified provenance, so that user keeps `method='registered'` for good, even
though a real code was redeemed. They are counted as `registration_auto` by the helpers above, and
the corroborating evidence for exactly that case lives in:

* `cmui_verification_codes` — `owner`, `status='redeemed'`, `redeemed_at`, `audit`;
* `cmui_redemption_attempts` — the attempt log for the same owner.

The new test file pins this case on a real database (auto-granted, then redeemed, still
`registered`, with the redeemed code row asserted alongside). So:
**`registration_auto` is an upper bound on "never really verified", not an exact count.**

Two smaller ambiguities, for completeness: `grandfathered` covers three origins (the boundary
backfill, the approved Clerk snapshot, and the dev auto-verify flag), distinguishable only by the
free text in `boundary_notes`; and `verified_at` records the first authenticated request, not
registration, so a "registered before/after the policy change" boundary cannot be derived.

## 6. The one card

**Decision:** leave the policy at `registered_active`, or switch it to `verified_only`.

The number the decision needs is exactly how many accounts `verified_only` would newly refuse, and it
must be measured on the deployment's own database — this round did not open it, so **the count is
unmeasured here and is not estimated**. The command is read-only and prints three integers:

```
python -m app.cm_update.qualification_origin_report --database "$CMUI_DATA_DIR/ui.sqlite3"
```

Its output `registration_auto` is that number, and because of §5 each of those accounts should be
cross-checked against `cmui_verification_codes` (`status='redeemed'`) before the switch, since some
of them may be real verifications the qualification row cannot show.

Switching has no migration and no data change: it changes which rows satisfy the gate, nothing else,
and it is reversible by setting the variable back.

## 7. What this change does not claim

* **No historical row was rewritten, downgraded or deleted.** Every account keeps the qualification
  it had; the change stops new grants and makes origins visible.
* **The count is not measured here.** The production UI database is on the server and was not opened.
* **The gate is enforced in two places, and both were checked**, but the recon that preceded this
  change also found one path with no campus check at all — shared-overlay document bytes
  (`app/api/publication.py`), which can only serve `WORKSPACE_PRIVATE` sources, and a deployment
  that runs `v3_enabled` **without** `ui_extension_enabled` installs no authorizer at all. Neither
  is changed here; both are stated so the enforcement claim is not read as broader than it is.
* **The UI still labels a `registered` row as 已通过（注册自动开通）.** Under the default policy that
  is accurate. Under `verified_only` it would be misleading, and the label would have to change with
  the policy — noted, not done.
