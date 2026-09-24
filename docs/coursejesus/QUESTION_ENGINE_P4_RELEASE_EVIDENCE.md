# Question Engine P4 local release evidence

Date: 2026-09-25

Branch: `fix/codex-dsh-audit-20260919`

Application revision: `df8694b0b4d97347f1c75baaca70c7e725e94a6e`

## Verdict

P4 is **locally complete** for this application revision. The wider regression, browser journeys,
synthetic backup/restore, schema-25-to-38 rehearsal and old-release compatibility gate all pass.
This is a local release-candidate verdict only. No production service, Clerk tenant, DNS/hosting
control plane, live DeepSeek endpoint or billable TypeSafe/Jev endpoint was contacted.

## Stop-the-line defect found by the first full regression

The first P4 full run on application revision `f00f3e3` was intentionally preserved:

- `1806 passed, 2 skipped, 11 failed, 3 warnings`;
- log: `work/current-change/full_run_coursejesus_p4_f00f3e3.log`;
- JUnit: `work/current-change/full_run_coursejesus_p4_f00f3e3.xml`.

Two failures were an executable-documentation mismatch: the Jev callsite matrix still described 21
definitions and two Question Engine signals after the catalog had gained two specialized signals.

The remaining nine failures exposed one restart defect. A schema-38 database can legitimately hold
five `QUESTION_AUTHOR` and five `QUESTION_BLIND_SOLVER` reservations in one operation. On restart,
`Database.initialize()` replayed historical migration 027 before migration 038. Migration 027
temporarily restored the old role enum and old `UNIQUE(workspace_id, operation_id, role)` constraint,
so copying the current rows failed before 038 could rebuild the ledger again.

The fix keeps the historical SQL immutable. When migration 38 is already recorded, initialization
skips migration 027's superseded replay; fresh databases and pre-38 upgrades still execute 027 followed by
038. A regression test inserts repeated Question Engine roles, restarts initialization, and verifies
both rows, SQLite integrity and foreign keys. The Jev matrix now lists all 23 definitions and all four
separately receipted Question Engine signals.

## Focused correction evidence

| Gate | Result |
|---|---|
| Original 9 restart failures + new restart regression + Jev matrix | **15 passed** |
| Migration, schema rollback, assessment preparation, Question Engine and backup/restore group | **64 passed**, 1 dependency warning |
| Focused Ruff | pass |
| Python byte compilation | pass |
| Git diff check | pass |

## Exact-candidate regression

| Gate | Result | Evidence |
|---|---|---|
| Full RAG/backend suite | **1818 passed, 2 skipped, 0 failed**, 3 warnings, 1036.89 s | `work/current-change/full_run_coursejesus_p4_df8694b.log`; `full_run_coursejesus_p4_df8694b.xml` |
| Web unit | **115 passed** across 25 files | `work/current-change/p4-web-test-df8694b.log` |
| Web typecheck | pass | `work/current-change/p4-web-typecheck-df8694b.log` |
| Production-shaped Web build and PAT scan | pass; 7 built files, no token field, notice present | `work/current-change/p4-web-final-production-build-df8694b.log` |
| Agent unit | **92 passed** across 12 files | `work/current-change/p4-agent-test-df8694b.log` |
| Agent typecheck and build | pass | `p4-agent-typecheck-df8694b.log`; `p4-agent-build-df8694b.log` |
| Real-Chrome integrated audit | **15 passed**, 0 skipped/unexpected/flaky, no retry | `work/codex-audit/browser-1790293339997-11296/playwright-report.json` |
| Real-Chrome V3 image/text learning | **3 passed** | `work/current-change/p4-browser-v3-df8694b.log` |
| Real-Chrome refreshed shell | **23 passed** | `work/current-change/p4-browser-ui-df8694b.log` |
| Real-Chrome structured Jev/default-unavailable shape | **12 passed, 5 expected configuration skips**; 0 reload recoveries | `work/current-change/p4-browser-jev-df8694b.log` |
| Real-Chrome base CourseMate journeys | **4 passed** | `work/current-change/p4-browser-coursemate-df8694b.log` |

The two backend skips are the already documented Windows environment cases: unprivileged symlink
creation and POSIX permission-bit behavior. The three warnings are dependency deprecations. They are
not relabeled as passes, and no test or assertion was removed.

