"""Frozen qualification snapshot operations; all identities and HTTP are synthetic."""

import asyncio
import hashlib
import json
import os

import httpx
import pytest

from app.cm_update import qualification_snapshot as snapshots
from app.cm_update.auth import ensure_user
from app.cm_update.db import Database, SCHEMA_VERSION
from app.cm_update.social import verification_status


def record(subject: str, created: int = 1_000, **extra: object) -> dict[str, object]:
    return {
        "id": subject,
        "created_at": created,
        "updated_at": 3_000,
        "email_addresses": [{"email_address": f"{subject}@example.invalid"}],
        **extra,
    }


def test_frozen_snapshot_is_minimal_deterministic_and_reports_only_aggregates() -> None:
    first = snapshots.build_snapshot(
        [record("later", 2_001), record("old", 1_000)], captured_at_ms=4_000
    )
    second = snapshots.build_snapshot(
        [record("old", 1_000), record("later", 2_001)], captured_at_ms=4_000
    )

    assert first == second
    assert first["complete"] is True
    assert first["records"] == [
        {"id": "later", "created_at": 2_001, "updated_at": 3_000,
         "banned": False, "deleted": False, "locked": False},
        {"id": "old", "created_at": 1_000, "updated_at": 3_000,
         "banned": False, "deleted": False, "locked": False},
    ]
    assert "email" not in json.dumps(first)

    preview = snapshots.preview_snapshot(first, cutoff_ms=2_000)
    assert preview == {
        "version": 1,
        "complete": True,
        "captured_at_ms": 4_000,
        "registered_count": 2,
        "candidate_count": 1,
        "unknown_created_at": 0,
        "snapshot_sha256": snapshots.snapshot_sha256(first),
        "candidate_set_sha256": hashlib.sha256(b'["old"]').hexdigest(),
        "eligibility_evidence_sha256": (
            "40d467ff6c22c791b628c56e9246a658b255390240938a36df1a5f4e5511632e"
        ),
        "database": None,
    }
    assert "old" not in json.dumps(preview)


def test_snapshot_file_is_private_and_never_overwritten(tmp_path) -> None:
    output = tmp_path / "qualification.json"
    snapshot = snapshots.build_snapshot([record("old")], captured_at_ms=4_000)

    snapshots.write_snapshot(output, snapshot)
    original = output.read_bytes()
    if os.name != "nt":
        assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        snapshots.write_snapshot(output, snapshots.build_snapshot([], captured_at_ms=5_000))
    assert output.read_bytes() == original


def test_capture_uses_complete_client_result_and_leaves_database_untouched(tmp_path) -> None:
    output = tmp_path / "qualification.json"

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer synthetic-secret"
        return httpx.Response(200, json=[record("old")])

    async def capture() -> dict[str, object]:
        async with httpx.AsyncClient(
            base_url="https://clerk.example.invalid/v1/",
            headers={"Authorization": "Bearer synthetic-secret"},
            transport=httpx.MockTransport(handle),
        ) as http:
            return await snapshots.capture_snapshot(
                output, "synthetic-secret", http_client=http, captured_at_ms=4_000
            )

    summary = asyncio.run(capture())
    assert summary["registered_count"] == 1
    assert summary["snapshot_sha256"]
    assert "old" not in json.dumps(summary)
    assert snapshots.read_snapshot(output)["records"][0]["id"] == "old"


def test_readonly_database_preview_does_not_create_or_modify_a_database(tmp_path) -> None:
    missing = tmp_path / "missing.sqlite3"
    snapshot = snapshots.build_snapshot([record("old")], captured_at_ms=4_000)
    with pytest.raises(FileNotFoundError):
        snapshots.preview_snapshot(snapshot, cutoff_ms=2_000, database=missing)
    assert not missing.exists()

    database = tmp_path / "ui.sqlite3"
    db = Database(database)
    db.initialize()
    ensure_user(db, "existing")
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    preview = snapshots.preview_snapshot(snapshot, cutoff_ms=2_000, database=database)
    after = hashlib.sha256(database.read_bytes()).hexdigest()

    assert before == after
    assert preview["database"] == {
        "schema_version": str(SCHEMA_VERSION),
        "fixed_cutoff_ms": None,
        "receipt_status": None,
        "receipt_cutoff_ms": None,
        "receipt_evidence_sha256": None,
    }


def test_apply_requires_exact_frozen_hashes_and_never_refetches(tmp_path) -> None:
    database = tmp_path / "ui.sqlite3"
    db = Database(database)
    db.initialize()
    snapshot = snapshots.build_snapshot(
        [record("old"), record("new", 2_001)], captured_at_ms=4_000
    )
    preview = snapshots.preview_snapshot(snapshot, cutoff_ms=2_000)

    with pytest.raises(ValueError, match="snapshot hash"):
        snapshots.apply_snapshot(
            database,
            snapshot,
            cutoff_ms=2_000,
            expected_snapshot_sha256="0" * 64,
            expected_candidate_set_sha256=preview["candidate_set_sha256"],
        )
    assert db.all("SELECT * FROM cmui_verification") == []
    assert db.one(
        "SELECT value FROM cmui_meta WHERE key='verification_grandfather_registered_snapshot'"
    ) is None

    with pytest.raises(ValueError, match="candidate-set hash"):
        snapshots.apply_snapshot(
            database,
            snapshot,
            cutoff_ms=2_000,
            expected_snapshot_sha256=preview["snapshot_sha256"],
            expected_candidate_set_sha256="f" * 64,
        )
    assert db.all("SELECT * FROM cmui_verification") == []

    receipt = snapshots.apply_snapshot(
        database,
        snapshot,
        cutoff_ms=2_000,
        expected_snapshot_sha256=preview["snapshot_sha256"],
        expected_candidate_set_sha256=preview["candidate_set_sha256"],
    )
    assert receipt["status"] == "COMPLETED"
    assert receipt["candidate_count"] == 1
    assert "old" not in json.dumps(receipt)
    assert verification_status(db, "old")["method"] == "grandfathered"
    assert verification_status(db, "new")["verified"] is False


def test_apply_refuses_an_unrelated_completed_database_receipt(tmp_path) -> None:
    database = tmp_path / "ui.sqlite3"
    db = Database(database)
    db.initialize()
    first = snapshots.build_snapshot([record("first")], captured_at_ms=4_000)
    first_preview = snapshots.preview_snapshot(first, cutoff_ms=2_000)
    snapshots.apply_snapshot(
        database,
        first,
        cutoff_ms=2_000,
        expected_snapshot_sha256=first_preview["snapshot_sha256"],
        expected_candidate_set_sha256=first_preview["candidate_set_sha256"],
    )

    second = snapshots.build_snapshot([record("second")], captured_at_ms=5_000)
    second_preview = snapshots.preview_snapshot(second, cutoff_ms=2_000)
    with pytest.raises(ValueError, match="completed receipt"):
        snapshots.apply_snapshot(
            database,
            second,
            cutoff_ms=2_000,
            expected_snapshot_sha256=second_preview["snapshot_sha256"],
            expected_candidate_set_sha256=second_preview["candidate_set_sha256"],
        )
    assert verification_status(db, "second")["verified"] is False


def test_snapshot_rejects_non_boolean_account_state() -> None:
    with pytest.raises(ValueError, match="boolean"):
        snapshots.build_snapshot([record("old", banned="false")], captured_at_ms=4_000)
