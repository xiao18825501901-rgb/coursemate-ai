# P0 current execution state (2026-09-30, resumed round)

This is the short ledger the plan asks for: what is done, what is measured
failed, what is blocked and what has produced no business result yet.  It is not
an acceptance report, and it does not replace the seven documents the earlier
round wrote -- those keep their own results and are appended to, never rewritten.

## Work tree

```
REPO    D:\CourseMate_COMPLETE_ARCHIVE_20260918\01_SOURCE_REPOSITORY
        \work\auto-knowledge-map-20260927\candidate
branch  feature/learning-loop-20260928
HEAD    50a3560  (2f189df + 4fda9c9 + 50a3560)
prod    /srv/coursemate/current -> /srv/coursemate/releases/916b76c  (unchanged)
```

Nothing was reset, stashed, cleaned or force-pushed.  The untracked `artifacts/`
and `apps/web/public/downloads/` directories from earlier rounds are untouched.

## Done in this round, with the evidence for each

| item | state | evidence |
|---|---|---|
| Three zero-call diagnostics | **DONE** | `P0_ZERO_CALL_DIAGNOSTICS_20260930.md`; run on a verified copy, live DB fingerprint identical before and after |
| CS3481 hard-gate cause | **DONE (diagnosed)** | `qe_22cfcc081c3e4fa2899d53fd400671e2` fails only `INPUT_IDENTITY`; the recovery stage accepted the named `INTEGRAL_FLOAT_AS_INT` rendering and the validator compared the canonical hash alone |
| Provider failure census | **DONE (measured)** | 32 failures over 366 rows / ~798 reviewer calls = 4.01 %; every failed row is absent from the outcomes, so a failure costs coverage and is never a semantic negative |
| Nine-candidate disposition | **DONE** | 4 ambiguity-only, 3 substantive disagreement, 1 provider failure, 1 deterministic hard fail = 9, mutually exclusive and complete |
| Copy guard | **DONE** | `app/db_target.py` + 23 tests; refuses two production paths even when they agree, and checks realpath, samefile, inode, hard links, symlink components and containment |
| Provider failure ledger | **DONE** | migration 066 + `provider_failure_ledger.py`; the layer is now persisted with error class, terminal status, HTTP status, timeout kind, response arrival, latency and usage |
| Append-only call ledger | **FIXED and measured** | `INSERT OR REPLACE` did not fire the delete trigger (`recursive_triggers` is 0 on this runtime), so a conflicting call row was silently replaced; the writer is now a plain `INSERT` and the key includes the prompt and schema versions |
| Identity drift | **FIXED** | both stages go through `QuestionBlueprint.identity_under()`; the report records which rendering matched |
| Student-visible task contract | **IMPLEMENTED** | `app/learning/task_spec.py`; public projection rendered from the contract, four fact roles, a claim to critique is never a premise |
| Bounded profiles | **IMPLEMENTED** | `P-SQL`, `P-DISCRETE`, `P-COURSE-RULE`; a completeness certificate is issued by code and `NOT_SUPPORTED` is never a pass |
| Constructive ambiguity witness | **IMPLEMENTED** | `app/learning/ambiguity_witness.py`; inadmissible readings refused, equal answers under the declared equivalence refused, SQL readings executed by the oracle |
| Citation by span id | **IMPLEMENTED** | judge schema v4 and prompts v5; the server restores the frozen text, digest and locator into the receipt |
| Regression | **GREEN** | 266 passed, 1 skipped (this account cannot create symbolic links) |

## Not done, with the real reason

| item | state | reason |
|---|---|---|
| Read-only Schema-65 review and a new trusted backup | **NOT DONE** | the live fingerprint was recorded read-only (integrity ok, 65 rows in `schema_migrations`, provenance 49 READY / 9 NEEDS_REVIEW, zero hybrid rows) but the backup and the restore proof have not been taken |
| Provider timeout / retry audit | **NOT DONE** | the ledger now records `timeout_kind` and the cause chain, but no run has yet produced a failure through the new path, so there is nothing measured to report |
| Frozen independent evaluation | **NOT DONE** | requires billable provider calls under the new policy; the prompt and schema versions changed, so every previously measured number is now a different method |
| Qualification installed in production | **NOT DONE** | production still holds zero qualification rows |
| First real READY item | **NOT DONE** | the nine stored candidates carry no task contract, so none of them can be certified for a profile; they need a revision under the new author prompt |
| Two SQL configurations, five-question grading, N8 | **NOT DONE** | both configurations remain BLOCKED at 0/5; nothing new is publishable yet |
| Campus / private do-one | **NOT DONE** | same cause |
| Authenticated browser acceptance | **NOT DONE** | not attempted this round |
| Production deployment | **NOT DONE** | `916b76c` is still in service; migration 066 has not been applied to production |
| `QUALITY_NONINFERIORITY_EVIDENCE` | **UNKNOWN** | no paired same-sample gold exists; this is not claimed and is not used to stop the engineering work |
| `MAP50_13_PAUSED` | **PAUSED** | unchanged; no Map50 unit was started |

