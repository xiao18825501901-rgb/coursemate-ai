# Findings and fixes — chronological evidence

The early sections below preserve actual RED/intermediate states. Their “pending”
wording is historical, superseded by the continuation closure at the end and the
current REQUIREMENT_EVIDENCE_MATRIX.md. They are not current unresolved counts.

Baseline `9104b5a`; local audit branch `fix/codex-dsh-audit-20260919`.

## F03 / R11 — confirmed at mounted V3 HTTP boundary

DSH claimed question-only streaming. The original runner found the separator in
the accumulated response but sliced only the last delta. All five internal
separator splits disclosed the synthetic answer. Missing, damaged and duplicate
separators also failed privacy/validation checks. Initial regression: **8 failed**.

Fix: keep exercise output private until the completed response has exactly one
separator, a question and a parseable stepped answer. Commit only the question to
the public partial text and event ledger in the exercise transaction. Answer
remains stored and reveal returns that same version. Completion adapters may
extend an already received prefix; incompatible completions fail closed.

## R13 — pre-reveal step access confirmed

An owner who knew a valid step ID received HTTP 202 for explanation generation
without revealing the answer. New HTTP regression failed with 202 instead of
403. The route now checks the persisted reveal receipt before reading steps or
calling the provider.

## R07 — historical event replay confirmed

Injecting a synthetic canary into old prompt_ready text and nested coverage.error
made it visible over the mounted SSE endpoint. New regression failed. Public
event projection now applies on replay, uses a closed vocabulary, regenerates
status labels, omits arbitrary evaluator errors and excludes internal payloads.
Delivery receipt errors are also omitted from GET run. This is backend access
control evidence, not a claim of perfect model resistance to prompt extraction.

Validation after these fixes: **33 passed** across the new privacy regressions,
`test_current_change_features.py` and `tests/ui_extension/test_provider.py`.
External identity/model transport is synthetic; real V3 mount/database logic is
used by the API regression. Browser and real model NOT VERIFIED.

Remaining within R11: historical exercise deltas/partial text created by the old
bug, cancellation/reconnection, byte-boundary transport and broader history/share
surfaces require additional checks. Other R01–R18 work remains open in the matrix.

## Owner coordination checkpoint — 2026-09-19

The owner explicitly confirmed DSH has stopped modifying this D-drive repository.
This is owner-provided coordination evidence, not a claim that all machine
processes were independently terminated. HEAD remains `9104b5a`, branch
`fix/codex-dsh-audit-20260919`. Audit modifications remain uncommitted; no reset,
production access, model billing or push was performed.

## R14–R15 — private invitations and selected-history validation

Mounted V3 regressions initially failed for all three sharing cases: private
invitation hidden from its recipient, nonexistent selected Pair silently
accepted, and integrated files copied as zero despite a successful share response.

Invitation visibility now checks the authenticated recipient's share relationship
without granting access to the source course. Selected-history requests require
a nonempty selection and validate every Pair's owner and course; invalid IDs
return 404 rather than falling back to all history.

After these two fixes: `tests/test_codex_sharing.py` reports **2 passed, 1 failed**
in 12.72 seconds. The remaining failure is genuine: integrated snapshot file
copy/import is not yet implemented. The test is retained, not skipped or relaxed.
This is local mounted V3 integration evidence with isolated synthetic data and
fake external providers, NOT live-model, browser or production acceptance.

Command environment: CMUI_ENV=test, CMUI_PROVIDER_MODE=test,
CMUI_ALLOW_BILLABLE=false, CMUI_AUTO_VERIFY_NEW_USERS=false,
CMUI_COVERAGE_REVIEWER=none; project-local audit virtual environment.

## Continuation closure — 2026-09-19

