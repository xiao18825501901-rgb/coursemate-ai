"""Schema 26 → 28 rollback compatibility: the previous release must stay viable.

Migration 027 rebuilds four tables (``assessment_question_revisions``,
``assessment_blueprint_items``, ``learning_model_run_evidence``,
``learning_model_call_reservations``) to widen CHECK constraints, and 027/028 add
new tables. Rebuilding a table is the one migration shape that can silently break
an already-deployed release, so this file freezes what the previous release
(commit ``b05fd294``, Schema 26) actually had and asserts the migrated schema only
ever *grew*:

* every pre-027 column still exists, with the same type and nullability, so the
  old code's explicit ``INSERT`` column lists and ``SELECT *`` reads keep working;
* every pre-027 table still exists;
* every pre-027 CHECK enum value is still accepted — constraints may widen, never
  narrow, because narrowing would reject rows the old release still writes.

The frozen snapshot below was extracted from an exported copy of that release
(``git archive b05fd294`` + the release's own ``Database.initialize()`` +
``PRAGMA table_info`` / ``sqlite_master`` SQL), not from this tree. It is a pin,
not a description: if a later migration removes a column or narrows an enum this
test fails loudly instead of shipping a database the previous release cannot use.

The complementary end-to-end evidence — running the previous release's own code
against a Schema-28 database — is reproducible with
``scripts/verify_rollback_compat.py <release-tree>``.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.config import Settings
from app.db import Database

# table -> ((column, declared type, notnull), ...) exactly as Schema 26 had them.
PRE_027_COLUMNS: dict[str, tuple[tuple[str, str, int], ...]] = {
    "assessment_question_revisions": (
        ("id", "TEXT", 0),
        ("course_id", "TEXT", 1),
        ("owner_user_id", "TEXT", 0),
        ("family_id", "TEXT", 1),
        ("revision", "INTEGER", 1),
        ("source_kind", "TEXT", 1),
        ("source_document_version_id", "TEXT", 0),
        ("source_problem_revision_id", "TEXT", 0),
        ("question_type", "TEXT", 1),
        ("difficulty", "INTEGER", 1),
        ("prompt_text", "TEXT", 1),
        ("options_json", "TEXT", 1),
        ("answer_json", "TEXT", 1),
        ("validation_status", "TEXT", 1),
        ("verification_method", "TEXT", 1),
        ("content_hash", "TEXT", 1),
        ("created_by_user_id", "TEXT", 1),
        ("created_at", "TEXT", 1),
    ),
    "assessment_blueprint_items": (
        ("id", "TEXT", 0),
        ("blueprint_id", "TEXT", 1),
        ("ordinal", "INTEGER", 1),
        ("question_revision_id", "TEXT", 1),
        ("family_id", "TEXT", 1),
        ("marks", "INTEGER", 1),
        ("source_kind", "TEXT", 1),
        ("verification_method", "TEXT", 1),
    ),
    "learning_model_run_evidence": (
        ("id", "TEXT", 0),
        ("workspace_id", "TEXT", 1),
        ("operation_id", "TEXT", 1),
        ("role", "TEXT", 1),
        ("model_id", "TEXT", 1),
        ("provider_label", "TEXT", 1),
        ("protocol", "TEXT", 1),
        ("region_label", "TEXT", 1),
        ("template_version", "TEXT", 1),
        ("schema_version", "TEXT", 1),
        ("input_hash", "TEXT", 0),
        ("started_at", "TEXT", 1),
        ("finished_at", "TEXT", 1),
        ("latency_ms", "INTEGER", 1),
        ("input_tokens", "INTEGER", 1),
        ("output_tokens", "INTEGER", 1),
        ("status", "TEXT", 1),
        ("error_class", "TEXT", 0),
        ("provider_response_id", "TEXT", 0),
    ),
    "learning_model_call_reservations": (
        ("id", "TEXT", 0),
        ("workspace_id", "TEXT", 1),
        ("operation_id", "TEXT", 1),
        ("owner_user_id", "TEXT", 1),
        ("course_id", "TEXT", 1),
        ("role", "TEXT", 1),
        ("reserved_output_tokens", "INTEGER", 1),
        ("status", "TEXT", 1),
        ("input_tokens", "INTEGER", 1),
        ("output_tokens", "INTEGER", 1),
        ("created_at", "TEXT", 1),
        ("finished_at", "TEXT", 0),
    ),
}

# Every table the previous release created and reads.
PRE_027_TABLES: tuple[str, ...] = (
    "assessment_blueprint_grade_policies",
    "assessment_blueprint_items",
    "assessment_blueprint_versions",
    "assessment_exposure_events",
    "assessment_question_attempts",
    "assessment_question_revisions",
    "assessment_rubric_criteria",
    "assessment_sessions",
    "learning_start_events",
)

# CHECK constraints the previous release relied on; the migrated schema must still
# accept every one of these values.
PRE_027_ENUMS: dict[str, dict[str, tuple[str, ...]]] = {
    "assessment_question_revisions": {
        "source_kind": ("OFFICIAL", "WORKSPACE_PRIVATE", "MODEL_GENERATED", "EXTERNAL_INSPIRED"),
        "question_type": ("MCQ_SINGLE", "NUMERIC", "SHORT_TEXT", "EXPLANATION", "CODE"),
        "validation_status": ("CANDIDATE", "VALIDATED", "NEEDS_REVIEW", "REJECTED"),
        "verification_method": (
            "OFFICIAL",
            "OWNER_AUTHORED",
            "DETERMINISTIC",
            "HUMAN_REVIEWED",
            "MODEL_ONLY",
        ),
    },
    "assessment_blueprint_items": {
        "source_kind": ("OFFICIAL", "WORKSPACE_PRIVATE", "MODEL_GENERATED", "EXTERNAL_INSPIRED"),
        "verification_method": (
            "OFFICIAL",
            "OWNER_AUTHORED",
            "DETERMINISTIC",
            "HUMAN_REVIEWED",
        ),
    },
    "learning_model_run_evidence": {
        "role": ("planner", "teacher", "problem", "grader", "router"),
        "status": ("COMPLETED", "FAILED", "UNKNOWN", "BLOCKED", "LEGACY_COMPLETED"),
    },
    "learning_model_call_reservations": {
        "role": ("planner", "teacher", "problem", "grader", "router"),
        "status": ("RESERVED", "COMPLETED", "FAILED", "UNKNOWN", "BLOCKED"),
    },
}

ADDITIVE_TABLES: tuple[str, ...] = (
    "assessment_preparation_jobs",
    "assessment_reference_solutions",
    "assessment_answer_drafts",
    "assessment_submission_revisions",
    "assessment_grading_receipts",
    "assessment_explanation_contexts",
    "jev_decision_receipts",
    "entity_relations",
    "feedback_reports",
    "question_engine_provenance",
)


def _migrated_database(tmp_path: Path) -> Database:
    database = Database(
        Settings(
            database_path=tmp_path / "rag.sqlite3",
            upload_dir=tmp_path / "uploads",
            app_env="test",
            v3_enabled=True,
            rag_provider_mode="deterministic",
            ui_web_dir=tmp_path / "no-web-build",
        )
    )
    database.initialize()
    return database


def _live_enums(sql: str) -> dict[str, tuple[str, ...]]:
    pattern = re.compile(r"(\w+)\s+IN\s*\(([^)]*)\)")
    return {
        match.group(1): tuple(
            value.strip().strip("'") for value in match.group(2).split(",")
        )
        for match in pattern.finditer(sql)
    }


def test_every_pre_027_table_still_exists(tmp_path: Path) -> None:
    database = _migrated_database(tmp_path)
    with database.connect() as connection:
        present = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert sorted(set(PRE_027_TABLES) - present) == []


def test_rebuilt_tables_keep_every_pre_027_column_with_the_same_shape(
    tmp_path: Path,
) -> None:
    database = _migrated_database(tmp_path)
    problems: list[str] = []
    with database.connect() as connection:
        for table, frozen in PRE_027_COLUMNS.items():
            live = {
                row[1]: (row[2], row[3])
                for row in connection.execute(f'PRAGMA table_info("{table}")')
            }
            for name, declared_type, notnull in frozen:
                if name not in live:
                    problems.append(f"{table}.{name}: column was removed")
                    continue
                if live[name] != (declared_type, notnull):
                    problems.append(
                        f"{table}.{name}: type/notnull changed "
                        f"{live[name]} != {(declared_type, notnull)}"
                    )
    assert problems == [], (
        "migration 027 rebuilt these tables; the previous release must still be "
        "able to insert and read them: " + "; ".join(problems)
    )


def test_check_enums_only_widen(tmp_path: Path) -> None:
    database = _migrated_database(tmp_path)
    problems: list[str] = []
    with database.connect() as connection:
        for table, frozen_enums in PRE_027_ENUMS.items():
            row = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name=?", (table,)
            ).fetchone()
            assert row is not None, f"{table} has no schema"
            live = _live_enums(str(row[0]))
            for column, before in frozen_enums.items():
                if column not in live:
                    problems.append(f"{table}.{column}: CHECK constraint disappeared")
                    continue
                missing = sorted(set(before) - set(live[column]))
                if missing:
                    problems.append(f"{table}.{column}: values no longer accepted {missing}")
    assert problems == [], (
        "CHECK constraints may widen but never narrow, otherwise rows written by "
        "the previous release become invalid: " + "; ".join(problems)
    )


def test_new_tables_are_additive_and_the_migration_set_replays(tmp_path: Path) -> None:
    database = _migrated_database(tmp_path)
    database.initialize()  # replay must be idempotent
    with database.connect() as connection:
        versions = [
            row[0]
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        present = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert versions == sorted(versions)
    assert 27 in versions and 28 in versions
    assert sorted(set(ADDITIVE_TABLES) - present) == []


def test_a_pre_027_shaped_row_survives_a_migration_replay(tmp_path: Path) -> None:
    """A row written the way the deployed release writes it must survive 27-28.

    The insert uses only columns that existed before 027, which is exactly what
    the previous release emits. (The stronger "old file migrated upward" case is
    covered by ``test_v3_migration_rehearsal``; this one pins the row shape the
    previous release can still produce and read back.)
    """
    database = _migrated_database(tmp_path)
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO courses(id,name,publication_status) "
            "VALUES('compat-course','Compat','published')"
        )
        connection.execute(
            "INSERT INTO assessment_question_revisions("
            "id,course_id,owner_user_id,family_id,revision,source_kind,question_type,"
            "difficulty,prompt_text,options_json,answer_json,validation_status,"
            "verification_method,content_hash,created_by_user_id) "
            "VALUES('q1','compat-course','owner','family',1,'MODEL_GENERATED','MCQ_SINGLE',"
            "1,'pre-027 question','[]','{\"correct_option\":\"A\"}','VALIDATED',"
            "'DETERMINISTIC',?,'owner')",
            ("a" * 64,),
        )
        before = dict(
            connection.execute(
                "SELECT * FROM assessment_question_revisions WHERE id='q1'"
            ).fetchone()
        )
    # Re-open the same file and replay the whole migration set: the row is intact.
    replayed = Database(
        Settings(
            database_path=tmp_path / "rag.sqlite3",
            upload_dir=tmp_path / "uploads",
            app_env="test",
            v3_enabled=True,
            rag_provider_mode="deterministic",
            ui_web_dir=tmp_path / "no-web-build",
        )
    )
    replayed.initialize()
    with replayed.connect() as connection:
        after = dict(
            connection.execute(
                "SELECT * FROM assessment_question_revisions WHERE id='q1'"
            ).fetchone()
        )
    assert after == before
    assert before["validation_status"] == "VALIDATED"
    assert before["verification_method"] == "DETERMINISTIC"
