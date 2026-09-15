"""Migration 022 and UI Schema 5: compatibility evidence on isolated copies.

These tests simulate the exact upgrade/rollback boundaries the release must
prove, using copies under tmp paths:

* a historical Schema-21 database upgrades to 22 preserving VALIDATED /
  LEGACY_PRESERVED rows, triggers and integrity, and the upgrade is idempotent;
* the new unique index reports pre-existing duplicates loudly instead of
  silently deleting anything;
* the RAG migration runs even when the UI extension is disabled (the flag
  never owned RAG migrations);
* an OLD release's readiness check and progress query still work on a Schema-22
  database - it simply does not count REVIEWED rows (no crash, smaller
  progress), which is the honest compatibility statement rather than "columns
  unchanged therefore identical";
* an older UI extension release refuses to open a Schema-5 UI database instead
  of writing into it.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app import db as app_db
from app.config import Settings
from app.db import Database
from app.learning.workspaces import join_course

PRE_022_MIGRATIONS = tuple(name for name in app_db.V3_MIGRATIONS if name != "022_shell_delivery_evidence.sql")

MIGRATIONS_DIR = Path(app_db.__file__).parent.parent / "migrations"


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        app_env="test",
        v3_enabled=True,
        rag_provider_mode="deterministic",
        ui_web_dir=tmp_path / "no-web-build",
    )


def _legacy_rows(database: Database) -> None:
    """Seed the same pre-plan ledger shape migration 015 backfills from."""
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO courses(id,name,publication_status) "
            "VALUES('cs3481','Synthetic','published')"
        )
    join_course(database, "cs3481", "user-a", 10)
    workspace_id = join_course(database, "cs3481", "user-a", 10)["id"]
    content = json.dumps(
        [
            {
                "item_id": "principle",
                "requirement": "REQUIRED",
                "objective": "Explain",
                "acceptance": "State the principle.",
                "evidence_ids": [],
            },
            {
                "item_id": "second",
                "requirement": "REQUIRED",
                "objective": "Explain the second",
                "acceptance": "State the second principle.",
                "evidence_ids": [],
            },
        ],
        sort_keys=True,
    )
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO knowledge_nodes(id,course_id,owner_user_id,title,description,"
            "major,kind,status) VALUES('legacy-node','cs3481',NULL,'Legacy',"
            "'Synthetic','CS','ATOMIC','PUBLISHED')"
        )
        connection.execute(
            "INSERT INTO teaching_specs(node_id,version,content_json,content_hash) "
            "VALUES('legacy-node',1,?,?)",
            (content, "0" * 64),
        )
        connection.execute(
            "INSERT INTO learning_journeys(id,workspace_id,node_id,spec_version) "
            "VALUES('legacy-journey',?, 'legacy-node', 1)",
            (workspace_id,),
        )
        connection.execute(
            "INSERT INTO teaching_units(id,journey_id,operation_id,workflow,"
            "content_json,plan_json,provenance_json) VALUES("
            "'legacy-unit','legacy-journey','legacy-op','TEACHING',"
            "'{\"sections\":[{\"section_id\":\"legacy-section\",\"title\":\"Legacy\","
            "\"content\":\"A legacy completed explanation retained for migration history.\"}]}',"
            "'{}','{\"evidence_ids\":[]}')"
        )
        connection.execute(
            "INSERT INTO learning_coverage(journey_id,item_id,unit_id,section_ids_json) "
            "VALUES('legacy-journey','principle','legacy-unit','[\"legacy-section\"]')"
        )


def test_schema_21_copy_upgrades_to_22_preserving_rows_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Build a genuine historical Schema-21 database first.
    monkeypatch.setattr(app_db, "V3_MIGRATIONS", PRE_022_MIGRATIONS)
    database = Database(_settings(tmp_path))
    database.initialize()
    _legacy_rows(database)
    monkeypatch.undo()

    database.initialize()  # the real 022 upgrade on the historical copy
    with database.connect() as connection:
        versions = [
            row[0]
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        assert versions == list(range(1, app_db.LATEST_V3_SCHEMA_VERSION + 1))
        preserved = connection.execute(
            "SELECT validation_status, plan_version_id, content_hash "
            "FROM teaching_delivery_evidence WHERE teaching_unit_id='legacy-unit'"
        ).fetchall()
        assert [tuple(row) for row in preserved] == [("LEGACY_PRESERVED", None, None)]
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(teaching_units)")
        }
        assert "one_teaching_unit_per_operation" in indexes

    database.initialize()  # idempotent
    with database.connect() as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_upgrade_reports_pre_existing_duplicates_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_db, "V3_MIGRATIONS", PRE_022_MIGRATIONS)
    database = Database(_settings(tmp_path))
    database.initialize()
    _legacy_rows(database)
    # A pre-existing duplicate (journey_id, operation_id) that the new unique
    # index cannot accept. The upgrade must fail loudly and never delete rows.
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO teaching_units(id,journey_id,operation_id,workflow,"
            "content_json,plan_json,provenance_json) VALUES("
            "'legacy-unit-2','legacy-journey','legacy-op','TEACHING',"
            "'{\"sections\":[]}','{}','{}')"
        )
    monkeypatch.undo()

    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed: teaching_units"):
        database.initialize()
    # Both rows survive untouched for an audited operator decision.
    with database.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM teaching_units WHERE journey_id='legacy-journey' "
            "AND operation_id='legacy-op'"
        ).fetchone()[0]
        assert count == 2


def test_rag_migration_runs_even_with_ui_extension_disabled(tmp_path: Path) -> None:
    # The UI mount flag never owned RAG migrations: Database.initialize applies
    # V3_MIGRATIONS whenever v3_enabled is true, UI mounted or not.
    database = Database(_settings(tmp_path))
    database.initialize()
    with database.connect() as connection:
        version = connection.execute(
            "SELECT MAX(version) FROM schema_migrations WHERE version <= ?",
            (app_db.LATEST_V3_SCHEMA_VERSION,),
        ).fetchone()[0]
    assert version == 22


def test_old_release_readiness_and_progress_on_schema_22(tmp_path: Path) -> None:
    from app.learning.coverage_review import DeterministicCoverageReviewer
    from app.learning.shell_delivery import submit_shell_delivery
    import asyncio

    database = Database(_settings(tmp_path))
    database.initialize()
    _legacy_rows(database)
    # Re-running initialize replays migration 015's backfill for the seeded
    # legacy coverage (INSERT OR IGNORE), exactly like the upgrade path.
    database.initialize()

    # An old release's readiness probe only knows versions 1..21.
    with database.connect() as connection:
        applied = {
            int(row[0])
            for row in connection.execute(
                "SELECT version FROM schema_migrations WHERE version <= ?", (21,)
            )
        }
        assert applied == set(range(1, 22))  # old release reports READY

    # Write a REVIEWED row through the real new-code path for a SECOND item
    # (the legacy one is already covered by the backfilled LEGACY row).
    content = "补充讲解：State the second principle."
    asyncio.run(
        submit_shell_delivery(
            database,
            workspace_id="w-1",
            journey_id="legacy-journey",
            node={"id": "legacy-node", "spec_hash": None},
            spec_version=1,
            items=[
                {
                    "item_id": "second",
                    "requirement": "REQUIRED",
                    "objective": "Explain the second",
                    "acceptance": "State the second principle.",
                }
            ],
            content=content,
            operation_id="reviewed-op",
            provenance={"run_id": "reviewed-op", "course_id": "cs3481"},
            reviewer=DeterministicCoverageReviewer(),
        )
    )

    with database.connect() as connection:
        # The old release's coverage query (no REVIEWED status) still runs and
        # simply does not count the new rows: smaller progress, never a crash.
        old_covered = connection.execute(
            "SELECT DISTINCT item_id FROM teaching_delivery_evidence "
            "WHERE journey_id='legacy-journey' AND validation_status IN "
            "('VALIDATED','LEGACY_PRESERVED')"
        ).fetchall()
        assert [row[0] for row in old_covered] == ["principle"]
        new_covered = connection.execute(
            "SELECT DISTINCT item_id FROM teaching_delivery_evidence "
            "WHERE journey_id='legacy-journey' AND validation_status IN "
            "('VALIDATED','LEGACY_PRESERVED','REVIEWED')"
        ).fetchall()
        assert sorted(row[0] for row in new_covered) == ["principle", "second"]
        reviewed = connection.execute(
            "SELECT validation_status FROM teaching_delivery_evidence "
            "WHERE teaching_unit_id=(SELECT id FROM teaching_units WHERE operation_id='reviewed-op')"
        ).fetchone()[0]
        assert reviewed == "REVIEWED"


def test_older_ui_release_refuses_schema_5_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.cm_update import db as ui_db_module
    from app.cm_update.db import Database as UiDatabase

    ui_dir = tmp_path / "ui"
    current = UiDatabase(ui_dir / "ui.sqlite3")
    current.initialize()  # writes Schema 5
    assert current.one("SELECT value FROM cmui_meta WHERE key='schema_version'")["value"] == "5"

    # Simulate the older release binary: its SCHEMA_VERSION constant is lower.
    monkeypatch.setattr(ui_db_module, "SCHEMA_VERSION", 4)
    older = UiDatabase(ui_dir / "ui.sqlite3")
    with pytest.raises(ValueError, match="Newer UI database schema detected; do not downgrade"):
        older.initialize()