## Deliberate decisions taken this round, with their risk stated

1. **The contract is excluded from the revision identity.**  Including it would
   change the identity of every item written from now on and could not be
   reproduced for the rows already stored, which carry no contract.  It is bound
   instead through the public projection digest that the completeness certificate
   and every receipt carry.  The limitation is exact: a changed stem or condition
   forces a new revision because those are in the identity, while a changed
   contract under an unchanged stem invalidates the certificate rather than the
   revision.
2. **A bare ambiguity refusal no longer decides the case.**  Nine measured runs
   established that this reviewer over-reports an absent condition on sound items,
   so that verdict is answered by the server's own completeness evidence.  The
   accepted risk is a real defect the reviewer failed to substantiate on an item a
   registered profile nonetheless certifies; it is bounded by the certificate's
   checks, the six hard gates and the oracle, and it is why the profile registry
   is deliberately narrow.  The opposite error is not accepted: an unverified
   witness holds the item, and absence of a witness is never an approval.
3. **No fuzzy citation matching was introduced.**  Making the quotation optional
   removes transcription; it does not remove verification.  A supplied quotation
   still has to match the frozen text exactly.

## Copy-guard verification on the production host (measured, not simulated)

Run on the real host against the real production path
(`/srv/coursemate/data/releases/20260919T202006Z/rag.sqlite3`, mode 0640, uid 998,
`st_nlink` 1, writable by the process running the check), with no deployment
environment file sourced.  Every hostile case is refused with its own code:

| case | result |
|---|---|
| the argument alone names production | `DATABASE_TARGET_IS_PRODUCTION` |
| environment and argument **both** name production | `DATABASE_TARGET_IS_PRODUCTION` |
| environment names production while the argument names a copy | `DATABASE_TARGET_ENVIRONMENT_MISMATCH` |
| environment names a different, non-production file | `DATABASE_TARGET_ENVIRONMENT_MISMATCH` |
| a traversal path reaches production | `DATABASE_TARGET_NOT_EXPLICIT` |
| a **symbolic link** to production | `DATABASE_TARGET_IS_PRODUCTION` |
| a **hard link** to production | `DATABASE_TARGET_IS_PRODUCTION` |
| a copy outside the authorised root | `DATABASE_TARGET_OUTSIDE_ALLOWED_ROOT` |
| a path that does not exist | `DATABASE_TARGET_MISSING` |
| a writable purpose that declares no production path | `DATABASE_TARGET_PRODUCTION_PATHS_REQUIRED` |
| the wrong expected schema | `DATABASE_TARGET_SCHEMA_MISMATCH` |
| the copy declared as its own source | `DATABASE_TARGET_IS_SOURCE` |
| a distinct copy inside the root, from a declared source | **ACCEPTED** |
| the read-only probe calling `initialize()` | `DATABASE_TARGET_READ_ONLY` |
| the read-only probe issuing a write | `OperationalError` |

The live database was read-only throughout and is unchanged afterwards
(`integrity_check` ok, zero `hybrid_quality_receipts`).  Artifact:
`/srv/coursemate/validation/p0-diag/guard-check-20260929T205901Z.txt`.  This is the
case the previous rule could not catch: two paths that agree on production.

## Trusted backup and restore, proved (2026-09-30)

The newest recovery unit before this round was `coursemate-v2-20260928T200126.170700Z`,
taken 2026-09-29 04:01 — **before** the accidental migration 065.  There was no
post-incident recovery point.  There is one now:

```
VERIFIED_BACKUP=/srv/coursemate/backups/coursemate-v2-20260929T211151.109907Z
```

Produced by the project's own `ops/production_backup_window.sh` (one writer pause,
services restored afterwards), then verified and **restored once**:

| check | result |
|---|---|
| `sha256sum --check SHA256SUMS` | OK for every artifact |
| `rag.sqlite3` / `agent.sqlite3` / `ui.sqlite3` | `integrity_check=ok`, 0 foreign-key violations |
| uploads | 850 files, 1 191 756 901 bytes |
| UI shares | 16 files |
| release config | `releaseConfigIncluded: false` — no manifest was supplied, recorded rather than carried forward stale |

**Restore rehearsal** (`ops/restore_v2.py`, source = that unit, target = a
separate directory, live data directory never named):

