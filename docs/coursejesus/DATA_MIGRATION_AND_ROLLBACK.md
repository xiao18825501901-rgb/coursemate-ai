# DATA MIGRATION AND ROLLBACK (CourseJesus work)

**State of this document.** Written in round 73, covering the schema and rollback position of the
CourseJesus work (brand/domain, Canvas private import, campus material) against the production
release. It is a *plan plus current measurement*, not a record of a deployment: **nothing here has
been applied to production**, and the production release is still `4ef5064` on its own schema.

## 1. Where the schema stands (measured, not assumed)

| Fact | Value | Where it comes from |
|---|---|---|
| Latest V3 schema version | **32** | `LATEST_V3_SCHEMA_VERSION` in `app/db.py` |
| Latest V2 schema version | 10 | `LATEST_V2_SCHEMA_VERSION` |
| Registered V3 migrations | **22** (`011_learning_workspaces.sql` … `032_campus_material.sql`) | the explicit `V3_MIGRATIONS` tuple |
| Migration files on disk | 26 | `services/rag-api/migrations/*.sql` |
| Migrations added by this work | `029_entity_relations.sql`, `030_feedback_reports.sql`, `031_canvas_import.sql`, `032_campus_material.sql` | migration files |
| Production release / schema | `4ef5064`, schema **25** | read-only production observation recorded in `COURSEJESUS_EXECUTION_STATE.md` |

Two rules this repository already follows, and which the numbers above depend on:

* **Migrations are registered explicitly**, in the `V3_MIGRATIONS` tuple — there is no directory scan,
  so a migration file that is not registered is not applied.
* **Each migration file inserts its own `schema_migrations` row**, so a partially applied release
  cannot look complete.

## 2. What this work adds to the database

| Migration | Tables | Notes |
|---|---|---|
| `029_entity_relations.sql` | entity relations for course concepts | relations only; it merges no knowledge node and changes no tree id |
| `030_feedback_reports.sql` | the user-initiated feedback queue | records identifiers, and a body only when the user opted in |
| `031_canvas_import.sql` | `canvas_connections`, `canvas_import_jobs`, `canvas_import_files` | **no token column exists**; a job references a connection, and the credential lives in the encrypted store keyed by `connection_id` |
| `032_campus_material.sql` | `campus_material_records` | one row per source file with `usage_rights`, `publication_basis` and a NOT NULL `review_status` |

Nothing in these migrations drops or rewrites a column, changes an existing table's shape, or
touches any table that existed before them. That is what makes the rollback in §4 possible.

## 3. Applying them (forward)

1. **Back up first, consistently.** `ops/backup_v2.py` creates a verified backup of both databases
   and the uploads with a `coursemate-v2-<stamp>` name, and `ops/restore_v2.py` verifies and restores
   one into a new isolated directory. A backup that has not been restored once is not evidence, so
   the release sequence rehearses the restore before touching production.
2. **Rehearse on an isolated copy.** `scripts/rehearse_v3_migration.py` applies the migrations to a
   copy and reports what it did; the release sequence runs it before the real window.
3. **Apply during the bounded window.** `ops/production_switch_four_changes.sh` stops the two
   services, switches the release symlink, starts them, and verifies health; it refuses to proceed if
   either service was unhealthy to begin with.
4. **Verify afterwards.** Schema version equals 32, the four tables above exist, and the course,
   document, node, assessment and user identifiers from before the migration are unchanged.

## 4. Rolling back

The rollback story is deliberately "additive or nothing", which is what `scripts/verify_rollback_compat.py`
measures. Given a previous release root and the current tree, it reports a verdict plus the fields a
reviewer needs to disagree with it: `verdict`, `reasons`, `tables_missing_for_release`,
`columns_missing_for_release`, `columns_retyped_for_release`, `check_enums_narrowed`,
`rebuilt_tables_checked`, `pool_filter_verdict`, `pool_filter_release`, `pool_filter_current`,
`pool_filter_unchanged`, `pool_filter_detail` and `rollback_concerns`.

How to read it:

* **`verdict: ROLLBACK_SAFE_WITH_MIGRATED_DB`** (the tool's exit 0) means the previous release can
  run against the migrated database: no table or column it needs is gone, no column it reads changed
  type, no CHECK enum it relies on was narrowed, and the assessment pool filter it selects with is
  byte-identical (measured from **both** trees — round 42 found and fixed a version of this tool that
  read only the current tree and so could never have said "different").
* **`verdict: ROLLBACK_REQUIRES_DB_RESTORE`** (exit 3) means a code-only rollback is not viable;
  the release sequence falls back to `OLD_RELEASE` with the pre-migration backup restored, which is
  why the backup is verified before the window and not after.
* **`pool_filter_verdict`** is one of `UNCHANGED`, `CHANGED` or `UNDETERMINED`. Anything other than
  `UNCHANGED` is listed in `rollback_concerns` and needs an owner decision, because the two releases
  would select different assessment pools. An unextractable predicate is reported as `UNDETERMINED`
  and is never rounded up to "compatible".

## 5. What is *not* covered here

* **Applying any of this to production.** That is an owner-gated action with its own window, and the
  release sequence in `COURSEJESUS_EXECUTION_STATE.md` places it after local green and after the
  live model validation.
* **A domain, Clerk, Netlify or GitHub change.** Those are not schema changes; they are in
  `DOMAIN_AND_CLERK_MIGRATION.md` and `GITHUB_AND_NETLIFY_RENAME.md`.
* **Credential storage migration.** `031` stores no token, and the encrypted credential files live
  outside the database, so a database restore neither creates nor destroys a Canvas credential; a
  restored database with no key material simply reports the Canvas integration as unconfigured.
* **Old-domain compatibility.** Nothing here requires the old domain to stay up; that dependency is
  tracked separately in the migration document above.
