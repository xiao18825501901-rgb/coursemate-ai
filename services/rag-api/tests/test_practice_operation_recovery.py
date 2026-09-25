from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_question_persistence import (
    COURSE,
    NODE,
    OWNER,
    PRIVATE_COURSE,
    WORKSPACE,
    database_with_objective,
)
from test_question_runtime import decisions

from app.learning.practice_recovery import (
    PracticeRecoveryError,
    inspect_practice_operations,
    reconcile_practice_operation,
)
from app.learning.provider import LearningProvider
from app.learning.question_runtime import QuestionEngineRuntime, QuestionEngineRuntimeError, _hash


def _orphaned_hint(tmp_path: Path, operation_id: str, *, metered: bool = True):
    database, config = database_with_objective(tmp_path)
    runtime = QuestionEngineRuntime(
        database=database,
        provider=LearningProvider(config),
        semantic_decisions=decisions(database),
    )
    generated = runtime.generate_one(
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        course_id=COURSE,
        private_course_id=PRIVATE_COURSE,
        node_id=NODE,
        operation_id=f"question-for-{operation_id}",
    )
    context = runtime._practice_context(
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        question_revision_id=generated["question_revision_id"],
    )
    input_hash = _hash("HINT", generated["question_revision_id"], context)
    old_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO practice_interaction_operations("
            "workspace_id,operation_id,question_revision_id,owner_user_id,kind,input_hash,"
            "status,created_at,updated_at) VALUES(?,?,?,?,?,?,'CLAIMED',?,?)",
            (
                WORKSPACE,
                operation_id,
                generated["question_revision_id"],
                OWNER,
                "HINT",
                input_hash,
                old_time,
                old_time,
            ),
        )
        if metered:
            connection.execute(
                "INSERT INTO practice_operation_metering_guards("
                "workspace_id,operation_id,guard_version) "
                "VALUES(?,?,'metered-practice.v1')",
                (WORKSPACE, operation_id),
            )
    return database, runtime, generated["question_revision_id"]


def test_inventory_distinguishes_not_sent_unknown_and_completed_without_result(
    tmp_path: Path,
) -> None:
    database, _, _ = _orphaned_hint(tmp_path, "orphan-not-sent")
    with database.connect() as connection:
        rows = inspect_practice_operations(
            connection, workspace_id=WORKSPACE, operation_id="orphan-not-sent"
        )
        assert rows[0].classification == "NOT_SENT"
        assert rows[0].within_active_window is False

        connection.execute(
            "INSERT INTO practice_interaction_operations "
            "SELECT workspace_id,'orphan-unknown',question_revision_id,owner_user_id,kind,"
            "input_hash,status,result_json,error_code,created_at,updated_at "
            "FROM practice_interaction_operations WHERE operation_id='orphan-not-sent'"
        )
        connection.execute(
            "INSERT INTO practice_operation_metering_guards("
            "workspace_id,operation_id,guard_version) "
            "VALUES(?,?,'metered-practice.v1')",
            (WORKSPACE, "orphan-unknown"),
        )
        connection.execute(
            "INSERT INTO learning_model_call_reservations("
            "id,workspace_id,operation_id,owner_user_id,course_id,role,"
            "reserved_output_tokens,status) VALUES('reservation-unknown',?,?,?,?,?,100,'RESERVED')",
            (WORKSPACE, "orphan-unknown", OWNER, COURSE, "PRACTICE_HINT"),
        )

        connection.execute(
            "INSERT INTO practice_interaction_operations "
            "SELECT workspace_id,'orphan-completed-call',question_revision_id,owner_user_id,kind,"
            "input_hash,status,result_json,error_code,created_at,updated_at "
            "FROM practice_interaction_operations WHERE operation_id='orphan-not-sent'"
        )
        connection.execute(
            "INSERT INTO practice_operation_metering_guards("
            "workspace_id,operation_id,guard_version) "
            "VALUES(?,?,'metered-practice.v1')",
            (WORKSPACE, "orphan-completed-call"),
        )
        connection.execute(
            "INSERT INTO learning_model_call_reservations("
            "id,workspace_id,operation_id,owner_user_id,course_id,role,"
            "reserved_output_tokens,status,finished_at) "
            "VALUES('reservation-completed',?,?,?,?,?,100,'COMPLETED',?)",
            (
                WORKSPACE,
                "orphan-completed-call",
                OWNER,
                COURSE,
                "PRACTICE_HINT",
                "2026-09-25T00:00:00Z",
            ),
        )
        inventory = {
            row.operation_id: row.classification
            for row in inspect_practice_operations(connection, workspace_id=WORKSPACE)
        }

    assert inventory["orphan-unknown"] == "UPSTREAM_UNKNOWN"
    assert inventory["orphan-completed-call"] == "UPSTREAM_COMPLETED_NO_RESULT"


