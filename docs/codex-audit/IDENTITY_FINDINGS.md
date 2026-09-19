# Independent identity and verification regressions

Date: 2026-09-19. Scope: R16 and R18. Tests written independently before implementation fixes, against the D-drive source repository. No external identity lookup, model call, production access, or real qualification changes were performed.

## Observed failures

`services/rag-api/tests/test_codex_identity_verification.py`: **6 failed, 2 dependency deprecation warnings, 19.22 seconds**, exit 1.

| Requirement | Regression | Observed current behavior | Implementation pointer |
|---|---|---|---|
| R18 | Issued/redeemed secret absent from persisted records | Failed: plaintext remains in `cmui_verification_codes`. Source also writes plaintext to redemption attempts and verification boundary notes. | `cm_update/social.py`: `generate_codes`, `redeem_code`, `_attempt`; `cm_update/db.py` verification tables |
| R18 | Admin list exposes opaque `code_id`; disable by that ID actually prevents redemption | Failed at missing `code_id`; list exposes only redacted `code`. Later state/redemption assertions remain pending until this is implemented. | `cm_update/app.py`: `admin_list_codes`, `admin_disable_code`; `cm_update/models.py`: `VerificationDisable` |
| R16 | Empty search paginates 25 users | Failed: 0 returned across three pages. | `cm_update/app.py`: `people` |
| R16 | One-character search paginates 25 users | Failed: 0 returned across three pages. | `cm_update/app.py`: `people` |
| R16 | Longer search honors requested 10-item pages | Failed: 20 returned on first page; offset/limit not implemented. | `cm_update/app.py`: `people` |
| R18 | Failed protected old-user snapshot recovers on next startup, including old registered user absent from UI projection | Failed: recovered old user remains unverified. | `cm_update/app.py`: lifespan suppresses snapshot error; `cm_update/social.py`: `grandfather_existing_users` permanently writes boundary and skips IDs absent from `cmui_users`; `ui_extension/domain.py`: `verification.grandfather_candidates` only reads existing V3 ownership rows |

The HMAC claim is contradicted by actual persistence, not inferred from field names: issuance computes an HMAC but also stores the raw code; redemption computes `digest` but does not use it for lookup or comparison. The opaque-ID test deliberately stops at the first missing contract and does not claim the later disable-by-ID behavior has already been executed.

The directory tests accept either a legacy array or an `items` envelope, and use conventional `limit`/`offset` pagination. They exercise real mounted V3 UI routes with synthetic database records. They do not yet prove synchronization of registered users who never opened the UI; an identity-source client and fake HTTP upstream tests remain required for that separate contract.

The grandfather test uses the real UI lifespan and database, with a fake DomainPort only for the protected external snapshot boundary. It is not a live Clerk integration test.

## Reproduction

From the D-drive repository root in PowerShell:

```powershell
$env:CMUI_ALLOW_BILLABLE='false'
$env:CMUI_PROVIDER_MODE='test'
$env:CMUI_ENV='test'
$env:CMUI_AUTO_VERIFY_NEW_USERS='false'
$env:CMUI_DATA_DIR=''
$env:PYTHONPATH='services/rag-api'
& 'work/codex-audit/venv/Scripts/python.exe' -m pytest services/rag-api/tests/test_codex_identity_verification.py -q --basetemp=work/codex-audit/identity-test-temp
```

All data lives under the project-owned isolated pytest directory. Test fixtures use `test_current_change_features.client`, disable automatic verification, and inject authentication/embeddings. No existing database is opened. This records the RED state; the final audit must record subsequent GREEN verification separately.

## Storage correction and helper verification

The bounded verification-storage correction adds UI schema 7 without rewriting the historical schema-6 bootstrap. Migration rebuilds the code table with opaque `code_id` and unique HMAC, preserves issued/disabled/redeemed rows and redeemed owner tombstones, HMACs attempt records, and redacts seven-digit secrets from boundary notes. Populated legacy data requires an explicitly supplied configured verification secret; no fallback key is invented by the migration. A failed migration rolls back its table replacement and does not advance schema version. Logical redaction does **not** prove physical erasure of old SQLite pages, WAL files, or backups; retained backups remain sensitive.

Callsite contract: `db.initialize(verification_secret=social._secret(cfg))`. Admin routes must use `social.list_codes` and `social.disable_code`; issuance returns plaintext strings only in its creation response. Redemption checks HMAC, preserves leading zeros, and gives the same invalid reason for invalid/disabled/already-used codes. Grandfather application is atomic and creates missing user projections from protected snapshot IDs; caller must invoke it only after complete successful snapshot acquisition.

Storage-only test selection `-k 'schema6 or code_helpers or concurrent_redemption or snapshot_atomic'`: **4 passed, 6 deselected, 2 warnings, 7.77 seconds**. This verifies populated schema-6 upgrade and repeated initialization, missing-key migration refusal, retained tombstones and leading-zero redemption, opaque disabling, wrong-HMAC-key rejection, concurrent single-owner redemption and replay, atomic/one-time protected grandfathering. Endpoint wiring, external identity snapshot acquisition, and directory implementation remain the main agent's integration responsibility.
