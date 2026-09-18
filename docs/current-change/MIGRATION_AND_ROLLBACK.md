# MIGRATION_AND_ROLLBACK

## Schema changes (this round)

1. `services/rag-api/migrations/025_campus_display_and_verification.sql`
   (V3 DB, `LATEST_V3_SCHEMA_VERSION` 24 → 25):
   - new table `learning_pairs` (+ partial unique node-binding index);
   - ledger row version 25.
   Conditional ALTERs applied in `app/db.py` (SQLite cannot ADD COLUMN IF NOT EXISTS):
   - `courses.display_type` CHECK IN ('private','campus','shared');
   - `courses.requires_student_verification INTEGER NOT NULL DEFAULT 0`;
   - one-time data repair: official courses → campus+verification, user courses → private;
   - one-time name repair: strips a trailing ` <id>` suffix ONLY when the stored name
     provably ends with the course id (old creation logic wrote "base id" into name);
     legitimate numeric names (CS3481, Python 3) are untouched.
   Idempotent by inspection; re-runs skip when columns exist.
2. `app/cm_update/db.py` schema 5 → 6 (UI DB): `cmui_pairs`, `cmui_classifications`,
   `cmui_verification*`, `cmui_redemption_attempts`, `cmui_shares*`, `cmui_exercises`,
   `cmui_answer_reveals`, `cmui_step_explanations`, `cmui_explanation_messages`;
   amendments: `cmui_runs.teaching_mode`, `cmui_courses.display_type` +
   `requires_student_verification`, `cmui_messages.provenance` + `exercise`,
   `cmui_conversations.hidden`, `cmui_step_explanations.conversation`.
   One-time `_migrate_pairs` pairs `cmui_layout` evidence first, then single-lane leftovers.

## Migration safety

- All migration experiments were run against fresh temporary databases via the test
  harness (`tmp_path`), never against the archived production snapshots.
- UI `initialize()` refuses to run over a legacy domain DB and refuses downgrades
  (`cmui_meta.schema_version` check) — unchanged guarantees plus the new idempotent amendments.
- Backup before deploy (required by deployment round): copy `rag.sqlite3`,
  `agent.sqlite3`, `ui.sqlite3`, uploads; `PRAGMA integrity_check` each;
  cross-DB references (cmui_run_v3 → journeys) re-verified after restore.

## Rollback

- Application rollback: revert to the previous release — all new tables/columns are
  additive and ignored by older releases (same pattern as migrations 022–024).
- Data is NEVER rolled back with code: user data (pairs, shares, verification,
  exercises) survives a code rollback; a data restore is an independent, explicit
  operation from the archived backups.
- Known state changes after upgrade that a rollback would hide (not delete):
  display_type values, grandfathered verification rows, pair rows, share snapshots.

## Deployment prerequisites (future round)

- `CMUI_VERIFICATION_SECRET` set (production validation enforces).
- Real student-verification boundary snapshot approved.
- Real-model (qwen3.8-max) verification budget for classification/teaching/exercises/
  explanations explicitly approved.
