"""The receipt ledger may legitimately be absent — and that must never fail a decision.

The receipts table ships with migration 028, which belongs to the V3 migration set. So a
V2-only deployment, and the real window in which new application code runs *before* its
migration has been applied, both have a working database without that table. The first
version of the module-A wiring turned exactly that ordering detail into a failed learner
request (`sqlite3.OperationalError: no such table: jev_decision_receipts` raised out of
the QA stream); this file pins the fix and the boundary of it.

The rule these tests encode: an **absent ledger** is a cache miss plus a dropped receipt,
while every other SQLite error still propagates, because a real schema or data bug must
not hide behind a best-effort write.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.config import Settings
from app.db import Database
from app.jev.catalog import load_catalog
from app.jev.gateway import Receipt
from app.jev.models import CacheScope, owner_scope_hash
from app.jev.receipt_store import SqlReceiptStore, receipt_connection

RECEIPTS_TABLE = "jev_decision_receipts"


def uninitialized_ledger_database(tmp_path: Path) -> Database:
    """A real migrated database without the V3 migration set (no receipts table)."""

    settings = Settings(
        database_path=tmp_path / "v2.sqlite3",
        upload_dir=tmp_path / "uploads",
        app_env="test",
    )
    database = Database(settings)
    database.initialize()
    return database


def make_receipt() -> Receipt:
    return Receipt(
        id="jev_absent_ledger",
        definition_key="extraction.field_grounded.v1",
        primitive="Choice",
        mode="shadow",
        caller_role="extraction",
        owner_scope_hash=owner_scope_hash("user-a", "official"),
        course_id="cs3481",
        workspace_id=None,
        material_revision=None,
        node_id=None,
        spec_version=None,
        question_hash=None,
        input_hash="0" * 64,
        output_json='{"choice": "GROUNDED"}',
        outcome="ok",
        latency_ms=1.0,
        model_version="fake-1.0.0",
    )


def has_ledger(database: Database) -> bool:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (RECEIPTS_TABLE,),
        ).fetchone()
    return row is not None


def test_the_fixture_really_has_no_ledger(tmp_path: Path) -> None:
    """If the table existed, every other test in this file would prove nothing."""

    database = uninitialized_ledger_database(tmp_path)
    assert has_ledger(database) is False


def test_lookup_is_a_cache_miss_without_the_ledger(tmp_path: Path) -> None:
    database = uninitialized_ledger_database(tmp_path)
    definition = load_catalog().get("extraction.field_grounded.v1")

    cached = SqlReceiptStore(database).lookup(
        definition,
        CacheScope(
            owner_scope_hash=owner_scope_hash("user-a", "official"), course_id="cs3481"
        ),
        provider_model_version="fake-1.0.0",
    )

    assert cached is None


def test_save_drops_the_receipt_without_the_ledger(tmp_path: Path) -> None:
    database = uninitialized_ledger_database(tmp_path)

    SqlReceiptStore(database).save(make_receipt())  # must not raise


def test_a_lent_transaction_still_commits_without_the_ledger(tmp_path: Path) -> None:
    """The caller's business write must survive an unmigrated ledger.

    This is the assessment-grading shape: the receipt is offered the caller's open
    transaction, so a raise here would roll back a grade.
    """

    database = uninitialized_ledger_database(tmp_path)
    store = SqlReceiptStore(database)

    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO schema_migrations(version, name) VALUES(9001, 'business write')"
        )
        with receipt_connection(connection):
            store.save(make_receipt())
        connection.commit()

    with database.connect() as connection:
        committed = connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version=9001"
        ).fetchone()[0]
    assert committed == 1, "the business transaction must still commit"


@pytest.mark.parametrize("method", ["lookup", "save"])
def test_any_other_sqlite_error_still_propagates(tmp_path: Path, method: str) -> None:
    """Only an absent table degrades; a real database fault is never swallowed."""

    database = uninitialized_ledger_database(tmp_path)

    class BrokenDatabase:
        def connect(self) -> object:
            raise sqlite3.OperationalError("disk I/O error")

    store = SqlReceiptStore(BrokenDatabase())
    definition = load_catalog().get("extraction.field_grounded.v1")
    scope = CacheScope(
        owner_scope_hash=owner_scope_hash("user-a", "official"), course_id="cs3481"
    )

    with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
        if method == "lookup":
            store.lookup(definition, scope, provider_model_version=None)
        else:
            store.save(make_receipt())
    # The real database is untouched by this test.
    assert has_ledger(database) is False