def test_explicit_not_sent_reconciliation_links_one_new_operation_without_reuse(
    tmp_path: Path,
) -> None:
    database, runtime, question_revision_id = _orphaned_hint(tmp_path, "orphan-retry-source")
    with database.connect() as connection:
        with pytest.raises(PracticeRecoveryError, match="writers"):
            reconcile_practice_operation(
                connection,
                workspace_id=WORKSPACE,
                operation_id="orphan-retry-source",
                expected_classification="NOT_SENT",
                disposition="NOT_SENT",
                operator_ref="incident-P5-001",
                evidence=b"worker drain evidence",
                writers_drained=False,
            )
        reconciled = reconcile_practice_operation(
            connection,
            workspace_id=WORKSPACE,
            operation_id="orphan-retry-source",
            expected_classification="NOT_SENT",
            disposition="NOT_SENT",
            operator_ref="incident-P5-001",
            evidence=b"worker drain evidence",
            writers_drained=True,
        )
    assert reconciled.classification == "RECONCILED_NOT_SENT"

    with pytest.raises(QuestionEngineRuntimeError) as blocked:
        runtime.generate_hint(
            owner_user_id=OWNER,
            workspace_id=WORKSPACE,
            question_revision_id=question_revision_id,
            operation_id="orphan-retry-source",
        )
    assert blocked.value.code == "PRACTICE_OPERATION_RECOVERED"

    replacement = runtime.generate_hint(
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        question_revision_id=question_revision_id,
        operation_id="orphan-retry-replacement",
    )
    assert replacement["hint"]
    with database.connect() as connection:
        link = connection.execute(
            "SELECT prior_operation_id,new_operation_id FROM practice_operation_retry_links"
        ).fetchone()
        old = connection.execute(
            "SELECT status FROM practice_interaction_operations "
            "WHERE workspace_id=? AND operation_id='orphan-retry-source'",
            (WORKSPACE,),
        ).fetchone()
    assert tuple(link) == ("orphan-retry-source", "orphan-retry-replacement")
    assert old["status"] == "CLAIMED"


def test_reconciliation_refuses_to_reclassify_or_overwrite_evidence(tmp_path: Path) -> None:
    database, _, _ = _orphaned_hint(tmp_path, "orphan-evidence-lock")
    with database.connect() as connection:
        with pytest.raises(PracticeRecoveryError, match="classification"):
            reconcile_practice_operation(
                connection,
                workspace_id=WORKSPACE,
                operation_id="orphan-evidence-lock",
                expected_classification="UPSTREAM_UNKNOWN",
                disposition="UPSTREAM_UNKNOWN",
                operator_ref="incident-P5-002",
                evidence=b"wrong classification evidence",
                writers_drained=True,
            )
        first = reconcile_practice_operation(
            connection,
            workspace_id=WORKSPACE,
            operation_id="orphan-evidence-lock",
            expected_classification="NOT_SENT",
            disposition="NOT_SENT",
            operator_ref="incident-P5-002",
            evidence=b"first evidence",
            writers_drained=True,
        )
        with pytest.raises(PracticeRecoveryError, match="already reconciled"):
            reconcile_practice_operation(
                connection,
                workspace_id=WORKSPACE,
                operation_id="orphan-evidence-lock",
                expected_classification="RECONCILED_NOT_SENT",
                disposition="NOT_SENT",
                operator_ref="incident-P5-003",
                evidence=b"replacement evidence",
                writers_drained=True,
            )
        row = connection.execute(
            "SELECT evidence_hash,operator_ref FROM practice_operation_reconciliations "
            "WHERE workspace_id=? AND operation_id='orphan-evidence-lock'",
            (WORKSPACE,),
        ).fetchone()
    assert row["evidence_hash"] == first.evidence_hash
    assert row["operator_ref"] == "incident-P5-002"
    assert "first evidence" not in json.dumps(dict(row))


def test_operator_cli_is_read_only_by_default_and_requires_explicit_apply(tmp_path: Path) -> None:
    database, _, _ = _orphaned_hint(tmp_path, "orphan-cli-operation")
    root = Path(__file__).resolve().parents[3]
    script = root / "scripts" / "reconcile_practice_operations.py"
    inventory = subprocess.run(
        [
            sys.executable,
            str(script),
            "inventory",
            "--database",
            str(database.path),
            "--workspace-id",
            WORKSPACE,
            "--operation-id",
            "orphan-cli-operation",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert inventory.returncode == 0, inventory.stderr
    assert json.loads(inventory.stdout)[0]["classification"] == "NOT_SENT"

    evidence = tmp_path / "worker-drain.txt"
    evidence.write_text("synthetic writers drained", encoding="utf-8")
    base = [
        sys.executable,
        str(script),
        "reconcile",
        "--database",
        str(database.path),
        "--workspace-id",
        WORKSPACE,
        "--operation-id",
        "orphan-cli-operation",
        "--expected-classification",
        "NOT_SENT",
        "--disposition",
        "NOT_SENT",
        "--operator-ref",
        "incident-P5-cli",
        "--evidence-file",
        str(evidence),
        "--writers-drained",
    ]
    refused = subprocess.run(base, cwd=root, capture_output=True, text=True, check=False)
    assert refused.returncode == 2
    assert "--apply" in refused.stderr
    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM practice_operation_reconciliations"
        ).fetchone()[0] == 0

    applied = subprocess.run(
        [*base, "--apply"], cwd=root, capture_output=True, text=True, check=False
    )
    assert applied.returncode == 0, applied.stderr
    assert json.loads(applied.stdout)["classification"] == "RECONCILED_NOT_SENT"
