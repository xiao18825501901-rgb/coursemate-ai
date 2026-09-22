"""Reference-solution verification gate: the assessment grading flow.

The stored reference solution for each question must be verified BEFORE it is
presented as grading evidence. Layer 1 is deterministic (existence, currency,
authorization — zero Jev calls); Layer 3 is semantic and only runs when a
semantic layer is configured. A negative verdict flags ``needs_review`` with a
machine-readable reason but never changes a mark, weight, total, grade or
coverage value.

These tests run against a real migrated V3 database (``Database.initialize``),
seed the assessment fixture through ``seed_assessment_fixture``, and use the
offline ``FakeTransport`` for the semantic layer (no network).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import Settings
from app.db import Database
from app.jev.catalog import load_catalog
from app.jev.errors import JevUnavailableError
from app.jev.gateway import FakeTransport, JevGateway
from app.jev.models import JevAnswer, JevResult
from app.jev.service import SemanticDecisionService
from app.learning.assessments import REFERENCE_VERIFY_MAX_REFS, AssessmentService
from app.learning.models import AssessmentAnswer

_SCRIPTS = str(Path(__file__).resolve().parents[3] / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)
from prepare_v3_e2e import seed_assessment_fixture  # noqa: E402

CATALOG = load_catalog()
SUPPORT_KEY = "source.supports_claim.v1"
OWNER = "user-a"


def make_database(path: Path) -> Database:
    database = Database(
        Settings(database_path=path, upload_dir=path.parent / "uploads", v3_enabled=True)
    )
    database.initialize()
    return database


def make_jev(
    responder: Callable[[Any], Any],
    *,
    modes: dict[str, str] | None = None,
) -> tuple[SemanticDecisionService, FakeTransport]:
    # No persistent receipt store: the semantic call runs inside the grading write
    # transaction (save_submission), and a second DB writer would deadlock. The
    # verdict is already recorded on the grading result, so the receipt ledger is
    # redundant here.
    transport = FakeTransport(responder)
    gateway = JevGateway(transport=transport, catalog=CATALOG, modes=modes or {})
    return SemanticDecisionService(gateway), transport


def seed_official_corpus(database: Database, chunks: dict[str, str] | None = None) -> None:
    """Insert course ``cs3481`` plus one official document/version with chunks."""
    chunks = chunks if chunks is not None else {"chunk-official": "The pass rate is 40%."}
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO courses(id,name,owner_user_id,course_type,visibility,publication_status) "
            "VALUES('cs3481','Synthetic CS3481',NULL,'official','public','private')"
        )
        connection.execute(
            "INSERT INTO documents(id,course_id,filename,stored_path,media_type,extension,"
            "sha256,byte_size,status) "
            "VALUES('doc-official','cs3481','official.txt','official.txt','text/plain',"
            "'.txt',?,12,'ready')",
            ("a" * 64,),
        )
        for ordinal, (chunk_id, content) in enumerate(chunks.items()):
            connection.execute(
                "INSERT INTO chunks(id,document_id,course_id,ordinal,content,locator_type,"
                "locator_value,section,embedding) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    chunk_id,
                    "doc-official",
                    "cs3481",
                    ordinal,
                    content,
                    "page",
                    str(ordinal + 1),
                    f"Page {ordinal + 1}",
                    "[1.0]",
                ),
            )


def supersede_document(database: Database) -> None:
    """Publish version 2, leaving the existing chunk bound to (stale) version 1."""
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO document_versions(id,document_id,version,course_id,owner_user_id,"
            "source_scope,filename,stored_path,media_type,extension,sha256,byte_size) "
            "VALUES('doc-official-v2','doc-official',2,'cs3481',NULL,'OFFICIAL',"
            "'official-v2.txt','official-v2.txt','text/plain','.txt',?,12)",
            ("b" * 64,),
        )


def start_session(
    database: Database, jev: SemanticDecisionService | None = None
) -> tuple[AssessmentService, Any, dict[str, Any]]:
    node_id = seed_assessment_fixture(database, OWNER)
    service = AssessmentService(database, jev=jev)
    with database.connect() as connection:
        workspace = connection.execute(
            "SELECT * FROM learning_workspaces WHERE owner_user_id=? AND course_id='cs3481'",
            (OWNER,),
        ).fetchone()
    with database.connect() as connection:
        session = service.start(connection, workspace, node_id)
    return service, workspace, session


def step(result: str, source_refs: list[str], step_id: str = "step_1") -> dict[str, Any]:
    return {
        "step_id": step_id,
        "ordinal": 1,
        "operation": "Derive the reference result",
        "result": result,
        "explanation": "The cited evidence must support the reference result.",
        "source_refs": list(source_refs),
    }


def set_reference_steps(
    database: Database, question_revision_id: str, steps: list[dict[str, Any]]
) -> None:
    source_refs = sorted({ref for item in steps for ref in item["source_refs"]})
    with database.connect() as connection:
        connection.execute(
            "DELETE FROM assessment_reference_solutions WHERE question_revision_id=?",
            (question_revision_id,),
        )
        connection.execute(
            "INSERT INTO assessment_reference_solutions(id,question_revision_id,"
            "blueprint_item_id,solution_revision,steps_json,answer_json,source_refs_json,"
            "prompt_version,content_hash) VALUES(?,?,NULL,1,?,?,?,?,?)",
            (
                uuid4().hex,
                question_revision_id,
                json.dumps(steps),
                json.dumps("Reference answer"),
                json.dumps(source_refs),
                "problem-v3.2",
                "a" * 64,
            ),
        )


def set_reference(
    database: Database, question_revision_id: str, source_refs: list[str], result: str
) -> None:
    set_reference_steps(database, question_revision_id, [step(result, source_refs)])


def submit(service: AssessmentService, workspace: Any, session: dict[str, Any]) -> dict[str, Any]:
    with service.db.connect() as connection:
        answers = [
            AssessmentAnswer(blueprint_item_id=question["id"], answer="correct")
            for question in session["questions"]
        ]
        return service.save_submission(connection, workspace, session["id"], answers, None)


def stable(result: dict[str, Any]) -> dict[str, Any]:
    """Project the grading-relevant, deterministic fields for byte comparison."""
    def question_stable(question: dict[str, Any]) -> dict[str, Any]:
        review = question.get("review") or {}
        return {
            "question_revision_id": question["question_revision_id"],
            "marks": question["marks"],
            "attempt_status": question["attempt_status"],
            "review": {
                "submitted_answer": review.get("submitted_answer"),
                "awarded_marks": review.get("awarded_marks"),
                "feedback": review.get("feedback"),
                "reference_verification": review.get("reference_verification"),
            },
        }

    return {
        "status": result["status"],
        "raw_score": result["raw_score"],
        "grade": result["grade"],
        "independent_eligible": result["independent_eligible"],
        "questions": [question_stable(question) for question in result["questions"]],
    }


def test_clean_submission_is_unchanged_and_unflagged(tmp_path: Path) -> None:
    database = make_database(tmp_path / "clean.sqlite3")
    seed_official_corpus(database)
    service, workspace, session = start_session(database, jev=None)
    question = session["questions"][0]
    set_reference(
        database, question["question_revision_id"], ["chunk-official"], "The pass rate is 40%."
    )

    result = submit(service, workspace, session)

    assert result["status"] == "GRADED"
    assert result["raw_score"] == 100
    assert result["independent_eligible"] is True
    assert all(q["attempt_status"] == "GRADED" for q in result["questions"])
    verification = result["questions"][0]["review"]["reference_verification"]
    assert verification["verdict"] == "verified"
    assert verification["verified"] is True
    assert verification["negative"] is False
    assert verification["reason"] is None
    assert verification["refs"] == [{"ref": "chunk-official", "status": "ok"}]


def test_stale_reference_flags_needs_review_but_score_identical(tmp_path: Path) -> None:
    clean_db = make_database(tmp_path / "clean.sqlite3")
    seed_official_corpus(clean_db)
    clean_service, clean_workspace, clean_session = start_session(clean_db, jev=None)
    clean_question = clean_session["questions"][0]
    set_reference(
        clean_db,
        clean_question["question_revision_id"],
        ["chunk-official"],
        "The pass rate is 40%.",
    )
    clean_result = submit(clean_service, clean_workspace, clean_session)

    stale_db = make_database(tmp_path / "stale.sqlite3")
    seed_official_corpus(stale_db)
    supersede_document(stale_db)  # chunk-official is now bound to superseded version 1
    stale_service, stale_workspace, stale_session = start_session(stale_db, jev=None)
    stale_question = stale_session["questions"][0]
    set_reference(
        stale_db,
        stale_question["question_revision_id"],
        ["chunk-official"],
        "The pass rate is 40%.",
    )
    stale_result = submit(stale_service, stale_workspace, stale_session)

    assert stale_result["status"] == "SUBMITTED"
    assert stale_result["raw_score"] is None
    flagged = stale_result["questions"][0]
    assert flagged["attempt_status"] == "NEEDS_REVIEW"
    verification = flagged["review"]["reference_verification"]
    assert verification["verdict"] == "reference_evidence_stale"
    assert verification["reason"] == "reference_evidence_stale"
    assert verification["negative"] is True
    assert verification["verified"] is False
    assert verification["refs"] == [{"ref": "chunk-official", "status": "stale"}]

    # The mark, feedback and the learner's own answer are byte-identical to the
    # clean run; only the review flag changed.
    clean_review = clean_result["questions"][0]["review"]
    assert flagged["review"]["awarded_marks"] == clean_review["awarded_marks"]
    assert flagged["review"]["feedback"] == clean_review["feedback"]
    assert flagged["review"]["submitted_answer"] == clean_review["submitted_answer"]
    assert all(q["attempt_status"] == "GRADED" for q in stale_result["questions"][1:])


def test_reference_without_resolvable_refs_is_unverified_not_contradiction(
    tmp_path: Path,
) -> None:
    database = make_database(tmp_path / "empty.sqlite3")
    seed_official_corpus(database)
    service, workspace, session = start_session(database, jev=None)
    question = session["questions"][0]
    set_reference(database, question["question_revision_id"], [], "The pass rate is 88%.")

    result = submit(service, workspace, session)

    assert result["status"] == "GRADED"
    assert result["raw_score"] == 100
    assert all(q["attempt_status"] == "GRADED" for q in result["questions"])
    verification = result["questions"][0]["review"]["reference_verification"]
    assert verification["verdict"] == "reference_evidence_unverified"
    assert verification["negative"] is False
    assert verification["verified"] is False
    assert verification["reason"] is None
    assert verification["refs"] == []


def test_real_contradiction_flags_needs_review_in_on_mode(tmp_path: Path) -> None:
    database = make_database(tmp_path / "contra.sqlite3")
    seed_official_corpus(database)  # chunk content "The pass rate is 40%."

    def responder(call: Any) -> JevResult:
        return JevResult(answers={SUPPORT_KEY: JevAnswer(noul=0.1)})

    jev, _ = make_jev(responder, modes={SUPPORT_KEY: "on"})
    service, workspace, session = start_session(database, jev=jev)
    question = session["questions"][0]
    set_reference(
        database, question["question_revision_id"], ["chunk-official"], "The pass rate is 88%."
    )

    result = submit(service, workspace, session)

    assert result["status"] == "SUBMITTED"
    assert result["raw_score"] is None
    flagged = result["questions"][0]
    assert flagged["attempt_status"] == "NEEDS_REVIEW"
    verification = flagged["review"]["reference_verification"]
    assert verification["verdict"] == "reference_contradicted"
    assert verification["reason"] == "reference_contradicted"
    assert verification["negative"] is True
    assert verification["refs"] == [
        {"ref": "chunk-official", "status": "ok", "semantic": "CONTRADICTED"}
    ]
    # The contradiction only flags review; the deterministic mark is unchanged.
    assert flagged["review"]["awarded_marks"] == 10.0


def test_shadow_and_unavailable_are_byte_identical_to_no_jev(tmp_path: Path) -> None:
    def run(database: Database, jev: SemanticDecisionService | None) -> dict[str, Any]:
        seed_official_corpus(database)
        service, workspace, session = start_session(database, jev=jev)
        question = session["questions"][0]
        set_reference(
            database,
            question["question_revision_id"],
            ["chunk-official"],
            "The pass rate is 40%.",
        )
        return stable(submit(service, workspace, session))

    base = run(make_database(tmp_path / "base.sqlite3"), None)

    # Shadow (the default): a hostile "unsupported" suggestion is recorded but
    # never applied, so the result is byte-identical to no Jev layer.
    shadow_db = make_database(tmp_path / "shadow.sqlite3")
    shadow_jev, _ = make_jev(
        lambda call: JevResult(answers={SUPPORT_KEY: JevAnswer(noul=0.1)})
    )
    shadow = run(shadow_db, shadow_jev)

    # Unavailable transport in "on" mode: fails closed, identical result.
    unavailable_db = make_database(tmp_path / "unavailable.sqlite3")
    unavailable_jev, _ = make_jev(
        lambda call: (_ for _ in ()).throw(JevUnavailableError("down")),
        modes={SUPPORT_KEY: "on"},
    )
    unavailable = run(unavailable_db, unavailable_jev)

    assert shadow == base
    assert unavailable == base


def test_reference_verification_respects_call_budget(tmp_path: Path) -> None:
    database = make_database(tmp_path / "budget.sqlite3")
    chunks = {f"chunk-official-{index}": f"Evidence chunk {index}." for index in range(12)}
    seed_official_corpus(database, chunks)

    calls: list[str] = []

    def responder(call: Any) -> JevResult:
        calls.append(next(iter(call.questions)))
        return JevResult(answers={SUPPORT_KEY: JevAnswer(noul=0.9)})

    jev, transport = make_jev(responder, modes={SUPPORT_KEY: "on"})
    service, workspace, session = start_session(database, jev=jev)
    question = session["questions"][0]
    steps = [
        step("Evidence is consistent.", [f"chunk-official-{index}"], step_id=f"step_{index}")
        for index in range(12)
    ]
    set_reference_steps(database, question["question_revision_id"], steps)

    result = submit(service, workspace, session)

    verification = result["questions"][0]["review"]["reference_verification"]
    # Only a bounded number of refs are checked, and one semantic call per step.
    assert len(verification["refs"]) == REFERENCE_VERIFY_MAX_REFS
    assert len(calls) == REFERENCE_VERIFY_MAX_REFS
    assert len(transport.calls) == REFERENCE_VERIFY_MAX_REFS
    assert all(item["status"] == "ok" for item in verification["refs"])
    # Budgeted verification is still a clean grade (all refs supported).
    assert result["status"] == "GRADED"
    assert result["raw_score"] == 100
