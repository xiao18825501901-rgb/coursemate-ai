"""The provider failure ledger, and the append-only guarantee behind it.

Everything here is a deterministic fact: a classification table, a row shape, an
SQLite trigger, an INSERT conflict.  No provider is contacted and nothing is
guessed about a real failed call.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from test_question_persistence import database_with_objective  # noqa: E402

from app.learning.hybrid_review import POLICY_REVISION
from app.learning.provider import (
    FAILURE_LAYER_HTTP_OR_PERMISSION,
    FAILURE_LAYER_LOCAL_CONFIGURATION,
    FAILURE_LAYER_LOCAL_DURABILITY,
    FAILURE_LAYER_LOCAL_INPUT_VALIDATION,
    FAILURE_LAYER_PROVIDER_EMPTY_OR_REFUSAL,
    FAILURE_LAYER_PROVIDER_INCOMPLETE,
    FAILURE_LAYER_RESPONSE_SCHEMA,
    FAILURE_LAYER_UNKNOWN,
    FAILURE_LAYER_UPSTREAM_TRANSPORT,
    classify_failure_layer,
)
from app.learning.provider_failure_ledger import (
    failure_census,
    failure_row,
    record_provider_failure,
)


def _run(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "model": "deepseek-flash",
        "provider": "DEEPSEEK_API",
        "protocol": "responses",
        "region": "ENDPOINT_DEEPSEEK",
        "role": "evidence_audit",
        "template_version": "judge-evidence-audit.v4",
        "schema_version": "coursejesus-judge-findings.v3",
        "input_hash": "a" * 64,
        "started_at": "2026-09-30T00:00:00Z",
        "finished_at": "2026-09-30T00:00:12Z",
        "latency_ms": 12000,
        "input_tokens": 5100,
        "output_tokens": 0,
        "provider_response_id": None,
        "status": "FAILED",
        "error_class": "SCHEMA_INVALID",
    }
    values.update(overrides)
    return values


# --- the taxonomy is a table, so a wrong bucket is a failing test ----------------


@pytest.mark.parametrize(
    ("error_class", "status", "expected"),
    [
        ("CONTEXT_BUDGET", "FAILED", FAILURE_LAYER_LOCAL_INPUT_VALIDATION),
        ("IMAGE_MODEL_LIMIT", "FAILED", FAILURE_LAYER_LOCAL_INPUT_VALIDATION),
        ("MODEL_OUTPUT_LIMIT_INVALID", "FAILED", FAILURE_LAYER_LOCAL_INPUT_VALIDATION),
        ("MODEL_LIVE_BLOCKED", "BLOCKED", FAILURE_LAYER_LOCAL_CONFIGURATION),
        ("MODEL_ENDPOINT_INVALID", "BLOCKED", FAILURE_LAYER_LOCAL_CONFIGURATION),
        ("AUTO_LEDGER_WRITE_FAILED", "UNKNOWN", FAILURE_LAYER_LOCAL_DURABILITY),
        ("MODEL_INCOMPLETE", "FAILED", FAILURE_LAYER_PROVIDER_INCOMPLETE),
        ("MODEL_EMPTY_OUTPUT", "FAILED", FAILURE_LAYER_PROVIDER_EMPTY_OR_REFUSAL),
        ("SCHEMA_INVALID", "FAILED", FAILURE_LAYER_RESPONSE_SCHEMA),
        ("ValidationError", "FAILED", FAILURE_LAYER_RESPONSE_SCHEMA),
        ("APITimeoutError", "UNKNOWN", FAILURE_LAYER_UPSTREAM_TRANSPORT),
        ("APIConnectionError", "UNKNOWN", FAILURE_LAYER_UPSTREAM_TRANSPORT),
        ("InternalServerError", "FAILED", FAILURE_LAYER_UPSTREAM_TRANSPORT),
        ("RateLimitError", "FAILED", FAILURE_LAYER_HTTP_OR_PERMISSION),
        ("AuthenticationError", "FAILED", FAILURE_LAYER_HTTP_OR_PERMISSION),
        ("SomethingNewFromTheProvider", "FAILED", FAILURE_LAYER_UNKNOWN),
    ],
)
def test_each_error_class_lands_in_its_named_layer(
    error_class: str, status: str, expected: str
) -> None:
    assert classify_failure_layer(error_class=error_class, status=status) == expected


def test_a_complete_response_that_failed_the_schema_is_not_an_outage() -> None:
    """The rule the stored runs could not enforce, enforced at the classifier."""
    assert (
        classify_failure_layer(error_class="SCHEMA_INVALID", status="FAILED")
        != classify_failure_layer(error_class="APITimeoutError", status="UNKNOWN")
    )


# --- the row shape -----------------------------------------------------------------


def test_a_failure_row_keeps_the_complete_response_and_its_digest() -> None:
    text = json.dumps({"cases": [{"case_key": "question.ambiguity.v1", "verdict": "PASS"}]})
    row = failure_row(
        policy_revision=POLICY_REVISION,
        role="evidence_audit",
        run=_run(response_text=text, response_received=True),
        question_revision_hash="b" * 64,
    )
    assert row["failure_layer"] == FAILURE_LAYER_RESPONSE_SCHEMA
    assert row["response_received"] == 1
    assert row["response_text"] == text
    assert row["response_digest"] == hashlib.sha256(text.encode()).hexdigest()


def test_a_transport_failure_still_records_the_layer_and_the_status() -> None:
    row = failure_row(
        policy_revision=POLICY_REVISION,
        role="adversarial_audit",
        run=_run(
            error_class="APITimeoutError",
            status="UNKNOWN",
            timeout_kind="READ",
            cause_chain=["APITimeoutError", "ReadTimeout"],
        ),
    )
    assert row["failure_layer"] == FAILURE_LAYER_UPSTREAM_TRANSPORT
    assert row["terminal_status"] == "UNKNOWN"
    assert row["timeout_kind"] == "READ"
    assert json.loads(row["cause_chain_json"]) == ["APITimeoutError", "ReadTimeout"]


# --- durability ---------------------------------------------------------------------


def test_a_recorded_failure_survives_and_is_immutable(tmp_path: Path) -> None:
    database, _ = database_with_objective(tmp_path)
    row_id = record_provider_failure(
        database,
        policy_revision=POLICY_REVISION,
        role="evidence_audit",
        run=_run(error_class="APITimeoutError", status="UNKNOWN"),
        question_revision_hash="c" * 64,
        blueprint_hash="d" * 64,
        evidence_pack_hash="e" * 64,
        message="a strong semantic review did not reach a complete terminal",
    )
    assert row_id.startswith("hybridfail-")
    assert failure_census(database, question_revision_hash="c" * 64) == {
        FAILURE_LAYER_UPSTREAM_TRANSPORT: 1
    }
    with database.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE hybrid_provider_failures SET error_class=? WHERE id=?",
                ("APIConnectionError", row_id),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM hybrid_provider_failures WHERE id=?", (row_id,))
    with database.connect() as connection:
        stored = connection.execute(
            "SELECT error_class, failure_layer FROM hybrid_provider_failures WHERE id=?",
            (row_id,),
        ).fetchone()
    assert stored["error_class"] == "APITimeoutError"


CALL_COLUMNS = (
    "id,question_revision_hash,blueprint_hash,evidence_pack_hash,policy_revision,"
    "role,call_id,model,provider,protocol,region,template_version,schema_version,"
    "input_hash,response_digest,response_json,findings_json,verification_json,"
    "references_verified,terminal,input_tokens,output_tokens,latency_ms,"
    "provider_response_id"
)
CALL_VALUES: tuple[Any, ...] = (
    "call-1", "f" * 64, "a" * 64, "b" * 64, POLICY_REVISION,
    "evidence_audit", "response-1", "deepseek-flash", "DEEPSEEK_API", "responses",
    "ENDPOINT_DEEPSEEK", "judge-evidence-audit.v4", "coursejesus-judge-findings.v3",
    "1" * 64, "2" * 64, "{}", "{}", "{}",
    1, "completed", 10, 20, 30, "response-1",
)
CALL_INSERT = "INSERT INTO hybrid_review_calls(" + CALL_COLUMNS + ") VALUES(" + ",".join(
    "?" * 24
) + ")"


def test_the_review_call_ledger_is_actually_append_only(tmp_path: Path) -> None:
    """The defect that made the 065 triggers decorative.

    SQLite fires a BEFORE DELETE trigger from INSERT OR REPLACE only when
    PRAGMA recursive_triggers is on, and the runtime default is 0.  The writer
    used INSERT OR REPLACE, so a conflicting call row was silently overwritten
    while the immutable triggers never ran.  The rebuild in migration 066 widens
    the key to include the prompt and schema versions, and the writer now uses a
    plain INSERT, so a duplicate refuses instead of erasing history.
    """
    database, _ = database_with_objective(tmp_path)
    with database.connect() as connection:
        assert connection.execute("PRAGMA recursive_triggers").fetchone()[0] == 0
        connection.execute(CALL_INSERT, CALL_VALUES)
        # The same identity with a different prompt version is a new call.
        newer = list(CALL_VALUES)
        newer[0] = "call-2"
        newer[11] = "judge-evidence-audit.v5"
        connection.execute(CALL_INSERT, tuple(newer))
        # An exact duplicate refuses rather than replacing the first row.
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(CALL_INSERT, CALL_VALUES)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM hybrid_review_calls WHERE id=?", ("call-1",))
        assert connection.execute(
            "SELECT COUNT(*) FROM hybrid_review_calls"
        ).fetchone()[0] == 2


def test_the_writer_does_not_use_insert_or_replace() -> None:
    """A source-level guard, because the failure mode is silent."""
    source = (
        Path(__file__).resolve().parents[1] / "app" / "learning" / "hybrid_quality.py"
    ).read_text(encoding="utf-8")
    assert "INSERT OR REPLACE INTO hybrid_review_calls" not in source