The key Chrome screenshots were inspected at original resolution:

- `work/codex-audit/browser-1790293339997-11296/browser-results/codex-audit-Question-Engin-5a2a2-nswers-private-until-reveal/practice-light.png`;
- `work/codex-audit/browser-1790293339997-11296/browser-results/codex-audit-Question-Engin-5a2a2-nswers-private-until-reveal/practice-dark.png`;
- `work/codex-audit/browser-1790293339997-11296/browser-results/codex-audit-empty-assessme-8bafe-ntary-Question-Engine-slots/five-question-slots.png`.

They show the two-pane practice state in both themes and the frozen five-question `10/15/20/25/30`
assessment without pre-submit answer material. All browser fixtures are explicitly labeled synthetic
and use isolated databases, identities and fake provider/Jev transports.

## Candidate backup, restore, migration and rollback

The rehearsal used the preserved synthetic schema-25 source at
`work/current-change/rehearsal-r81-source.sqlite3`; it did not read a production database.

1. `ops/backup_v2.py` created a checksummed recovery unit under
   `work/current-change/p4-backups-df8694b/`.
2. `ops/restore_v2.py` verified it and published one fresh isolated restore at
   `work/current-change/p4-restored-df8694b/` without resume.
3. `scripts/rehearse_v3_migration.py` copied that restored database, applied migrations through 38,
   called initialization twice, and reported:
   - `old_rows_unchanged: true`;
   - `integrity: ok`;
   - `foreign_key_violations: 0`;
   - versions 1 through 38 present;
   - `v3_invariants_ok: true`;
   - no missing governance schema objects.
4. `scripts/verify_rollback_compat.py` compared the migrated candidate with preserved release
   `4ef5064` and returned `ROLLBACK_SAFE_WITH_MIGRATED_DB`, with no missing/retyped/narrowed schema
   dependencies and an unchanged Assessment pool predicate.

Evidence:

- `work/current-change/p4-backup-df8694b.log`;
- `work/current-change/p4-restore-df8694b.log`;
- `work/current-change/p4-migration-rehearsal-df8694b.json`;
- `work/current-change/rollback-compat-4ef5064-df8694b.json`.

Key evidence SHA-256 values:

| Artifact | SHA-256 |
|---|---|
| first failed full-run log | `eb73c63b23d33a6090c568928b0ec18f81b9fdbddaecd484990dc6cd3a3599b6` |
| first failed full-run JUnit | `b931fa0bc58c8c45be4be3292ead4636e3d401eb6d3f6495de437a0bda067419` |
| fixed-candidate full-run log | `59696811d40c0d9fa53ee93b572bf84c4fbccd459138915633c56c863e05c88e` |
| fixed-candidate full-run JUnit | `b8c739dd7919a1636dfbe0ff6cb062307eeb21dd2a758935dc7d7d71f66eccd7` |
| migration rehearsal JSON | `84387f8623210234b3ab301a5cf8fdd7458a207d349484cf0136f66f9a41fab2` |
| rollback compatibility JSON | `003a76fd8eae00b566bcb8aec35173700324808020f401dea06c65dd40f38f8a` |
| integrated Chrome JSON report | `07cfdb46bbf55237d456d63df66fc60c0d1b41115df94bd7e6d1380f8edea4c8` |

The verified pre-migration backup remains the primary rollback mechanism even though code-only
rollback compatibility passes.

## Evidence boundaries and remaining gates

- `SOURCE_IMPLEMENTED`: PASS through local P4.
- `LOCAL / FAKE-PROVIDER VERIFIED`: PASS on the exact application revision above.
- `LIVE MODEL VERIFIED`: **NOT VERIFIED for the Question Engine pipeline**.
- `PRODUCTION VERIFIED`: **NOT VERIFIED and not changed**.
- Human quality acceptance of generated practice/assessment content: still required.
- Campus material publication remains blocked by the owner's rights decision; this work did not
  rescan `D:\Canvas` and did not publish any withheld material.
- A later production release still requires a fresh authorised production snapshot, verified
  restore rehearsal of that snapshot, approved live-model budget, release window, signed-in
  acceptance and rollback observation.