| fact | restored | live |
|---|---|---|
| `integrity_check` | ok | ok |
| foreign-key violations | 0 | 0 |
| tables | 151 | 151 |
| schema rows / max | 65 / 65 | 65 / 65 |
| provenance | 49 READY, 9 NEEDS_REVIEW | 49 READY, 9 NEEDS_REVIEW |
| courses / documents / chunks | 87 / 850 / 22 909 | 87 / 850 / 22 909 |
| JEV receipts | 117 | 117 |
| question-engine provenance | 58 | 58 |
| uploads extracted | 850 files, 1 191 756 901 bytes | matches the manifest exactly |

**Every field is identical between the restore and live.**  The rehearsal target
was removed afterwards and the live services stayed active and healthy throughout
(`rag-api` and `agent-api` both returned `{"status":"ok"}`).

Disk after: 2.4 GiB free (the verified recovery unit is 1.7 GiB of that).

## Two production defects found while taking that backup

Both were pre-existing and both would have broken the deployment this round is
building toward.  Neither was caused by the work in this round, but the first was
**exposed** by it and is reported as such.

### 1. Release `916b76c` was deployed without the agent-api Node dependencies

`/srv/coursemate/current/services/agent-api` had no `node_modules`, and no release
on the host had one either.  The running agent process predated the 916b76c
cutover, so it kept serving until the backup window stopped it; the restart then
exposed the defect:

```
Error [ERR_MODULE_NOT_FOUND]: Cannot find package 'cors' imported from
/srv/coursemate/releases/916b76c/services/agent-api/dist/src/app.js
```

The service crash-looped (`NRestarts` climbing, 5 s apart).  **Repair**: installed
exactly what the release's own `package-lock.json` pins, into the release root,
then restored the release directory to mode 555:

```
npm ci --omit=dev --workspace @coursemate/agent-api --include-workspace-root
cors=2.8.6  express=5.2.1  helmet=8.3.0  openai=7.4.0  ajv=8.20.0
express-rate-limit=8.6.2  @clerk/express=2.1.55
```

Verified afterwards: `coursejesus-openjev`, `coursemate-rag` and `coursemate-agent`
all `active`, and `GET 127.0.0.1:28001/health` returns `{"status":"ok","service":"agent-api"}`.
This is a repair to a live release and is recorded as one; the proper fix is that
no release is published without its dependencies installed.

### 2. Every ops shell script shipped with CRLF line endings

The release tarball was packaged from a Windows working tree, so
`production_backup_window.sh`, `backup_v2.sh`, `restore_v2.sh`, `monitor_v2.sh` and
`production_switch_four_changes.sh` all arrived with CRLF.  On the Linux host bash
reads `set -euo pipefail` as an option named `pipefail\r`:

```
/srv/coursemate/current/ops/production_backup_window.sh: line 6: set: pipefail: invalid option name
```

So the backup, restore, monitor and release-switch wrappers **could not run at all**
as deployed.  A wrapper that silently cannot run is worse than a missing one: the
operator believes the backup happened.  The git index was already LF — only the
working tree the release was packaged from was not.

**Fix**: `.gitattributes` now forces `eol=lf` for `*.sh` and `*.py`, and the shell
scripts were renormalized to LF.  The backup in this round was then taken through
the project's own wrapper from corrected copies, which is how we know the wrapper
itself works.

### 3. The backup tool needed Python 3.11 but its wrapper uses the host's 3.10

`ops/backup_v2.py` imported `datetime.UTC` (3.11+), while `backup_v2.sh` and
`production_backup_window.sh` default to `python3`, which is 3.10.12 on this host:

```
ImportError: cannot import name 'UTC' from 'datetime' (/usr/lib/python3.10/datetime.py)
```

**Fix**: `backup_v2.py` and `monitor_v2.py` use `timezone.utc`, which works on both.
The backup above was taken with the host's `/usr/bin/python3` (3.10.12) through the
documented wrapper, which is the direct proof of the fix.

## A plain file copy of the live database is not a backup (measured)

While the verified recovery unit was being taken, an `scp` of the live
`rag.sqlite3` was also pulled to the development machine, to have an off-box copy.
It does **not** open:

```
bytes=688529408   sha256=71f5d98175388a0f02209bad9fbd9a0d813c299bb99ae98e4ff4dd4f4574f5b9
PRAGMA integrity_check -> sqlite3.DatabaseError:
  malformed database schema (akm-job-d8f8959c079a3a68e6d20bec9b2bdb6d)
```

The live file grew during the transfer (688 455 680 to 688 529 408 bytes), so the
copy is a torn snapshot.  This is exactly the failure the project's backup tool
avoids by using SQLite's own `backup` API under a writer pause, and it is worth
recording because it is the mistake a file copy looks like it should not make.
The torn copy was deleted and was never used as a backup; the evidence line above
is kept at `out/torn-copy-evidence.txt` in the round's work directory.

