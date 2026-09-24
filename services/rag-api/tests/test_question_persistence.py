"""Stage 7 persists one scoped Question Engine revision atomically into the existing pool."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.db import LATEST_V3_SCHEMA_VERSION, Database
from app.jev.catalog import load_catalog
from app.jev.gateway import FakeTransport, JevGateway
from app.jev.models import JevAnswer, JevResult
from app.jev.receipt_store import SqlReceiptStore
from app.jev.service import SemanticDecisionService
from app.learning.assessments import AssessmentService
from app.learning.blind_solve import run_blind_solve
from app.learning.provider import LearningProvider
from app.learning.question_author import QUESTION_AUTHOR_PROMPT_VERSION, author_question
from app.learning.question_blueprint import QuestionBlueprint, resolve_objective
from app.learning.question_evidence import EvidencePackAccess, build_evidence_pack
from app.learning.question_persistence import (
    QuestionPersistenceError,
    persist_question_candidate,
)
from app.learning.question_validator import (
    collect_question_semantic_signals,
    validate_question_candidate,
)

OWNER = "user-a"
COURSE = "course-question-engine"
PRIVATE_COURSE = "course-question-engine-private"
WORKSPACE = "workspace-question-engine"
NODE = "node-question-engine"
SPEC_HASH = "a" * 64


def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        chunk_size=200,
        chunk_overlap=20,
        app_env="test",
        v3_enabled=True,
        rag_provider_mode="deterministic",
        ui_web_dir=tmp_path / "no-web-build",
    )


def database_with_objective(tmp_path: Path) -> tuple[Database, Settings]:
    config = settings(tmp_path)
    database = Database(config)
    database.initialize()
    item = {
        "item_id": "objective-density",
        "requirement": "REQUIRED",
        "objective": "计算每个点的 epsilon 邻域并判断核心点数量",
        "acceptance": "邻域计数和核心点结论均有课程规则支持",
        "evidence_ids": ["chunk-course"],
    }
    content = "A core point has at least MinPts points in its epsilon neighbourhood."
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO courses(id,name,owner_user_id,course_type,visibility,publication_status) "
            "VALUES(?,? ,?,'user','private','private')",
            (COURSE, "Question Engine course", OWNER),
        )
        connection.execute(
            "INSERT INTO courses(id,name,owner_user_id,course_type,visibility,publication_status) "
            "VALUES(?,? ,?,'user','private','private')",
            (PRIVATE_COURSE, "Question Engine private corpus", OWNER),
        )
        connection.execute(
            "INSERT INTO learning_workspaces(id,owner_user_id,course_id,private_course_id) "
            "VALUES(?,?,?,?)",
            (WORKSPACE, OWNER, COURSE, PRIVATE_COURSE),
        )
        connection.execute(
            "INSERT INTO knowledge_nodes(id,course_id,owner_user_id,title,description,"
            "major,kind,status) VALUES(?,?,?,'Density clustering','Synthetic','CS',"
            "'ATOMIC','PRIVATE')",
            (NODE, COURSE, OWNER),
        )
        connection.execute(
            "INSERT INTO documents(id,course_id,filename,stored_path,media_type,extension,"
            "sha256,byte_size,status,chunk_count) VALUES('doc-course',?,'lecture.md',"
            "'lecture.md','text/markdown','.md',?,?,'ready',1)",
            (COURSE, "b" * 64, len(content.encode())),
        )
        connection.execute(
            "INSERT INTO chunks(id,document_id,course_id,ordinal,content,locator_type,"
            "locator_value,section,embedding) VALUES('chunk-course','doc-course',?,0,"
            "?,'page','7','DBSCAN','[]')",
            (COURSE, content),
        )
        connection.execute(
            "INSERT INTO teaching_specs(node_id,version,content_json,content_hash) "
            "VALUES(?,1,?,?)",
            (NODE, json.dumps([item], ensure_ascii=False), SPEC_HASH),
        )
    return database, config


def pipeline(tmp_path: Path) -> dict[str, Any]:
    database, config = database_with_objective(tmp_path)
    with database.connect() as connection:
        objective = resolve_objective(connection, node_id=NODE)
    evidence = build_evidence_pack(
        database,
        objective=objective,
        access=EvidencePackAccess(
            owner_user_id=OWNER,
            course_id=COURSE,
            private_course_id=PRIVATE_COURSE,
        ),
    )
    blueprint = QuestionBlueprint(
        blueprint_id="blueprint-density-1",
        course_id=COURSE,
        node_id=NODE,
        spec_version=1,
        spec_content_hash=SPEC_HASH,
        objective_id=objective.item_id,
        objective_text=objective.objective,
        source_scope=evidence.source_scope(),
        bloom_target="APPLY",
        target_difficulty=3,
        difficulty_features=["STEPS", "COMPUTATION"],
        question_type="NUMERIC",
        expected_answer_form="NUMERIC_VALUE",
        marks=15,
        scoring_criteria=["邻域计数正确", "核心点结论正确"],
        question_family_id="family-density",
        prompt_versions={"question_author": QUESTION_AUTHOR_PROMPT_VERSION},
        generation_policy_version="question-generation-policy-v1",
    )
    provider = LearningProvider(config)
    candidate = author_question(provider, blueprint=blueprint, evidence=evidence)
    blind = run_blind_solve(provider, candidate=candidate, evidence=evidence)

    def responder(call: Any) -> JevResult:
        key = next(iter(call.questions))
        verdict = "CLEAR" if key == "question.ambiguity.v1" else "AGREE"
        return JevResult(answers={key: JevAnswer(choice=verdict)})

    decisions = SemanticDecisionService(
        JevGateway(
            transport=FakeTransport(responder),
            catalog=load_catalog(),
            modes={
                "question.ambiguity.v1": "on",
                "question.answer_agreement.v1": "on",
            },
            receipt_store=SqlReceiptStore(database),
        )
    )
    scope = decisions.scope(
        owner_user_id=OWNER,
        authorization_scope="question_validation",
        course_id=COURSE,
        workspace_id=WORKSPACE,
        node_id=NODE,
        spec_version=1,
        question_hash=candidate.question_revision,
    )
    semantic = collect_question_semantic_signals(
        decisions,
        candidate=candidate,
        blueprint=blueprint,
        evidence=evidence,
        blind_receipt=blind,
        scope=scope,
    )
    report = validate_question_candidate(
        candidate=candidate,
        blueprint=blueprint,
        evidence=evidence,
        blind_receipt=blind,
        semantic_signals=semantic,
    )
    return {
        "database": database,
        "blueprint": blueprint,
        "evidence": evidence,
        "candidate": candidate,
        "blind": blind,
        "report": report,
        "decisions": decisions,
    }


def persist(values: dict[str, Any], **overrides: Any):
    arguments = {
        "database": values["database"],
        "owner_user_id": OWNER,
        "workspace_id": WORKSPACE,
        "blueprint": values["blueprint"],
        "evidence": values["evidence"],
        "candidate": values["candidate"],
        "blind_receipt": values["blind"],
        "validation_report": values["report"],
        "semantic_decisions": values["decisions"],
    }
    arguments.update(overrides)
    return persist_question_candidate(**arguments)


def test_fresh_schema_includes_additive_question_engine_provenance(tmp_path: Path) -> None:
    database, _ = database_with_objective(tmp_path)
    with database.connect() as connection:
        versions = [row[0] for row in connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )]
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(question_engine_provenance)")
        }
        slot_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(assessment_preparation_questions)"
            )
        }

    assert LATEST_V3_SCHEMA_VERSION == 38
    assert versions == list(range(1, 39))
    assert {
        "question_revision_id",
        "workspace_id",
        "blueprint_json",
        "evidence_ids_json",
        "author_run_json",
        "blind_input_hash",
        "blind_output_json",
        "blind_run_json",
        "validation_report_json",
        "publication_status",
    } <= columns
    assert {"preparation_job_id", "ordinal", "slot_key", "question_revision_id"} <= slot_columns


def test_validated_candidate_is_ready_private_and_idempotent(tmp_path: Path) -> None:
    values = pipeline(tmp_path)

    first = persist(values)
    second = persist(values)

    assert first.status == "READY"
    assert first.verification_method == "AI_REVIEWED"
    assert first.question_revision_id == second.question_revision_id
    assert second.idempotent is True
    assert "answer" not in first.model_dump_json().casefold()
    with values["database"].connect() as connection:
        question = connection.execute(
            "SELECT * FROM assessment_question_revisions WHERE id=?",
            (first.question_revision_id,),
        ).fetchone()
        provenance = connection.execute(
            "SELECT * FROM question_engine_provenance WHERE question_revision_id=?",
            (first.question_revision_id,),
        ).fetchone()
        counts = (
            connection.execute("SELECT COUNT(*) FROM assessment_question_revisions").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM question_engine_provenance").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM assessment_reference_solutions").fetchone()[0],
        )
    assert question["owner_user_id"] == OWNER
    assert question["source_kind"] == "MODEL_GENERATED"
    assert question["validation_status"] == "VALIDATED"
    assert question["verification_method"] == "AI_REVIEWED"
    answer = json.loads(question["answer_json"])
    assert "correct_option" not in answer
    assert answer["rule_violation_analysis"] is None
    assert answer["verification_notice"] == "AI_REVIEWED_NOT_DETERMINISTIC_PROOF"
    assert AssessmentService._is_deterministic(
        {
            "question_type": question["question_type"],
            "answer_key": answer,
            "verification_method": question["verification_method"],
        }
    ) is False
    assert provenance["publication_status"] == "READY"
    assert counts == (1, 1, 1)


def test_missing_receipt_or_provider_provenance_cannot_become_ready(tmp_path: Path) -> None:
    values = pipeline(tmp_path)
    missing_receipt_id = values["report"].semantic_signals[0].receipt_id
    with values["database"].connect() as connection:
        connection.execute("DELETE FROM jev_decision_receipts WHERE id=?", (missing_receipt_id,))

    result = persist(values)

    assert result.status == "NEEDS_REVIEW"
    assert result.verification_method == "MODEL_ONLY"
    with values["database"].connect() as connection:
        question = connection.execute(
            "SELECT validation_status,verification_method FROM assessment_question_revisions "
            "WHERE id=?",
            (result.question_revision_id,),
        ).fetchone()
    assert tuple(question) == ("NEEDS_REVIEW", "MODEL_ONLY")

    other = pipeline(tmp_path / "missing-provider")
    no_provider_receipt = replace(other["blind"], provider_run=None)
    result = persist(other, blind_receipt=no_provider_receipt)
    assert result.status == "NEEDS_REVIEW"


def test_stale_evidence_or_foreign_owner_rolls_back_without_partial_rows(tmp_path: Path) -> None:
    values = pipeline(tmp_path)
    fragment = values["evidence"].fragments[0]
    with values["database"].connect() as connection:
        connection.execute(
            "INSERT INTO material_evidence(id,node_id,document_version_id,chunk_id,"
            "owner_user_id,source_scope,locator_type,locator_value,status) "
            "VALUES('revoked',?,?,?,?, 'OWNER_COURSE','page','7','REVOKED')",
            (NODE, fragment.document_version_id, fragment.evidence_id, OWNER),
        )

    with pytest.raises(QuestionPersistenceError) as refusal:
        persist(values)
    assert refusal.value.code == "QUESTION_SOURCE_CHANGED"

    with pytest.raises(QuestionPersistenceError) as refusal:
        persist(values, owner_user_id="user-b")
    assert refusal.value.code == "QUESTION_WORKSPACE_NOT_FOUND"
    with values["database"].connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM assessment_question_revisions"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM question_engine_provenance"
        ).fetchone()[0] == 0


def test_ready_revision_leaves_the_pool_when_its_evidence_is_revoked(tmp_path: Path) -> None:
    values = pipeline(tmp_path)
    result = persist(values)
    service = AssessmentService(values["database"])
    with values["database"].connect() as connection:
        workspace = connection.execute(
            "SELECT * FROM learning_workspaces WHERE id=?", (WORKSPACE,)
        ).fetchone()
        node = service._atomic_node(connection, workspace, NODE)
        assert "family-density" in service.distinct_families(connection, workspace, node)
        fragment = values["evidence"].fragments[0]
        connection.execute(
            "INSERT INTO material_evidence(id,node_id,document_version_id,chunk_id,"
            "owner_user_id,source_scope,locator_type,locator_value,status) "
            "VALUES('revoked-after-ready',?,?,?,?, 'OWNER_COURSE','page','7','REVOKED')",
            (NODE, fragment.document_version_id, fragment.evidence_id, OWNER),
        )

    with values["database"].connect() as connection:
        workspace = connection.execute(
            "SELECT * FROM learning_workspaces WHERE id=?", (WORKSPACE,)
        ).fetchone()
        node = service._atomic_node(connection, workspace, NODE)
        assert "family-density" not in service.distinct_families(connection, workspace, node)
        assert connection.execute(
            "SELECT publication_status FROM question_engine_provenance "
            "WHERE question_revision_id=?",
            (result.question_revision_id,),
        ).fetchone()[0] == "READY"


def test_candidate_revision_hash_is_recomputed_before_storage(tmp_path: Path) -> None:
    values = pipeline(tmp_path)
    public = values["candidate"].public_question.model_copy(
        update={"question_text": values["candidate"].public_question.question_text + " tampered"}
    )
    tampered = values["candidate"].model_copy(update={"public_question": public})

    with pytest.raises(QuestionPersistenceError) as refusal:
        persist(values, candidate=tampered)

    assert refusal.value.code == "QUESTION_REVISION_MISMATCH"
    with values["database"].connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM assessment_question_revisions"
        ).fetchone()[0] == 0


def test_identical_revision_hash_is_idempotent_only_within_one_workspace(
    tmp_path: Path,
) -> None:
    values = pipeline(tmp_path)
    first = persist(values)
    second_owner = "user-b"
    second_workspace = "workspace-question-engine-b"
    with values["database"].connect() as connection:
        connection.execute(
            "UPDATE courses SET visibility='public',publication_status='published' WHERE id=?",
            (COURSE,),
        )
        connection.execute(
            "INSERT INTO courses(id,name,owner_user_id,course_type,visibility,"
            "publication_status) VALUES(?,? ,?,'user','private','private')",
            ("course-question-engine-private-b", "Second private corpus", second_owner),
        )
        connection.execute(
            "INSERT INTO learning_workspaces(id,owner_user_id,course_id,private_course_id) "
            "VALUES(?,?,?,?)",
            (
                second_workspace,
                second_owner,
                COURSE,
                "course-question-engine-private-b",
            ),
        )

    second = persist(
        values,
        owner_user_id=second_owner,
        workspace_id=second_workspace,
    )

    assert first.question_revision_id != second.question_revision_id
    assert second.idempotent is False
    assert second.status == "NEEDS_REVIEW"
    with values["database"].connect() as connection:
        owners = {
            row["owner_user_id"]
            for row in connection.execute(
                "SELECT owner_user_id FROM assessment_question_revisions"
            )
        }
    assert owners == {OWNER, second_owner}


def test_changed_blind_output_cannot_reuse_semantic_receipts_for_ready(
    tmp_path: Path,
) -> None:
    values = pipeline(tmp_path)
    blind_payload = json.loads(values["blind"].output)
    blind_payload["conclusion"] = "A different conclusion inserted after validation."
    changed_blind = replace(
        values["blind"],
        output=json.dumps(blind_payload, ensure_ascii=False),
    )

    result = persist(values, blind_receipt=changed_blind)

    assert result.status == "NEEDS_REVIEW"
    assert result.readiness_reason == "JEV_RECEIPT_NOT_DURABLE_OR_SCOPED"


def test_changed_author_input_receipt_cannot_promote_ready(tmp_path: Path) -> None:
    values = pipeline(tmp_path)
    changed_run = values["candidate"].provider_run.model_copy(
        update={"input_hash": "c" * 64}
    )
    changed_candidate = values["candidate"].model_copy(update={"provider_run": changed_run})

    result = persist(values, candidate=changed_candidate)

    assert result.status == "NEEDS_REVIEW"
    assert result.readiness_reason == "AUTHOR_PROVENANCE_INCOMPLETE"
