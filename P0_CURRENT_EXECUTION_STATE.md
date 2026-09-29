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

## What the next round has to do first

1. Take the trusted backup and prove a restore, and only then let anything write.
2. Freeze the new policy and run one bounded independent evaluation under the new
   prompt and schema versions -- the old numbers do not carry over.
3. Create the first real revision under the new author prompt, certify it, install
   a scoped qualification through the normal management entry point, and resolve
   the two SQL configurations.