## One explicit HTTP policy for every paid model client

Measured on the installed SDK (`openai` 2.53.0):

```
DEFAULT_MAX_RETRIES: 2
DEFAULT_TIMEOUT: Timeout(connect=5.0, read=600, write=600, pool=600)
```

Three clients were constructed with neither argument and inherited exactly that —
`OpenAIAnswerProvider`, `DeepSeekAnswerProvider` and `OpenAIEmbeddingProvider`.
Two silent automatic retries mean one learner question could become three
billable provider calls with no record that the first two happened, which is the
opposite of "no silent automatic retry" and it corrupts every count of what was
sent.  The budget was equally unrecorded: five seconds to connect against ten
minutes to read — the asymmetry the plan warns about, where a short window is not
an operation timeout and a long read is not a deadline.

`app/provider_client.py` now owns the policy: every phase is named, every value is
finite and validated, the whole-operation bound is derived from the phases, and
`build_openai_client` refuses a non-zero retry count outright.  The learning
provider keeps its configured model timeout as the read and write budget and
records the policy on every run.  The four provider-run contracts gained an
optional `timeouts` field, so a stored run written before the policy still
validates.

A source-level guard in `tests/test_provider_timeouts.py` asserts that no module
outside `provider_client.py` calls `OpenAI(...)`: inheriting the defaults is
silent, which is why the guard is at the source level and not only at the call
site.

## The first code-certified live item (2026-09-30)

A bounded live probe (`--diagnose-only --kinds NUMERIC --per-type 1`, two provider
calls: one author, one blind solve) now produces an item whose student-visible
task contract the server certifies:

```
author_failures:        []
task_contract:          true
profile:                P-DISCRETE v1
declared conventions:   ANSWER_FORM, BOUNDARY_INCLUSION, DATA_COMPLETENESS
fact roles:             GIVEN
answer equivalence:     EXACT
certificate_status:     COMPLETE_FOR_REGISTERED_PROFILE
certificate_failing:    []
projection:             1029 chars, digest 3c48deea9e87926817d9180135522c6d34c85d804af20db9e6d7de4034b82bbd
```

This is the positive path the round was built to reach: the author states what the
learner can see, the server renders the public projection from that contract, and
completeness is certified by code against a registered profile rather than asserted
by a reviewer.  The item is not published yet -- that needs a scoped qualification
installed through the normal management entry point.

### Four defects the probe found before deployment

The probe cost six author/blind calls in total across four iterations and found
four defects that local fixtures could not show, because the fixture provider
returns before the response is ever read:

1. **Every live call would have failed.**  The complete response was written into
   the run dict before schema validation, and the run dict is the receipt shape
   that `AuthorProviderRun` validates with `extra="forbid"`.  Symptom:
   `2 validation errors ... response_text Extra inputs are not permitted`.  The
   response and the rejection reason now live in local variables and are attached
   only to the failure, which is read rather than validated.  A regression test now
   drives the live branch and asserts the run carries only receipt keys.
2. **A closed enum destroyed whole paid calls.**  An invented convention key made
   `QuestionAuthorOutput` validation reject the entire response.  Convention keys
   and fact origins are now bounded free strings, and the *certificate* enforces the
   known set: an unrecognised key fails a check that names it instead of discarding
   the work.  Same for `role`, which stays closed because it is semantic.
3. **The rendered projection exceeded its own bound.**  `PublicProjection.text`
   inherited the single-statement limit of 800 characters, and a live item rendered
   1029.  The renderer raised instead of returning the block the learner is
   supposed to see.  It has its own bound now, with a regression test.
4. **The author context was defined twice and drifted.**  Adding the profile
   registry to the author call silently made every item's author receipt stale, and
   the symptom was a READY item quietly becoming NEEDS_REVIEW with
   `AUTHOR_PROVENANCE_INCOMPLETE`.  `author_context()` and `author_input_hash()` are
   now the single definition, used by both the call and the currency check.

Two further changes were required by what the probe measured rather than by
inspection: the prompt now carries an explicit JSON skeleton for the contract (the
model had returned `fact` instead of `statement`), and the server's profile registry
travels in the author context so the model chooses against the registered
requirements instead of its own idea of them (it had claimed P-SQL for a NUMERIC
item and declared conventions that profile does not accept -- correctly refused, but
the model had never been told what each profile requires).

Still true: **a diagnosis-only probe authors items; it publishes nothing.**

## What the next round has to do first

1. Take the trusted backup and prove a restore, and only then let anything write.
2. Freeze the new policy and run one bounded independent evaluation under the new
   prompt and schema versions -- the old numbers do not carry over.
3. Create the first real revision under the new author prompt, certify it, install
   a scoped qualification through the normal management entry point, and resolve
   the two SQL configurations.