| Confirmed defect | Genuine failure evidence | Correction and subsequent evidence |
|---|---|---|
| Integrated files absent | files_copied 0 instead of1 | V3 freeze/import service and receipt; three-file read/download/retrieval and sender-deletion/isolation tests |
| Import retry at full quota | existing successful file hit upload quota | Authorized existing-content check before quota; retry/concurrent tests |
| Same bytes in two authorized corpora collapsed | separate file entries lost | Preserve course/private corpus destinations; source→target mapping |
| Failed send required a new request/live manifest | retry503 instead of201 | Same frozen manifest resume, per-file index hash persistence, atomic ready/notices;17 related tests PASS |
| Selected unbound history accepted |201 instead of422 | Require actual bound Pair; all-history still supports unbound |
| Classification disappeared after sharing | recipient template_id None | Frozen classification/template evidence copied into recipient scope |
| Concurrent new message entered snapshot | synthetic after-snapshot message present | One history read transaction; regression PASS |
| Concurrent tree publication mixed specs | tree spec2 absent from old-spec snapshot | One knowledge export read transaction; independent1 RED→PASS |
| Missing-contract test asserted NOT_STARTED | expected state contradicted real contract | Correct synthetic fixture, retain SPEC_UNAVAILABLE assertion; no production weakening |
| Legacy campus histories still readable | revoked owner got200 | Central policy on original QA/history and list/mutations; negative tests retained |
| Same-owner wrong-course file path accepted | read/delete200 | Require membership in requested course's authorized file projection |
| Directory/verification flaws | six original endpoint failures | Opaque paginated directory, HMAC storage/migration, protected old-registration client; independent contracts |
| Late Pair load replaced a new selection | real browser restore regression | Pair revision checks and shared pending creation; backend exact-pair rules |
| Supplied problem had no persistent explanation target | missing exercise/answer version | Persist versioned steps and direct revealed state; actual run/step browser checks |
| Reveal/cached explanation ignored request payload | cross-target same ID returned200/202 | Durable full-hash action receipt; conflicts409 |
| Concurrent explanation setup raced | SQLite duplicate hidden conversation | After-retrieval transaction recheck/coalescing; same/different request tests |
| Silent cancel/restart left generating window | expired run failed but explanation generating | Periodic stream terminal check/close, projection CAS and atomic restart reconcile |
| Inbox tabs stayed on same tab | browser share card never appeared | setState uses selected id, not unchanged tab |
| Joined course inaccessible until reload | browser course route lacked new course in cached list | Await root course refresh after join |
| Attachment/resize controls absent from keyboard order | actual tabIndex=-1/Tab skipped/Arrow unchanged | Keyboard activation, movement and resizing; expanded browser checks |
| Step window code shown as plain text | DOM pre/code absent | Existing safe RichText renderer reused; independent RED→PASS |
| Standalone snapshot also lost files | joined course file list empty | New recipient IDs, verified bytes, parsed chunks, retry receipt and mapping;1 PASS |
| Windows final directory rename fails | real WinError5 in full suite and OS handle repro | Preserve/report staging, explicit verified resume and no-overwrite publication; original locker UNKNOWN |

Failures in an initial test fixture (wrong Pair DTO, invalid registry ID, browser
folder/ambiguous locator or shared synthetic rate budget) are not counted as
product defects. They were corrected without relaxing assertions or rate policy.
Browser tests use a separate explicitly verified synthetic actor for window model
calls, not global automatic verification. Paid model and production remain absent.

## Recovery continuation — 2026-09-20

- Original two Windows failures independently extracted from XML; a fresh baseline reproduced 1 failure/3 passes. Actual operation is final directory rename, not failed DB/archive validation. Original cause remains UNKNOWN. Resource tracking confirms our DB/file/tar handles are closed; an unrelated post-success test connection now closes explicitly.
- Bounded publication tests began 3 failures/1 pass, then passed. Real fresh CLI evidence recorded WinError5 then success after0.1s within one invocation. Persistent failure, target races, tamper rejection and explicit resume retain safety assertions. Root final33 passed. Old immediate raw OS rename after closing our test handle remained unproved; that post-close diagnostic now exercises the bounded application contract, while raw held-handle denial checks and failed XML stay intact.
- PREPARING had no controlled killed-worker recovery. Frozen recipient intent and OS-owned exclusion now support inspect/apply without source fallback or duplicate notification. Four dedicated worker-exit points pass; PID artifacts are retained. Review reproduced repeated/all-task cancellation releasing a lock before OS I/O completion; final executor-Future draining fixes both, independently reverified.
- WSL ext4 real runtime7 PASS, not mocks. DrvFS4 PASS/3 FAIL EINVAL retained and explicitly unsupported.
- Sidebar browser RED showed 190px code in123px width and no accessible full text. Name-first wrapping/focus/title fixes it without ID changes; final frozen-commit13 browser PASS.
- Historical local1937 chunks lack recorded embedding provenance; UNKNOWN remains, no paid rebuild or forged metadata.
- Scope exclusion: legal long course-name creation can generate a >50-character ID and500. Browser setup evidence is retained; sidebar test creates a short name then renames through the normal API. This separate creation defect was not folded into the limited UI fix.

See RECOVERY_GATE_AND_REMAINING_STATUS.md for current final regression and operational restrictions.
