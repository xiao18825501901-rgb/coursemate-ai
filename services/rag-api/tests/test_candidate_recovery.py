"""Rebuilding an already-authored candidate for review only.

The recovery path exists so an item whose author, blind solve and deterministic
gates are already complete can be reviewed without paying for it again.  These
tests pin the property that makes that safe: the rebuild is verified against the
hashes the pipeline itself recorded, and any mismatch is a refusal rather than a
best-effort repair.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.learning.candidate_recovery import (
    CandidateRecoveryError,
    deterministic_report_for,
    list_recoverable,
    recover_candidate,
)

from test_question_persistence import (  # noqa: E402 - shared fixture builder
    COURSE,
    NODE,
    OWNER,
    WORKSPACE,
    persist,
    pipeline,
)


def _persist_needs_review(tmp_path: Path) -> tuple[object, str, str]:
    """Run the real pipeline and persist the candidate with no semantic review.

    Returns the database, the stored row id (``qe_...``) and the immutable
    content hash (64 hex) -- the two are different identifiers and conflating
    them is the mistake this helper exists to prevent.
    """
    context = pipeline(tmp_path)
    database = context["database"]
    # Persist without the local semantic service: the candidate's author, blind
    # solve and deterministic gates are complete and only review is missing,
    # which is exactly the state the nine real revisions are in.
    persisted = persist(context, semantic_decisions=None)

    assert persisted.status == "NEEDS_REVIEW"
    with database.connect() as connection:
        row = connection.execute(
            "SELECT question_revision_id, question_revision_hash "
            "FROM question_engine_provenance WHERE workspace_id=?",
            (WORKSPACE,),
        ).fetchone()
    return database, str(row["question_revision_id"]), str(row["question_revision_hash"])


def test_a_stored_candidate_is_rebuilt_and_every_hash_verifies(tmp_path: Path) -> None:
    database, revision_id, revision_hash = _persist_needs_review(tmp_path)
    record = recover_candidate(database, question_revision_id=revision_id)

    assert record.publication_status == "NEEDS_REVIEW"
    assert record.candidate.question_revision == revision_hash
    # The rebuild reproduces the stored identities rather than approximating them.
    assert record.blueprint.identity() == record.candidate.blueprint_hash
    assert record.evidence.identity() == record.candidate.evidence_pack_hash
    assert record.candidate.revision_identity() == revision_hash
    assert record.blind_receipt.is_current_for(
        revision_hash,
        record.blind_receipt.input_hash,
    )
    assert record.owner_user_id == OWNER
    assert record.course_id == COURSE
    assert record.node_id == NODE


def test_the_recovered_candidate_carries_the_authored_content(tmp_path: Path) -> None:
    database, revision_id, _ = _persist_needs_review(tmp_path)
    record = recover_candidate(database, question_revision_id=revision_id)
    with database.connect() as connection:
        stored = connection.execute(
            "SELECT prompt_text, answer_json FROM assessment_question_revisions WHERE id=?",
            (revision_id,),
        ).fetchone()
    assert record.candidate.public_question.question_text == str(stored["prompt_text"])
    answer = json.loads(str(stored["answer_json"]))
    assert record.candidate.private_solution.candidate_answer == answer["reference_answer"]
    assert record.blind_receipt.output.strip().startswith("{")


def test_the_recovered_candidate_is_listed_as_recoverable(tmp_path: Path) -> None:
    database, revision_id, _ = _persist_needs_review(tmp_path)
    listed = list_recoverable(database)
    assert [row["question_revision_id"] for row in listed] == [revision_id]
    assert listed[0]["question_type"] == "NUMERIC"


def test_the_rebuilt_gates_start_from_an_unreviewed_state(tmp_path: Path) -> None:
    """Semantic signals are not reused, because replacing them is the point."""
    database, revision_id, _ = _persist_needs_review(tmp_path)
    record = recover_candidate(database, question_revision_id=revision_id)
    report = deterministic_report_for(record)
    # The six hard gates are recomputed from the recovered inputs...
    assert len(report.hard_gates) == 6
    assert all(gate.status == "PASS" for gate in report.hard_gates)
    # ...and every semantic case is left for the real review to decide.
    assert report.status == "NEEDS_REVIEW"
    assert {signal.verdict for signal in report.semantic_signals} == {"UNCERTAIN"}
    assert all(not signal.used_jev for signal in report.semantic_signals)


def _tamper(connection, sql: str, parameters: tuple) -> None:
    """Change a stored row the way a corruption would, past its own triggers."""
    connection.execute("DROP TRIGGER IF EXISTS immutable_question_engine_provenance_update")
    connection.execute(sql, parameters)


def test_a_tampered_blueprint_hash_is_refused_not_repaired(tmp_path: Path) -> None:
    database, revision_id, _ = _persist_needs_review(tmp_path)
    with database.connect() as connection:
        _tamper(
            connection,
            "UPDATE question_engine_provenance SET blueprint_hash=? "
            "WHERE question_revision_id=?",
            ("0" * 64, revision_id),
        )
    with pytest.raises(CandidateRecoveryError) as raised:
        recover_candidate(database, question_revision_id=revision_id)
    assert raised.value.code == "CANDIDATE_HASH_MISMATCH"


def test_a_tampered_blind_input_hash_is_refused(tmp_path: Path) -> None:
    database, revision_id, _ = _persist_needs_review(tmp_path)
    with database.connect() as connection:
        _tamper(
            connection,
            "UPDATE question_engine_provenance SET blind_input_hash=? "
            "WHERE question_revision_id=?",
            ("1" * 64, revision_id),
        )
    with pytest.raises(CandidateRecoveryError) as raised:
        recover_candidate(database, question_revision_id=revision_id)
    assert raised.value.code == "CANDIDATE_BLIND_MISMATCH"


def test_provenance_immutability_blocks_a_tamper_without_bypassing_it(
    tmp_path: Path,
) -> None:
    """The trigger is the first line of defence; the hash check is the second."""
    import sqlite3

    database, revision_id, _ = _persist_needs_review(tmp_path)
    with database.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE question_engine_provenance SET blueprint_hash=? "
                "WHERE question_revision_id=?",
                ("0" * 64, revision_id),
            )


def test_an_unknown_revision_is_refused(tmp_path: Path) -> None:
    database, _, _ = _persist_needs_review(tmp_path)
    with pytest.raises(CandidateRecoveryError) as raised:
        recover_candidate(database, question_revision_id="qe-does-not-exist")
    assert raised.value.code == "CANDIDATE_NOT_FOUND"
