import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from openai import OpenAI
from pydantic import SecretStr

from app.config import Settings
from app.db import Database
from app.errors import ApiError
from app.learning.assessments import AssessmentService
from app.learning.knowledge import KnowledgeService
from app.learning.models import AutoKnowledgeMapDraft, AutoKnowledgeSpecSetDraft
from app.learning.orchestrator import LearningOrchestrator
from app.learning.provider import LearningProvider
from app.rag.retrieval import HybridRetriever
from app.repositories.chunks import ChunkRepository
from app.services.auto_knowledge_map import (
    AUTO_MODEL_MAX_OUTPUT_TOKENS,
    BUILDER_VERSION,
    AutoKnowledgeMapService,
    OrchestratorDraftGenerator,
    canonical_json,
    digest,
)


class FakeGenerator:
    def __init__(self) -> None:
        self.calls = 0
        self.evidence_ids: list[str] = []
        self.evidence: list[dict[str, Any]] = []

    def generate(
        self,
        *,
        job_id: str,
        workspace_id: str,
        course: dict[str, Any],
        evidence: list[dict[str, Any]],
        heartbeat=None,
    ) -> tuple[AutoKnowledgeMapDraft, AutoKnowledgeSpecSetDraft, int]:
        self.calls += 1
        if heartbeat:
            heartbeat()
        self.evidence = evidence
        self.evidence_ids = [str(item["id"]) for item in evidence]
        node_evidence = self.evidence_ids[:]
        return (
            AutoKnowledgeMapDraft.model_validate(
                {
                    "title": f"{course['name']} AI learning map",
                    "modules": [
                        {
                            "key": "foundations",
                            "title": "Foundations",
                            "description": "Concepts grounded in the uploaded materials",
                            "major": "OTHER",
                        }
                    ],
                    "nodes": [
                        {
                            "key": "core-concept",
                            "parent_key": "foundations",
                            "title": "Core concept",
                            "description": "The central concept in the frozen sources",
                            "major": "OTHER",
                            "prerequisite_keys": [],
                            "evidence_ids": node_evidence,
                        }
                    ],
                }
            ),
            AutoKnowledgeSpecSetDraft.model_validate(
                {
                    "specs": [
                        {
                            "node_key": "core-concept",
                            "change_reason": "Generated from the frozen private source set",
                            "items": [
                                {
                                    "item_id": "explain",
                                    "requirement": "REQUIRED",
                                    "objective": "Explain the core concept",
                                    "acceptance": (
                                        "Explain it accurately and apply it to one example"
                                    ),
                                    "evidence_ids": node_evidence,
                                }
                            ],
                        }
                    ]
                }
            ),
            2,
        )


class RecordingLearning:
    """Provider-free stand-in for the production orchestrator boundary."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate(self, workspace_id, operation, schema, **kwargs):
        context = kwargs["context"]
        serialized = json.dumps(context, ensure_ascii=False, sort_keys=True)
        assert len(serialized) < 60_000
        self.calls.append(
            {
                "operation": operation,
                "schema": schema.__name__,
                "context_size": len(serialized),
                "instructions": kwargs["instructions"],
                "max_output_tokens": kwargs.get("max_output_tokens"),
            }
        )
        if schema.__name__ == "AutoKnowledgeMapDraft":
            assert len(context["frozen_source_segments"]) <= 6
            assert all(
                "source_evidence_id" not in item
                for item in context["frozen_source_segments"]
            )
            ids = [item["id"] for item in context["frozen_source_segments"]]
            output = schema.model_validate(
                {
                    "title": "Bounded shard",
                    "modules": [
                        {
                            "key": "module",
                            "title": "Course foundations",
                            "description": "Grounded grouping",
                            "major": "OTHER",
                        }
                    ],
                    "nodes": [
                        {
                            "key": "core",
                            "parent_key": "module",
                            "title": "Core knowledge",
                            "description": "Grounded in every bounded source part",
                            "major": "OTHER",
                            "prerequisite_keys": [],
                            "evidence_ids": ids,
                        }
                    ],
                    "dispositions": [
                        {
                            "evidence_id": value,
                            "status": "MAPPED",
                            "reason": "Mapped to the core node",
                            "node_keys": ["core"],
                        }
                        for value in ids
                    ],
                }
            )
        else:
            output = schema.model_validate(
                {
                    "specs": [
                        {
                            "node_key": node["key"],
                            "change_reason": "Frozen source analysis",
                            "items": [
                                {
                                    "item_id": "required_core",
                                    "requirement": "REQUIRED",
                                    "objective": "Explain the grounded core knowledge",
                                    "acceptance": "Explain and apply it accurately",
                                    "evidence_ids": node["evidence_ids"][:1],
                                }
                            ],
                        }
                        for node in context["knowledge_nodes"]
                    ]
                }
            )
        return output, {"status": "COMPLETED"}


class RepairingLearning(RecordingLearning):
    def __init__(self) -> None:
        super().__init__()
        self.rejected = False

    def generate(self, workspace_id, operation, schema, **kwargs):
        if schema.__name__ == "AutoKnowledgeMapDraft" and not self.rejected:
            self.rejected = True
            self.calls.append(
                {
                    "operation": operation,
                    "schema": schema.__name__,
                    "instructions": kwargs["instructions"],
                    "max_output_tokens": kwargs.get("max_output_tokens"),
                }
            )
            output = schema.model_validate(
                {"title": "Incomplete first response", "modules": [], "nodes": []}
            )
            sink = kwargs.get("transport_event_sink")
            if sink is not None:
                output_text = json.dumps(output.model_dump(), sort_keys=True)
                sink({"phase": "SEND_INTENT", "input_hash": "a" * 64})
                sink(
                    {
                        "phase": "RESPONSE_COMPLETE",
                        "provider_response_id": "repairing-learning-1",
                        "output_text": output_text,
                    }
                )
                sink({"phase": "CONTRACT_VALID"})
            return output, {"status": "COMPLETED"}
        output, run = super().generate(workspace_id, operation, schema, **kwargs)
        sink = kwargs.get("transport_event_sink")
        if sink is not None:
            output_text = json.dumps(output.model_dump(), sort_keys=True)
            sink({"phase": "SEND_INTENT", "input_hash": "b" * 64})
            sink(
                {
                    "phase": "RESPONSE_COMPLETE",
                    "provider_response_id": f"repairing-learning-{operation}",
                    "output_text": output_text,
                }
            )
            sink({"phase": "CONTRACT_VALID"})
        return output, run


class MultiShardRepairingLearning(RecordingLearning):
    def __init__(self) -> None:
        super().__init__()
        self.rejected_operations: set[str] = set()

    def generate(self, workspace_id, operation, schema, **kwargs):
        if (
            schema.__name__ == "AutoKnowledgeMapDraft"
            and "-r" not in operation
            and len(self.rejected_operations) < 3
        ):
            self.rejected_operations.add(operation)
            self.calls.append(
                {
                    "operation": operation,
                    "schema": schema.__name__,
                    "instructions": kwargs["instructions"],
                    "max_output_tokens": kwargs.get("max_output_tokens"),
                }
            )
            return schema.model_validate(
                {"title": "Incomplete shard", "modules": [], "nodes": []}
            ), {"status": "COMPLETED"}
        return super().generate(workspace_id, operation, schema, **kwargs)


class FixedEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


def response_payload(output: dict[str, Any], ordinal: int) -> dict[str, Any]:
    return {
        "id": f"resp_auto_map_{ordinal}",
        "object": "response",
        "created_at": ordinal,
        "status": "completed",
        "background": False,
        "billing": {"payer": "developer"},
        "error": None,
        "incomplete_details": None,
        "instructions": "bounded automatic map",
        "max_output_tokens": 4000,
        "max_tool_calls": None,
        "model": "deepseek-flash",
        "output": [
            {
                "id": f"msg_auto_map_{ordinal}",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "annotations": [],
                        "logprobs": [],
                        "text": json.dumps(output, ensure_ascii=False),
                    }
                ],
            }
        ],
        "parallel_tool_calls": False,
        "previous_response_id": None,
        "prompt_cache_key": None,
        "prompt_cache_retention": None,
        "reasoning": {"effort": "none", "summary": None},
        "safety_identifier": None,
        "service_tier": "default",
        "store": False,
        "temperature": 1.0,
        "text": {"format": {"type": "text"}, "verbosity": "medium"},
        "tool_choice": "auto",
        "tools": [],
        "top_logprobs": 0,
        "top_p": 1.0,
        "truncation": "disabled",
        "usage": {
            "input_tokens": 100 + ordinal,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 50 + ordinal,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 150 + (2 * ordinal),
        },
        "user": None,
        "metadata": {},
    }


def settings_at(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        v3_enabled=True,
        rag_provider_mode="deterministic",
        app_env="test",
        auth_test_user_id="owner-a",
        admin_user_ids="admin",
    )


def private_workspace(database: Database) -> str:
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO courses(id,name,owner_user_id,course_type,visibility,publication_status) "
            "VALUES('private-course','Private course','owner-a','user','private','private')"
        )
        connection.execute(
            "INSERT INTO courses(id,name,owner_user_id,course_type,visibility,publication_status) "
            "VALUES('private-corpus','Private corpus','owner-a','user','private','private')"
        )
        connection.execute(
            "INSERT INTO learning_workspaces(id,owner_user_id,course_id,private_course_id) "
            "VALUES('workspace-a','owner-a','private-course','private-corpus')"
        )
    return "workspace-a"


def ready_document(
    database: Database,
    *,
    document_id: str,
    chunk_id: str,
    content: str,
    course_id: str = "private-corpus",
) -> None:
    payload = content.encode()
    path = database.upload_dir / f"{document_id}.txt"
    path.write_bytes(payload)
    import hashlib

    with database.connect() as connection:
        connection.execute(
            "INSERT INTO documents(id,course_id,filename,stored_path,media_type,extension,"
            "sha256,byte_size,status) VALUES(?,?,?,?,'text/plain','.txt',?,?, 'processing')",
            (
                document_id,
                course_id,
                f"{document_id}.txt",
                str(path),
                hashlib.sha256(payload).hexdigest(),
                len(payload),
            ),
        )
        connection.execute(
            "INSERT INTO chunks(id,document_id,course_id,ordinal,content,locator_type,"
            "locator_value,embedding) VALUES(?,?,?,0,?,'line','1','[1.0]')",
            (chunk_id, document_id, course_id, content),
        )
        connection.execute(
            "UPDATE documents SET status='ready',chunk_count=1 WHERE id=?", (document_id,)
        )


def service_at(tmp_path: Path) -> tuple[Database, AutoKnowledgeMapService, FakeGenerator]:
    settings = settings_at(tmp_path)
    database = Database(settings)
    database.initialize()
    private_workspace(database)
    generator = FakeGenerator()
    service = AutoKnowledgeMapService(
        database,
        settings,
        learning=object(),  # type: ignore[arg-type]
        generator=generator,
    )
    return database, service, generator


def test_private_upload_batch_builds_one_active_tree_and_spec(tmp_path: Path) -> None:
    database, service, generator = service_at(tmp_path)
    ready_document(
        database,
        document_id="doc-one",
        chunk_id="chunk-one",
        content="A vector has magnitude and direction.",
    )
    ready_document(
        database,
        document_id="doc-two",
        chunk_id="chunk-two",
        content="Vector addition combines components.",
    )

    reconciled = service.reconcile(force=True)
    assert service.run_once("wrong-target-worker", target_key="PRIVATE:not-present") is None
    result = service.run_once("test-worker", target_key="PRIVATE:workspace-a")

    assert reconciled["QUEUED"] == 1
    assert result is not None and result["status"] == "READY"
    assert generator.calls == 1
    assert generator.evidence_ids == ["chunk-one", "chunk-two"]
    with database.connect() as connection:
        jobs = connection.execute("SELECT * FROM auto_knowledge_jobs").fetchall()
        target = connection.execute(
            "SELECT * FROM auto_knowledge_targets WHERE target_key='PRIVATE:workspace-a'"
        ).fetchone()
        tree = connection.execute(
            "SELECT * FROM knowledge_tree_versions WHERE id=?", (target["active_tree_version_id"],)
        ).fetchone()
        atomic = connection.execute(
            "SELECT node.* FROM knowledge_tree_memberships AS member "
            "JOIN knowledge_nodes AS node ON node.id=member.node_id "
            "WHERE member.tree_version_id=? AND node.kind='ATOMIC'",
            (tree["id"],),
        ).fetchone()


        spec = connection.execute(
            "SELECT metadata.status,item.requirement,item.evidence_ids_json "
            "FROM teaching_spec_metadata AS metadata JOIN teaching_items AS item "
            "ON item.node_id=metadata.node_id AND item.spec_version=metadata.version "
            "WHERE metadata.node_id=?",
            (atomic["id"],),
        ).fetchone()
        receipts = connection.execute("SELECT * FROM auto_knowledge_job_receipts").fetchall()
        material_evidence = connection.execute(
            "SELECT node_id,document_version_id,chunk_id,owner_user_id,source_scope,"
            "locator_type,locator_value,status FROM material_evidence WHERE node_id=? "
            "ORDER BY chunk_id",
            (atomic["id"],),
        ).fetchall()

    assert len(jobs) == 1
    assert jobs[0]["status"] == "READY"
    assert jobs[0]["model_calls_made"] == 2
    assert target["status"] == "READY"
    assert tree["tree_kind"] == "PERSONALIZED"
    assert tree["status"] == "ACTIVE"
    assert atomic["owner_user_id"] == "owner-a"
    assert atomic["status"] == "PRIVATE"
    assert spec["status"] == "PRIVATE_ACTIVE"
    assert spec["requirement"] == "REQUIRED"
    assert json.loads(spec["evidence_ids_json"]) == ["chunk-one", "chunk-two"]
    assert [dict(row) for row in material_evidence] == [
        {
            "node_id": atomic["id"],
            "document_version_id": "doc-one-v1",
            "chunk_id": "chunk-one",
            "owner_user_id": "owner-a",
            "source_scope": "WORKSPACE_PRIVATE",
            "locator_type": "line",
            "locator_value": "1",
            "status": "ACTIVE",
        },
        {
            "node_id": atomic["id"],
            "document_version_id": "doc-two-v1",
            "chunk_id": "chunk-two",
            "owner_user_id": "owner-a",
            "source_scope": "WORKSPACE_PRIVATE",
            "locator_type": "line",
            "locator_value": "1",
            "status": "ACTIVE",
        },
    ]
    assert len(receipts) == 1 and receipts[0]["status"] == "READY"


def test_staged_official_course_build_uses_an_internal_metering_workspace(
    tmp_path: Path,
) -> None:
    settings = settings_at(tmp_path)
    database = Database(settings)
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO courses(id,name,course_type,visibility,publication_status) "
            "VALUES('staged-campus','Staged campus','official','private','private')"
        )
    ready_document(
        database,
        document_id="staged-campus-doc",
        chunk_id="staged-campus-chunk",
        content="A staged campus course must build before public activation.",
        course_id="staged-campus",
    )
    generator = FakeGenerator()
    service = AutoKnowledgeMapService(
        database,
        settings,
        learning=object(),  # type: ignore[arg-type]
        generator=generator,
    )

    assert service.reconcile(force=True)["QUEUED"] == 1
    result = service.run_once("staged-campus-worker")

    assert result is not None and result["status"] == "READY"
    assert generator.calls == 1
    with database.connect() as connection:
        course = connection.execute(
            "SELECT visibility,publication_status FROM courses WHERE id='staged-campus'"
        ).fetchone()
        workspace = connection.execute(
            "SELECT * FROM learning_workspaces WHERE course_id='staged-campus'"
        ).fetchone()
        corpus = connection.execute(
            "SELECT owner_user_id,course_type,visibility,publication_status FROM courses "
            "WHERE id=?",
            (workspace["private_course_id"],),
        ).fetchone()
    assert tuple(course) == ("private", "private")
    assert workspace["owner_user_id"] == "admin"
    assert tuple(corpus) == ("admin", "user", "private", "private")


def test_pre_dispatch_staged_course_access_failure_has_one_audited_recovery(
    tmp_path: Path,
) -> None:
    settings = settings_at(tmp_path).model_copy(
        update={
            "auto_knowledge_map_enabled": True,
            "auto_knowledge_map_allow_billable": True,
        }
    )
    database = Database(settings)
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO courses(id,name,course_type,visibility,publication_status) "
            "VALUES('staged-recovery','Staged recovery','official','private','private')"
        )
    ready_document(
        database,
        document_id="staged-recovery-doc",
        chunk_id="staged-recovery-chunk",
        content="The old worker stopped before provider dispatch.",
        course_id="staged-recovery",
    )
    generator = FakeGenerator()
    service = AutoKnowledgeMapService(
        database,
        settings,
        learning=object(),  # type: ignore[arg-type]
        generator=generator,
    )
    assert service.reconcile(force=True)["QUEUED"] == 1
    with database.connect() as connection:
        job = connection.execute("SELECT * FROM auto_knowledge_jobs").fetchone()
        connection.execute(
            "UPDATE auto_knowledge_jobs SET status='BLOCKED',error_code='COURSE_NOT_FOUND',"
            "error_message='The course was not found.',completed_at=? WHERE id=?",
            ("2026-09-27T00:00:00.000Z", job["id"]),
        )
        connection.execute(
            "UPDATE auto_knowledge_targets SET status='BLOCKED',"
            "message='The course was not found.' WHERE target_key=?",
            (job["target_key"],),
        )
        connection.execute(
            "INSERT INTO auto_knowledge_job_receipts("
            "job_id,target_key,corpus_fingerprint,status,source_snapshot_hash,"
            "model_calls_made,detail_json) VALUES(?,?,?,'BLOCKED',?,0,?)",
            (
                job["id"],
                job["target_key"],
                job["corpus_fingerprint"],
                digest(json.loads(job["source_snapshot_json"])),
                json.dumps(
                    {
                        "error_code": "COURSE_NOT_FOUND",
                        "error_message": "The course was not found.",
                    }
                ),
            ),
        )

    reconciled = service.reconcile(force=True)
    assert reconciled["RECOVERED_SAFE_FAILURE"] == 1
    completed = service.run_once("staged-course-recovery-worker")
    assert completed is not None and completed["status"] == "READY"

    with database.connect() as connection:
        recovery = connection.execute(
            "SELECT reason,prior_receipt_json FROM auto_knowledge_job_recovery_receipts "
            "WHERE job_id=?",
            (job["id"],),
        ).fetchone()
        current = connection.execute(
            "SELECT status,error_code FROM auto_knowledge_jobs WHERE id=?", (job["id"],)
        ).fetchone()
    assert recovery["reason"] == "STAGED_COURSE_WORKSPACE_V1"
    assert json.loads(recovery["prior_receipt_json"])["status"] == "BLOCKED"
    assert tuple(current) == ("READY", None)


def test_explicit_multi_file_batch_waits_for_seal_then_builds_once(tmp_path: Path) -> None:
    database, service, generator = service_at(tmp_path)
    opened = service.begin_upload_batch(
        course_id="private-course",
        source_course_id="private-corpus",
        owner_user_id="owner-a",
        batch_id="batch-one",
        expected_items=2,
    )
    assert opened["status"] == "OPEN"
    ready_document(
        database,
        document_id="batch-doc-one",
        chunk_id="batch-chunk-one",
        content="The first file finished before the second one.",
    )
    service.record_upload_batch_item(
        batch_id="batch-one",
        item_key="item-one",
        course_id="private-course",
        owner_user_id="owner-a",
        status="INDEXED",
        document_id="batch-doc-one",
    )

    assert service.reconcile(force=True)["BATCH_OPEN"] == 1
    assert service.run_once("too-early") is None

    ready_document(
        database,
        document_id="batch-doc-two",
        chunk_id="batch-chunk-two",
        content="The second file completes the same logical corpus revision.",
    )
    service.record_upload_batch_item(
        batch_id="batch-one",
        item_key="item-two",
        course_id="private-course",
        owner_user_id="owner-a",
        status="INDEXED",
        document_id="batch-doc-two",
    )
    manifest = [
        {"item_key": "item-one", "status": "INDEXED", "document_id": "batch-doc-one"},
        {"item_key": "item-two", "status": "INDEXED", "document_id": "batch-doc-two"},
    ]
    sealed = service.seal_upload_batch(
        course_id="private-course",
        owner_user_id="owner-a",
        batch_id="batch-one",
        items=manifest,
    )
    repeated = service.seal_upload_batch(
        course_id="private-course",
        owner_user_id="owner-a",
        batch_id="batch-one",
        items=manifest,
    )
    assert sealed["status"] == repeated["status"] == "SEALED"

    assert service.reconcile(force=True)["QUEUED"] == 1
    assert service.run_once("after-seal")["status"] == "READY"
    assert generator.calls == 1
    assert generator.evidence_ids == ["batch-chunk-one", "batch-chunk-two"]
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM auto_knowledge_jobs").fetchone()[0] == 1


def test_canvas_local_import_waits_for_terminal_session_then_builds_once(
    tmp_path: Path,
) -> None:
    database, service, generator = service_at(tmp_path)
    ready_document(
        database,
        document_id="canvas-doc",
        chunk_id="canvas-chunk",
        content="A Canvas batch must finish before its course map is frozen.",
    )
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO canvas_local_sessions("
            "id,owner_user_id,institution_key,institution_origin,code_hash,status,expires_at) "
            "VALUES('canvas-session','owner-a','school','https://canvas.example.edu',"
            "'canvas-code-hash','IMPORTING','2099-01-01T00:00:00.000Z')"
        )
        connection.execute(
            "INSERT INTO canvas_local_files("
            "id,session_id,canvas_course_id,canvas_file_id,display_name,size_bytes,"
            "content_sha256,target_course_id,local_document_id,status) "
            "VALUES('canvas-file','canvas-session','source-course','source-file',"
            "'lecture.txt',64,?,'private-corpus','canvas-doc','INDEXED')",
            ("a" * 64,),
        )

    assert service.reconcile(force=True)["IMPORT_OPEN"] == 1
    assert service.run_once("canvas-too-early") is None

    with database.connect() as connection:
        connection.execute(
            "UPDATE canvas_local_sessions SET status='COMPLETED',completed_at=? "
            "WHERE id='canvas-session'",
            ("2026-09-27T00:00:00.000Z",),
        )

    assert service.reconcile(force=True)["QUEUED"] == 1
    assert service.run_once("canvas-after-complete")["status"] == "READY"
    assert generator.calls == 1
    assert generator.evidence_ids == ["canvas-chunk"]
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM auto_knowledge_jobs").fetchone()[0] == 1


def test_same_frozen_versions_are_idempotent_and_do_not_regenerate(tmp_path: Path) -> None:
    database, service, generator = service_at(tmp_path)
    ready_document(
        database,
        document_id="doc-one",
        chunk_id="chunk-one",
        content="A real source concept.",
    )
    service.reconcile(force=True)
    assert service.run_once("test-worker") is not None

    service.reconcile(force=True)
    assert service.run_once("test-worker") is None

    with database.connect() as connection:
        job_count = connection.execute("SELECT COUNT(*) FROM auto_knowledge_jobs").fetchone()[0]
        tree_count = connection.execute(
            "SELECT COUNT(*) FROM knowledge_tree_versions WHERE workspace_id='workspace-a'"
        ).fetchone()[0]
    assert generator.calls == 1
    assert job_count == 1
    assert tree_count == 1


def test_empty_or_unreadable_course_waits_without_fake_nodes_or_model_call(
    tmp_path: Path,
) -> None:
    database, service, generator = service_at(tmp_path)

    result = service.reconcile(force=True)

    assert result["WAITING_SOURCE"] == 1
    assert service.run_once("test-worker") is None
    assert generator.calls == 0
    with database.connect() as connection:
        target = connection.execute(
            "SELECT status,message FROM auto_knowledge_targets "
            "WHERE target_key='PRIVATE:workspace-a'"
        ).fetchone()
        nodes = connection.execute("SELECT COUNT(*) FROM knowledge_nodes").fetchone()[0]
    assert target["status"] == "WAITING_SOURCE"
    assert "No readable" in target["message"]
    assert nodes == 0


def test_reviewed_official_tree_is_authoritative_and_never_regenerated(
    tmp_path: Path,
) -> None:
    settings = settings_at(tmp_path)
    database = Database(settings)
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO courses(id,name,course_type,visibility,publication_status) "
            "VALUES('reviewed-course','Reviewed course','official','public','draft')"
        )
    ready_document(
        database,
        document_id="reviewed-doc",
        chunk_id="reviewed-chunk",
        content="New material cannot replace the reviewed tree automatically.",
        course_id="reviewed-course",
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE courses SET publication_status='published' WHERE id='reviewed-course'"
        )
        connection.execute(
            "INSERT INTO knowledge_tree_versions("
            "id,course_id,tree_kind,version,status,title,change_reason,content_hash,"
            "reviewed_by_user_id,reviewed_at) "
            "VALUES('reviewed-tree','reviewed-course','OFFICIAL',1,'PUBLISHED',"
            "'Reviewed tree','Human review','"
            + "a" * 64
            + "','reviewer','2026-09-27T00:00:00Z')"
        )
    generator = FakeGenerator()
    service = AutoKnowledgeMapService(
        database,
        settings,
        learning=object(),  # type: ignore[arg-type]
        generator=generator,
    )

    result = service.reconcile(force=True)

    assert result["EXISTING_ACTIVE"] == 1
    assert service.run_once("should-not-run") is None
    assert generator.calls == 0
    with database.connect() as connection:
        target = connection.execute(
            "SELECT status,active_tree_version_id FROM auto_knowledge_targets"
        ).fetchone()
        assert connection.execute("SELECT COUNT(*) FROM auto_knowledge_jobs").fetchone()[0] == 0
    assert dict(target) == {
        "status": "EXISTING_ACTIVE",
        "active_tree_version_id": "reviewed-tree",
    }


def test_existing_private_tree_stays_active_until_incremental_replacement_is_ready(
    tmp_path: Path,
) -> None:
    database, service, generator = service_at(tmp_path)
    spec_content = json.dumps(
        [
            {
                "item_id": "legacy-required",
                "requirement": "REQUIRED",
                "objective": "Explain the existing private concept",
                "acceptance": "Explain it accurately",
                "evidence_ids": [],
            }
        ],
        sort_keys=True,
    )
    import hashlib

    with database.connect() as connection:
        connection.execute(
            "INSERT INTO knowledge_nodes(id,course_id,owner_user_id,title,description,"
            "major,kind,status) VALUES('legacy-private-node','private-course','owner-a',"
            "'Legacy node','Existing learner structure','OTHER','ATOMIC','PRIVATE')"
        )
        connection.execute(
            "INSERT INTO teaching_specs(node_id,version,content_json,content_hash) "
            "VALUES('legacy-private-node',1,?,?)",
            (spec_content, hashlib.sha256(spec_content.encode()).hexdigest()),
        )
        connection.execute(
            "UPDATE teaching_spec_metadata SET status='PRIVATE_ACTIVE' "
            "WHERE node_id='legacy-private-node' AND version=1"
        )
        connection.execute(
            "INSERT INTO knowledge_tree_versions("
            "id,course_id,workspace_id,owner_user_id,tree_kind,version,status,title,"
            "change_reason,content_hash) VALUES('legacy-private-tree','private-course',"
            "'workspace-a','owner-a','PERSONALIZED',1,'DRAFT','Existing private map',"
            "'Pre-upgrade learner map',?)",
            ("b" * 64,),
        )
        connection.execute(
            "INSERT INTO knowledge_tree_memberships("
            "tree_version_id,node_id,parent_node_id,ordinal,teaching_spec_version) "
            "VALUES('legacy-private-tree','legacy-private-node',NULL,0,1)"
        )
        connection.execute(
            "UPDATE knowledge_tree_versions SET status='ACTIVE' "
            "WHERE id='legacy-private-tree'"
        )

    # Installing the feature records the existing tree as a baseline; it does
    # not rebuild or replace already-valid learner structure during backfill.
    assert service.reconcile(force=True)["EXISTING_ACTIVE"] == 1
    assert service.run_once("baseline-must-not-run") is None
    assert generator.calls == 0

    # A later source revision is incremental work. The old tree remains active
    # while that new frozen revision is generated and validated.
    ready_document(
        database,
        document_id="incremental-doc",
        chunk_id="incremental-chunk",
        content="New material should produce a replacement without an availability gap.",
    )
    original_generate = generator.generate

    def assert_old_version_available(**kwargs):
        with database.connect() as connection:
            old = connection.execute(
                "SELECT status FROM knowledge_tree_versions "
                "WHERE id='legacy-private-tree'"
            ).fetchone()
        assert old["status"] == "ACTIVE"
        return original_generate(**kwargs)

    generator.generate = assert_old_version_available  # type: ignore[method-assign]

    assert service.reconcile(force=True)["QUEUED"] == 1
    result = service.run_once("incremental-private-worker")

    assert result is not None and result["status"] == "READY"
    with database.connect() as connection:
        old = connection.execute(
            "SELECT status FROM knowledge_tree_versions WHERE id='legacy-private-tree'"
        ).fetchone()
        active = connection.execute(
            "SELECT id,base_tree_version_id FROM knowledge_tree_versions "
            "WHERE workspace_id='workspace-a' AND status='ACTIVE'"
        ).fetchone()
        old_node_count = connection.execute(
            "SELECT COUNT(*) FROM knowledge_nodes WHERE id='legacy-private-node'"
        ).fetchone()[0]
        old_node_in_replacement = connection.execute(
            "SELECT COUNT(*) FROM knowledge_tree_memberships "
            "WHERE tree_version_id=? AND node_id='legacy-private-node'",
            (active["id"],),
        ).fetchone()[0]
    assert old["status"] == "RETIRED"
    assert active["id"] != "legacy-private-tree"
    assert active["base_tree_version_id"] == "legacy-private-tree"
    assert old_node_count == 1
    assert old_node_in_replacement == 1


def test_upload_event_respects_quiet_window_and_status_get_only_reads(tmp_path: Path) -> None:
    database, service, generator = service_at(tmp_path)
    ready_document(
        database,
        document_id="quiet-doc",
        chunk_id="quiet-chunk",
        content="A source waiting for its batch quiet window.",
    )

    assert service.reconcile() == {}
    assert service.reconcile(full=True) == {"QUIET_WINDOW": 1}
    before = service.status("private-course", "owner-a")
    after = service.status("private-course", "owner-a")

    assert before["status"] == after["status"] == "QUEUED"
    assert before["pending_source_events"] == after["pending_source_events"] == 1
    assert generator.calls == 0
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM auto_knowledge_jobs").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM learning_model_call_reservations").fetchone()[
                0
            ]
            == 0
        )


def test_ready_on_insert_is_captured_for_trusted_importers(tmp_path: Path) -> None:
    database, _service, generator = service_at(tmp_path)
    payload = b"Trusted import content"
    path = tmp_path / "trusted-import.txt"
    path.write_bytes(payload)
    import hashlib

    with database.connect() as connection:
        connection.execute(
            "INSERT INTO documents(id,course_id,filename,stored_path,media_type,extension,"
            "sha256,byte_size,status) "
            "VALUES('trusted-doc','private-corpus',?,?,'text/plain','.txt',"
            "?,?,'ready')",
            (str(path), str(path), hashlib.sha256(payload).hexdigest(), len(payload)),
        )
        event = connection.execute(
            "SELECT source_course_id,document_id,event_kind,status "
            "FROM auto_knowledge_source_events WHERE document_id='trusted-doc'"
        ).fetchone()

    assert dict(event) == {
        "source_course_id": "private-corpus",
        "document_id": "trusted-doc",
        "event_kind": "DOCUMENT_READY",
        "status": "PENDING",
    }
    assert generator.calls == 0


def test_source_version_change_during_generation_fails_revision_fence(
    tmp_path: Path,
) -> None:
    database, service, generator = service_at(tmp_path)
    ready_document(
        database,
        document_id="doc-one",
        chunk_id="chunk-one",
        content="Initial content.",
    )
    original_generate = generator.generate

    def changing_generate(**kwargs):
        output = original_generate(**kwargs)
        ready_document(
            database,
            document_id="doc-two",
            chunk_id="chunk-two",
            content="A concurrent source update.",
        )
        return output

    generator.generate = changing_generate  # type: ignore[method-assign]
    service.reconcile(force=True)

    result = service.run_once("test-worker")

    assert result is not None and result["status"] == "FAILED"
    assert result["error"] == "AUTO_SOURCE_CHANGED"
    with database.connect() as connection:
        trees = connection.execute("SELECT COUNT(*) FROM knowledge_tree_versions").fetchone()[0]
        target = connection.execute(
            "SELECT status FROM auto_knowledge_targets WHERE target_key='PRIVATE:workspace-a'"
        ).fetchone()
    assert trees == 0
    assert target["status"] == "FAILED"


def test_stale_queued_snapshot_is_superseded_before_any_model_call(tmp_path: Path) -> None:
    database, service, generator = service_at(tmp_path)
    ready_document(
        database,
        document_id="doc-one",
        chunk_id="chunk-one",
        content="Initial content.",
    )
    service.reconcile(force=True)
    ready_document(
        database,
        document_id="doc-two",
        chunk_id="chunk-two",
        content="Changed before the queued job was claimed.",
    )

    result = service.run_once("stale-worker")

    assert result is not None and result["status"] == "SUPERSEDED"
    assert generator.calls == 0
    with database.connect() as connection:
        job = connection.execute("SELECT * FROM auto_knowledge_jobs").fetchone()
        receipt = connection.execute("SELECT * FROM auto_knowledge_job_receipts").fetchone()
    assert job["model_calls_made"] == 0
    assert receipt["status"] == "SUPERSEDED"


def test_late_provider_result_cannot_overwrite_an_unknown_lease_receipt(tmp_path: Path) -> None:
    database, service, generator = service_at(tmp_path)
    ready_document(
        database,
        document_id="lease-doc",
        chunk_id="lease-chunk",
        content="A provider result that arrives after lease recovery.",
    )
    original_generate = generator.generate

    def expire_lease(**kwargs):
        output = original_generate(**kwargs)
        with database.connect() as connection:
            job = connection.execute(
                "SELECT * FROM auto_knowledge_jobs WHERE status='RUNNING'"
            ).fetchone()
            connection.execute(
                "UPDATE auto_knowledge_jobs SET status='UNKNOWN',model_calls_made=2,"
                "lease_owner=NULL,lease_expires_at=NULL,error_code='LEASE_EXPIRED' "
                "WHERE id=?",
                (job["id"],),
            )
            connection.execute(
                "UPDATE auto_knowledge_targets SET status='UNKNOWN',message='lease expired' "
                "WHERE target_key=?",
                (job["target_key"],),
            )
            connection.execute(
                "INSERT INTO auto_knowledge_job_receipts("
                "job_id,target_key,corpus_fingerprint,status,source_snapshot_hash,"
                "model_calls_made,detail_json) VALUES(?,?,?,'UNKNOWN',?,2,'{}')",
                (
                    job["id"],
                    job["target_key"],
                    job["corpus_fingerprint"],
                    "f" * 64,
                ),
            )
        return output

    generator.generate = expire_lease  # type: ignore[method-assign]
    service.reconcile(force=True)

    result = service.run_once("expired-worker")

    assert result is not None
    assert result["status"] == "UNKNOWN"
    assert result["error"] == "AUTO_LEASE_LOST"
    with database.connect() as connection:
        job = connection.execute("SELECT status,error_code FROM auto_knowledge_jobs").fetchone()
        target = connection.execute("SELECT status,message FROM auto_knowledge_targets").fetchone()
        receipt = connection.execute(
            "SELECT status,model_calls_made FROM auto_knowledge_job_receipts"
        ).fetchone()
        assert connection.execute("SELECT COUNT(*) FROM knowledge_tree_versions").fetchone()[0] == 0
    assert dict(job) == {"status": "UNKNOWN", "error_code": "LEASE_EXPIRED"}
    assert dict(target) == {"status": "UNKNOWN", "message": "lease expired"}
    assert dict(receipt) == {"status": "UNKNOWN", "model_calls_made": 2}


def test_complete_source_is_segmented_without_truncation_or_oversize_single_call(
    tmp_path: Path,
) -> None:
    database, service, generator = service_at(tmp_path)
    content = "full-source-" * 1_000
    ready_document(
        database,
        document_id="full-doc",
        chunk_id="full-chunk",
        content=content,
    )
    service.reconcile(force=True)
    assert service.run_once("full-worker")["status"] == "READY"
    assert generator.evidence[0]["content"] == content
    assert generator.evidence[0]["truncated"] is False

    second_path = tmp_path / "segmented"
    settings2 = settings_at(second_path)
    database2 = Database(settings2)
    database2.initialize()
    private_workspace(database2)
    learning = RecordingLearning()
    service2 = AutoKnowledgeMapService(
        database2,
        settings2,
        learning=learning,  # type: ignore[arg-type]
    )
    ready_document(
        database2,
        document_id="oversize-doc",
        chunk_id="oversize-chunk",
        content="x" * 240_001,
    )
    service2.reconcile(force=True)
    completed = service2.run_once("segmented-worker")
    assert completed["status"] == "READY"
    assert len([item for item in learning.calls if item["schema"] == "AutoKnowledgeMapDraft"]) > 1
    assert all(item["context_size"] < 60_000 for item in learning.calls)
    with database2.connect() as connection:
        job = connection.execute("SELECT * FROM auto_knowledge_jobs").fetchone()
        course = connection.execute(
            "SELECT * FROM courses WHERE id=?", (job["course_id"],)
        ).fetchone()
        artifacts = connection.execute(
            "SELECT COUNT(*) FROM auto_knowledge_job_artifacts"
        ).fetchone()[0]
    assert job["model_calls_made"] == len(learning.calls)
    assert artifacts == len(learning.calls)

    # A process restart rehydrates every completed shard from its durable
    # artifact. It must not dispatch or reserve the same paid work again.
    calls_before_restart = len(learning.calls)
    restarted = AutoKnowledgeMapService(database2, settings2, learning)  # type: ignore[arg-type]
    _map, _specs, dispatched = restarted.generator.generate(
        job_id=str(job["id"]),
        workspace_id="workspace-a",
        course=dict(course),
        evidence=restarted._evidence(job),
    )
    assert dispatched == 0
    assert len(learning.calls) == calls_before_restart

def test_real_orchestrator_and_provider_complete_over_fake_http_upstream(
    tmp_path: Path,
) -> None:
    settings = settings_at(tmp_path).model_copy(
        update={
            "app_env": "development",
            "rag_provider_mode": "openai",
            "v3_model": "deepseek-flash",
            "v3_model_api_key": SecretStr("offline-contract-only"),
            "v3_model_base_url": "https://api.deepseek.com",
            # Course builds can legitimately need more shards than a learner's
            # interactive daily allowance. They remain metered, but use an
            # explicit background scope instead of consuming this quota.
            "v3_daily_model_calls_per_user": 1,
            "v3_daily_model_calls_per_user_course": 1,
        }
    )
    database = Database(settings)
    database.initialize()
    private_workspace(database)
    ready_document(
        database,
        document_id="http-doc",
        chunk_id="http-chunk",
        content="Grounded material. " * 5_000,
    )
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert str(request.url) == "https://api.deepseek.com/responses"
        assert body["reasoning"] == {"effort": "none"}
        assert body["store"] is False and body["tools"] == []
        assert body["max_output_tokens"] == 8_000
        serialized = str(body["input"])
        assert len(serialized) < 60_000
        context = json.loads(serialized)["authorized_context"]
        schema_name = str(body["text"]["format"]["name"])
        if schema_name == "AutoKnowledgeMapDraft":
            ids = [item["id"] for item in context["frozen_source_segments"]]
            output = {
                "title": "HTTP bounded shard",
                "modules": [
                    {
                        "key": "module",
                        "title": "HTTP module",
                        "description": "A grounded module",
                        "major": "OTHER",
                    }
                ],
                "nodes": [
                    {
                        "key": "core",
                        "parent_key": "module",
                        "title": "HTTP core",
                        "description": "A grounded atomic node",
                        "major": "OTHER",
                        "prerequisite_keys": [],
                        "evidence_ids": ids,
                    }
                ],
                "dispositions": [
                    {
                        "evidence_id": value,
                        "status": "MAPPED",
                        "reason": "Mapped by the bounded contract",
                        "node_keys": ["core"],
                    }
                    for value in ids
                ],
            }
        else:
            output = {
                "specs": [
                    {
                        "node_key": node["key"],
                        "change_reason": "Generated through fake HTTP",
                        "items": [
                            {
                                "item_id": "required_http",
                                "requirement": "REQUIRED",
                                "objective": "Explain the grounded HTTP concept",
                                "acceptance": "Explain and apply it",
                                "evidence_ids": node["evidence_ids"][:1],
                            }
                        ],
                    }
                    for node in context["knowledge_nodes"]
                ]
            }
        requests.append(body)
        return httpx.Response(200, json=response_payload(output, len(requests)))

    provider = LearningProvider(settings)
    transport_events: list[dict[str, Any]] = []
    provider.transport_event_sink = transport_events.append
    provider.client = OpenAI(
        api_key="offline-contract-only",
        base_url="https://api.deepseek.com",
        max_retries=0,
        timeout=60,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    learning = LearningOrchestrator(
        database,
        settings,
        HybridRetriever(ChunkRepository(database), FixedEmbeddingProvider()),
    )
    learning.provider = provider
    service = AutoKnowledgeMapService(database, settings, learning)

    assert service.reconcile(force=True)["QUEUED"] == 1
    result = service.run_once("fake-http-worker")

    assert result is not None and result["status"] == "READY"
    assert len(requests) >= 3  # segmented map shards plus one Teaching Spec batch
    assert [item["phase"] for item in transport_events] == [
        phase
        for _ in requests
        for phase in ("SEND_INTENT", "RESPONSE_COMPLETE", "CONTRACT_VALID")
    ]
    with database.connect() as connection:
        reservations = connection.execute(
            "SELECT status,quota_scope FROM learning_model_call_reservations ORDER BY rowid"
        ).fetchall()
        artifacts = connection.execute(
            "SELECT stage,input_hash,output_hash FROM auto_knowledge_job_artifacts "
            "ORDER BY stage,shard_key"
        ).fetchall()
        attempts = connection.execute(
            "SELECT status,output_hash,rejection_code FROM auto_knowledge_model_attempts "
            "ORDER BY created_at,operation_id"
        ).fetchall()
    assert len(reservations) == len(requests)
    assert all(
        (row["status"], row["quota_scope"]) == ("COMPLETED", "BACKGROUND_AUTO_MAP")
        for row in reservations
    )
    assert len(artifacts) == len(requests)
    assert all(len(row["input_hash"]) == len(row["output_hash"]) == 64 for row in artifacts)
    assert len(attempts) == len(requests)
    assert all(row["status"] == "ACCEPTED" for row in attempts)
    assert all(len(row["output_hash"]) == 64 for row in attempts)
    assert all(row["rejection_code"] is None for row in attempts)


def test_pre_dispatch_quota_failure_resumes_from_frozen_artifacts_with_audit(
    tmp_path: Path,
) -> None:
    settings = settings_at(tmp_path).model_copy(
        update={
            "auto_knowledge_map_enabled": True,
            "auto_knowledge_map_allow_billable": True,
        }
    )
    database = Database(settings)
    database.initialize()
    private_workspace(database)
    ready_document(
        database,
        document_id="quota-resume-doc",
        chunk_id="quota-resume-chunk",
        content="A quota stop before dispatch must reuse completed frozen work.",
    )
    learning = RecordingLearning()
    service = AutoKnowledgeMapService(database, settings, learning)  # type: ignore[arg-type]
    assert service.reconcile(force=True)["QUEUED"] == 1

    with database.connect() as connection:
        job = connection.execute("SELECT * FROM auto_knowledge_jobs").fetchone()
        operation = f"akm-{digest(str(job['id']))[:16]}-m-00000"
        connection.execute(
            "INSERT INTO learning_operations(workspace_id,id,request_hash,kind,status) "
            "VALUES('workspace-a',?,?,'auto.knowledge.map','UNKNOWN')",
            (operation, "f" * 64),
        )
        connection.execute(
            "UPDATE auto_knowledge_jobs SET status='FAILED',"
            "error_code='DAILY_MODEL_CALL_QUOTA',"
            "error_message='No provider call was made',completed_at=? WHERE id=?",
            ("2026-09-27T00:00:00.000Z", job["id"]),
        )
        connection.execute(
            "UPDATE auto_knowledge_targets SET status='FAILED' WHERE target_key=?",
            (job["target_key"],),
        )
        connection.execute(
            "INSERT INTO auto_knowledge_job_receipts("
            "job_id,target_key,corpus_fingerprint,status,source_snapshot_hash,"
            "model_calls_made,detail_json) VALUES(?,?,?,'FAILED',?,0,?)",
            (
                job["id"],
                job["target_key"],
                job["corpus_fingerprint"],
                digest(json.loads(job["source_snapshot_json"])),
                json.dumps({"error_code": "DAILY_MODEL_CALL_QUOTA"}),
            ),
        )

    reconciled = service.reconcile(force=True)
    assert reconciled["RECOVERED_SAFE_FAILURE"] == 1
    completed = service.run_once("quota-recovery-worker")
    assert completed is not None and completed["status"] == "READY"

    with database.connect() as connection:
        recovery = connection.execute(
            "SELECT reason,prior_receipt_json,blocked_operation_ids_json "
            "FROM auto_knowledge_job_recovery_receipts"
        ).fetchone()
        operations = connection.execute(
            "SELECT id,status FROM learning_operations ORDER BY id"
        ).fetchall()
        receipt = connection.execute(
            "SELECT status FROM auto_knowledge_job_receipts"
        ).fetchone()
    assert recovery["reason"] == "BACKGROUND_QUOTA_SCOPE_V1"
    assert json.loads(recovery["prior_receipt_json"])["status"] == "FAILED"
    assert json.loads(recovery["blocked_operation_ids_json"]) == [operation]
    assert (operation, "UNKNOWN") in {tuple(row) for row in operations}
    assert (f"{operation}-q1", "COMPLETED") in {tuple(row) for row in operations}
    assert receipt["status"] == "READY"


def test_legacy_job_level_repair_limit_resumes_only_known_rejected_shard(
    tmp_path: Path,
) -> None:
    settings = settings_at(tmp_path).model_copy(
        update={
            "auto_knowledge_map_enabled": True,
            "auto_knowledge_map_allow_billable": True,
        }
    )
    database = Database(settings)
    database.initialize()
    private_workspace(database)
    ready_document(
        database,
        document_id="repair-resume-doc",
        chunk_id="repair-resume-chunk",
        content="A known rejected shard can receive its own bounded repair.",
    )
    learning = RecordingLearning()
    service = AutoKnowledgeMapService(database, settings, learning)  # type: ignore[arg-type]
    assert service.reconcile(force=True)["QUEUED"] == 1

    output_text = "{}"
    output_hash = __import__("hashlib").sha256(output_text.encode()).hexdigest()
    with database.connect() as connection:
        job = connection.execute("SELECT * FROM auto_knowledge_jobs").fetchone()
        operation = f"akm-{digest(str(job['id']))[:16]}-m-00000"
        connection.execute(
            "INSERT INTO learning_operations(workspace_id,id,request_hash,kind,status) "
            "VALUES('workspace-a',?,?,'auto.knowledge.map','FAILED')",
            (operation, "e" * 64),
        )
        connection.execute(
            "INSERT INTO learning_model_call_reservations("
            "id,workspace_id,operation_id,owner_user_id,course_id,role,"
            "reserved_output_tokens,status,finished_at) "
            "VALUES('legacy-repair-reservation','workspace-a',?,'owner-a',"
            "'private-course','teacher',8000,'FAILED',?)",
            (operation, "2026-09-27T00:00:00.000Z"),
        )
        connection.execute(
            "INSERT INTO auto_knowledge_model_attempts("
            "operation_id,job_id,stage,shard_key,input_hash,status,"
            "output_text,output_hash,rejection_code,rejection_detail_json) "
            "VALUES(?,?,'SECTION_MAP','map-00000',?,'CONTRACT_REJECTED',?,?,?,?)",
            (
                operation,
                job["id"],
                "d" * 64,
                output_text,
                output_hash,
                "SCHEMA_INVALID",
                json.dumps({"code": "SCHEMA_INVALID"}),
            ),
        )
        connection.execute(
            "UPDATE auto_knowledge_jobs SET status='FAILED',model_calls_made=1,"
            "repair_calls_made=2,error_code='AUTO_REPAIR_LIMIT',"
            "error_message='Legacy job-level repair limit',completed_at=? WHERE id=?",
            ("2026-09-27T00:00:00.000Z", job["id"]),
        )
        connection.execute(
            "UPDATE auto_knowledge_targets SET status='FAILED' WHERE target_key=?",
            (job["target_key"],),
        )
        connection.execute(
            "INSERT INTO auto_knowledge_job_receipts("
            "job_id,target_key,corpus_fingerprint,status,source_snapshot_hash,"
            "model_calls_made,detail_json) VALUES(?,?,?,'FAILED',?,1,?)",
            (
                job["id"],
                job["target_key"],
                job["corpus_fingerprint"],
                digest(json.loads(job["source_snapshot_json"])),
                json.dumps({"error_code": "AUTO_REPAIR_LIMIT"}),
            ),
        )

    assert service.reconcile(force=True)["RECOVERED_SAFE_FAILURE"] == 1
    completed = service.run_once("repair-scope-recovery-worker")
    assert completed is not None and completed["status"] == "READY"

    with database.connect() as connection:
        recovery = connection.execute(
            "SELECT reason,blocked_operation_ids_json "
            "FROM auto_knowledge_job_recovery_receipts"
        ).fetchone()
        repairs = connection.execute(
            "SELECT stage,shard_key,ordinal,operation_id "
            "FROM auto_knowledge_repair_reservations"
        ).fetchall()
    assert recovery["reason"] == "PER_SHARD_REPAIR_SCOPE_V1"
    assert json.loads(recovery["blocked_operation_ids_json"]) == [operation]
    assert [tuple(row) for row in repairs] == [
        ("SECTION_MAP", "map-00000", 1, f"{operation}-r1")
    ]


def test_required_item_rejection_gets_one_audited_third_repair(
    tmp_path: Path,
) -> None:
    """A repeated, exact REQUIRED-item schema defect gets one final prompt repair.

    The normal per-shard budget remains two.  This recovery is deliberately
    narrower: all three rejected attempts are complete responses for the same
    Teaching Spec shard, the latest one is ``-r2``, and every rejection records
    the exact missing-REQUIRED-item validation issue observed in production.
    """

    settings = settings_at(tmp_path).model_copy(
        update={
            "auto_knowledge_map_enabled": True,
            "auto_knowledge_map_allow_billable": True,
        }
    )
    database = Database(settings)
    database.initialize()
    private_workspace(database)
    ready_document(
        database,
        document_id="required-repair-doc",
        chunk_id="required-repair-chunk",
        content="A grounded Teaching Spec still needs an explicit REQUIRED item.",
    )
    learning = RecordingLearning()
    service = AutoKnowledgeMapService(
        database, settings, learning  # type: ignore[arg-type]
    )
    assert service.reconcile(force=True)["QUEUED"] == 1

    issue = {
        "code": "SCHEMA_INVALID",
        "issues": [
            {
                "message": "Value error, Every atomic node needs at least one REQUIRED item",
                "path": "specs.5",
                "type": "value_error",
            }
        ],
    }
    with database.connect() as connection:
        job = connection.execute("SELECT * FROM auto_knowledge_jobs").fetchone()
        base = f"akm-{digest(str(job['id']))[:16]}-s-00007"
        for ordinal, suffix in enumerate(("", "-r1", "-r2")):
            operation = f"{base}{suffix}"
            connection.execute(
                "INSERT INTO auto_knowledge_model_attempts("
                "operation_id,job_id,stage,shard_key,input_hash,status,"
                "output_text,output_hash,rejection_code,rejection_detail_json) "
                "VALUES(?,?,'TEACHING_SPEC','spec-00007',?,'CONTRACT_REJECTED',"
                "'{}',?,'ValidationError',?)",
                (
                    operation,
                    job["id"],
                    str(ordinal) * 64,
                    hashlib.sha256(b"{}").hexdigest(),
                    json.dumps(issue),
                ),
            )
            if ordinal:
                connection.execute(
                    "INSERT INTO auto_knowledge_repair_reservations("
                    "job_id,stage,shard_key,ordinal,operation_id) VALUES(?,?,?,?,?)",
                    (job["id"], "TEACHING_SPEC", "spec-00007", ordinal, operation),
                )
        connection.execute(
            "UPDATE auto_knowledge_jobs SET status='FAILED',model_calls_made=3,"
            "repair_calls_made=2,error_code='AUTO_REPAIR_LIMIT',"
            "error_message='The two targeted repairs for this automatic-map shard "
            "were exhausted.',completed_at=? WHERE id=?",
            ("2026-09-27T07:10:28.902Z", job["id"]),
        )
        connection.execute(
            "UPDATE auto_knowledge_targets SET status='FAILED' WHERE active_job_id=?",
            (job["id"],),
        )
        connection.execute(
            "INSERT INTO auto_knowledge_job_receipts("
            "job_id,target_key,corpus_fingerprint,status,source_snapshot_hash,"
            "model_calls_made,detail_json) VALUES(?,?,?,'FAILED',?,3,?)",
            (
                job["id"],
                job["target_key"],
                job["corpus_fingerprint"],
                digest(json.loads(job["source_snapshot_json"])),
                json.dumps({"error_code": "AUTO_REPAIR_LIMIT"}),
            ),
        )

    assert service.reconcile(force=True)["RECOVERED_SAFE_FAILURE"] == 1
    with database.connect() as connection:
        recovery = connection.execute(
            "SELECT reason,blocked_operation_ids_json "
            "FROM auto_knowledge_job_recovery_receipts WHERE job_id=?",
            (job["id"],),
        ).fetchone()
    assert recovery["reason"] == "REQUIRED_ITEM_REPAIR_V1"
    assert json.loads(recovery["blocked_operation_ids_json"])[-1] == f"{base}-r2"

    # A short-lived production build changed the common base Prompt before it
    # reached r3. Accepted artifacts correctly rejected that replay by hash,
    # and an older generic artifact-rehydration reason was consumed without a
    # provider request. Preserve both receipts, then grant one local-only replay
    # after the historical base Prompt has been restored.
    drift_receipt = {
        "job_id": job["id"],
        "target_key": job["target_key"],
        "corpus_fingerprint": job["corpus_fingerprint"],
        "status": "FAILED",
        "source_snapshot_hash": digest(json.loads(job["source_snapshot_json"])),
        "model_calls_made": 3,
        "detail": {"error_code": "AUTO_ARTIFACT_CONFLICT"},
        "created_at": "2026-09-27T08:12:26.247Z",
    }
    drift_json = json.dumps(drift_receipt, sort_keys=True, separators=(",", ":"))
    with database.connect() as connection:
        # Preserve one accepted paid repair plus its rejected predecessor, as
        # the production hash-conflict guard requires. This is a different
        # shard from the exact missing-REQUIRED r2 authorization below.
        accepted_base = f"akm-{digest(str(job['id']))[:16]}-s-00001"
        rejected_output = "{}"
        accepted_output = json.dumps({"specs": []}, separators=(",", ":"))
        connection.execute(
            "INSERT INTO auto_knowledge_model_attempts("
            "operation_id,job_id,stage,shard_key,input_hash,status,"
            "output_text,output_hash,rejection_code,rejection_detail_json) "
            "VALUES(?,?,'TEACHING_SPEC','spec-00001',?,'CONTRACT_REJECTED',"
            "?,?, 'ValidationError','{}')",
            (
                accepted_base,
                job["id"],
                "a" * 64,
                rejected_output,
                hashlib.sha256(rejected_output.encode()).hexdigest(),
            ),
        )
        connection.execute(
            "INSERT INTO auto_knowledge_model_attempts("
            "operation_id,job_id,stage,shard_key,input_hash,status,"
            "output_text,output_hash,rejection_detail_json) "
            "VALUES(?,?,'TEACHING_SPEC','spec-00001',?,'ACCEPTED',?,?, '{}')",
            (
                f"{accepted_base}-r1",
                job["id"],
                "b" * 64,
                accepted_output,
                hashlib.sha256(accepted_output.encode()).hexdigest(),
            ),
        )
        connection.execute(
            "INSERT INTO auto_knowledge_repair_reservations("
            "job_id,stage,shard_key,ordinal,operation_id) VALUES(?,?,?,?,?)",
            (job["id"], "TEACHING_SPEC", "spec-00001", 1, f"{accepted_base}-r1"),
        )
        connection.execute(
            "INSERT INTO auto_knowledge_job_artifacts("
            "job_id,stage,shard_key,input_hash,model_operation_id,"
            "output_json,output_hash) VALUES(?, 'TEACHING_SPEC','spec-00001',?,?,?,?)",
            (
                job["id"],
                "b" * 64,
                f"{accepted_base}-r1",
                accepted_output,
                hashlib.sha256(accepted_output.encode()).hexdigest(),
            ),
        )
        connection.execute(
            "INSERT INTO auto_knowledge_job_recovery_receipts("
            "id,job_id,reason,prior_receipt_json,prior_receipt_hash,"
            "blocked_operation_ids_json) VALUES(?,?,?,?,?,'[]')",
            (
                "prior-artifact-rehydration",
                job["id"],
                "REPAIRED_ARTIFACT_REHYDRATION_V1",
                drift_json,
                hashlib.sha256(drift_json.encode()).hexdigest(),
            ),
        )
        connection.execute(
            "UPDATE auto_knowledge_jobs SET status='FAILED',"
            "error_code='AUTO_ARTIFACT_CONFLICT',error_message=?,completed_at=? "
            "WHERE id=?",
            (
                "A persisted generation shard no longer matches its frozen input.",
                "2026-09-27T08:12:26.247Z",
                job["id"],
            ),
        )
        connection.execute(
            "UPDATE auto_knowledge_targets SET status='FAILED' WHERE active_job_id=?",
            (job["id"],),
        )
        connection.execute(
            "INSERT INTO auto_knowledge_job_receipts("
            "job_id,target_key,corpus_fingerprint,status,source_snapshot_hash,"
            "model_calls_made,detail_json) VALUES(?,?,?,'FAILED',?,3,?)",
            (
                job["id"],
                job["target_key"],
                job["corpus_fingerprint"],
                digest(json.loads(job["source_snapshot_json"])),
                json.dumps({"error_code": "AUTO_ARTIFACT_CONFLICT"}),
            ),
        )

    assert service.reconcile(force=True)["RECOVERED_SAFE_FAILURE"] == 1
    with database.connect() as connection:
        reasons = {
            row[0]
            for row in connection.execute(
                "SELECT reason FROM auto_knowledge_job_recovery_receipts WHERE job_id=?",
                (job["id"],),
            )
        }
        connection.execute(
            "UPDATE auto_knowledge_jobs SET status='RUNNING' WHERE id=?", (job["id"],)
        )
    assert "BASE_PROMPT_HASH_RESTORE_V1" in reasons
    output, dispatched = service.generator._run_with_repairs(  # type: ignore[attr-defined]
        job_id=str(job["id"]),
        stage="TEACHING_SPEC",
        shard_key="spec-00007",
        operation_base=base,
        workspace_id="workspace-a",
        schema=AutoKnowledgeSpecSetDraft,
        instructions="Historical Teaching Spec prompt that must remain byte-stable.",
        context={"knowledge_nodes": [{"key": "core", "evidence_ids": ["e1"]}]},
        validate=lambda _value: None,
    )
    assert dispatched is True
    assert output.specs[0].items[0].requirement == "REQUIRED"
    assert '"requirement": "REQUIRED"' in learning.calls[-1]["instructions"]

    with database.connect() as connection:
        repairs = connection.execute(
            "SELECT ordinal,operation_id FROM auto_knowledge_repair_reservations "
            "WHERE job_id=? AND stage='TEACHING_SPEC' AND shard_key='spec-00007' "
            "ORDER BY ordinal",
            (job["id"],),
        ).fetchall()
    assert [tuple(row) for row in repairs] == [
        (1, f"{base}-r1"),
        (2, f"{base}-r2"),
        (3, f"{base}-r3"),
    ]

    # The job-level recovery receipt must not expand a different Teaching Spec
    # shard from two repairs to three.
    other_base = f"akm-{digest(str(job['id']))[:16]}-s-00008"
    with database.connect() as connection:
        for ordinal in (1, 2):
            connection.execute(
                "INSERT INTO auto_knowledge_repair_reservations("
                "job_id,stage,shard_key,ordinal,operation_id) VALUES(?,?,?,?,?)",
                (
                    job["id"],
                    "TEACHING_SPEC",
                    "spec-00008",
                    ordinal,
                    f"{other_base}-r{ordinal}",
                ),
            )
    with pytest.raises(ApiError) as denied:
        service.generator._reserve_repair(  # type: ignore[attr-defined]
            str(job["id"]), "TEACHING_SPEC", "spec-00008", other_base
        )
    assert denied.value.code == "AUTO_REPAIR_LIMIT"


def test_duplicate_map_keys_get_one_exact_audited_third_repair(tmp_path: Path) -> None:
    """Only the exact repeated SECTION_MAP key defect may reserve r3."""

    settings = settings_at(tmp_path).model_copy(
        update={
            "auto_knowledge_map_enabled": True,
            "auto_knowledge_map_allow_billable": True,
        }
    )
    database = Database(settings)
    database.initialize()
    private_workspace(database)
    ready_document(
        database,
        document_id="duplicate-key-doc",
        chunk_id="duplicate-key-chunk",
        content="A complete section map must use unique stable keys.",
    )
    learning = RecordingLearning()
    service = AutoKnowledgeMapService(
        database, settings, learning  # type: ignore[arg-type]
    )
    assert service.reconcile(force=True)["QUEUED"] == 1

    issue = {
        "code": "SCHEMA_INVALID",
        "issues": [
            {
                "message": "Value error, Automatic knowledge-map keys must be unique",
                "path": "",
                "type": "value_error",
            }
        ],
    }
    with database.connect() as connection:
        job = connection.execute("SELECT * FROM auto_knowledge_jobs").fetchone()
        base = f"akm-{digest(str(job['id']))[:16]}-m-00052"
        for ordinal, suffix in enumerate(("", "-r1", "-r2")):
            operation = f"{base}{suffix}"
            connection.execute(
                "INSERT INTO auto_knowledge_model_attempts("
                "operation_id,job_id,stage,shard_key,input_hash,status,"
                "output_text,output_hash,rejection_code,rejection_detail_json) "
                "VALUES(?,?,'SECTION_MAP','map-00052',?,'CONTRACT_REJECTED',"
                "'{}',?,'ValidationError',?)",
                (
                    operation,
                    job["id"],
                    str(ordinal) * 64,
                    hashlib.sha256(b"{}").hexdigest(),
                    json.dumps(issue),
                ),
            )
            if ordinal:
                connection.execute(
                    "INSERT INTO auto_knowledge_repair_reservations("
                    "job_id,stage,shard_key,ordinal,operation_id) VALUES(?,?,?,?,?)",
                    (job["id"], "SECTION_MAP", "map-00052", ordinal, operation),
                )
        connection.execute(
            "UPDATE auto_knowledge_jobs SET status='FAILED',model_calls_made=3,"
            "repair_calls_made=2,error_code='AUTO_REPAIR_LIMIT',"
            "error_message='The 2 targeted repairs for this automatic-map shard "
            "were exhausted.',completed_at=? WHERE id=?",
            ("2026-09-27T08:18:40.125Z", job["id"]),
        )
        connection.execute(
            "UPDATE auto_knowledge_targets SET status='FAILED' WHERE active_job_id=?",
            (job["id"],),
        )
        connection.execute(
            "INSERT INTO auto_knowledge_job_receipts("
            "job_id,target_key,corpus_fingerprint,status,source_snapshot_hash,"
            "model_calls_made,detail_json) VALUES(?,?,?,'FAILED',?,3,?)",
            (
                job["id"],
                job["target_key"],
                job["corpus_fingerprint"],
                digest(json.loads(job["source_snapshot_json"])),
                json.dumps({"error_code": "AUTO_REPAIR_LIMIT"}),
            ),
        )

    assert service.reconcile(force=True)["RECOVERED_SAFE_FAILURE"] == 1
    with database.connect() as connection:
        recovery = connection.execute(
            "SELECT reason,blocked_operation_ids_json "
            "FROM auto_knowledge_job_recovery_receipts WHERE job_id=?",
            (job["id"],),
        ).fetchone()
        connection.execute(
            "UPDATE auto_knowledge_jobs SET status='RUNNING' WHERE id=?", (job["id"],)
        )
    assert recovery["reason"] == "UNIQUE_KEY_REPAIR_V1"
    assert json.loads(recovery["blocked_operation_ids_json"])[-1] == f"{base}-r2"

    output, dispatched = service.generator._run_with_repairs(  # type: ignore[attr-defined]
        job_id=str(job["id"]),
        stage="SECTION_MAP",
        shard_key="map-00052",
        operation_base=base,
        workspace_id="workspace-a",
        schema=AutoKnowledgeMapDraft,
        instructions="Build a grounded map for this frozen section shard.",
        context={
            "frozen_source_segments": [
                {
                    "id": "segment-1",
                    "content": "Unique keys are required.",
                }
            ]
        },
        validate=lambda _value: None,
    )
    assert dispatched is True
    assert output.nodes[0].key == "core"
    assert "unique" in learning.calls[-1]["instructions"].lower()
    assert "parent_key" in learning.calls[-1]["instructions"]

    with database.connect() as connection:
        repairs = connection.execute(
            "SELECT ordinal,operation_id FROM auto_knowledge_repair_reservations "
            "WHERE job_id=? AND stage='SECTION_MAP' AND shard_key='map-00052' "
            "ORDER BY ordinal",
            (job["id"],),
        ).fetchall()
    assert [tuple(row) for row in repairs] == [
        (1, f"{base}-r1"),
        (2, f"{base}-r2"),
        (3, f"{base}-r3"),
    ]

    other_base = f"akm-{digest(str(job['id']))[:16]}-m-00053"
    with database.connect() as connection:
        for ordinal in (1, 2):
            connection.execute(
                "INSERT INTO auto_knowledge_repair_reservations("
                "job_id,stage,shard_key,ordinal,operation_id) VALUES(?,?,?,?,?)",
                (
                    job["id"],
                    "SECTION_MAP",
                    "map-00053",
                    ordinal,
                    f"{other_base}-r{ordinal}",
                ),
            )
    with pytest.raises(ApiError) as denied:
        service.generator._reserve_repair(  # type: ignore[attr-defined]
            str(job["id"]), "SECTION_MAP", "map-00053", other_base
        )
    assert denied.value.code == "AUTO_REPAIR_LIMIT"


def test_teaching_spec_evidence_scope_gets_one_exact_audited_third_repair(
    tmp_path: Path,
) -> None:
    """Only a complete, repeated atomic-evidence failure may reserve r3.

    The ordinary repair ceiling remains two.  This mirrors the production
    GE1401 failure: the same Teaching Spec shard has three durable complete
    responses, each was rejected by the authoritative aggregate validator
    because an item cited evidence from another atomic node, and no r3 send or
    reservation exists yet.
    """

    settings = settings_at(tmp_path).model_copy(
        update={
            "auto_knowledge_map_enabled": True,
            "auto_knowledge_map_allow_billable": True,
        }
    )
    database = Database(settings)
    database.initialize()
    private_workspace(database)
    ready_document(
        database,
        document_id="evidence-scope-repair-doc",
        chunk_id="evidence-scope-repair-chunk",
        content="Each Teaching Spec must cite only its own atomic-node evidence.",
    )
    learning = RecordingLearning()
    service = AutoKnowledgeMapService(
        database, settings, learning  # type: ignore[arg-type]
    )
    assert service.reconcile(force=True)["QUEUED"] == 1

    issue = {
        "code": "AUTO_EVIDENCE_INVALID",
        "details": {},
        "message": "A Teaching Spec cited evidence outside its atomic node.",
    }
    with database.connect() as connection:
        job = connection.execute("SELECT * FROM auto_knowledge_jobs").fetchone()
        base = f"akm-{digest(str(job['id']))[:16]}-s-00060"
        for ordinal, suffix in enumerate(("", "-r1", "-r2")):
            operation = f"{base}{suffix}"
            output = json.dumps({"specs": []}, separators=(",", ":"))
            connection.execute(
                "INSERT INTO auto_knowledge_model_attempts("
                "operation_id,job_id,stage,shard_key,input_hash,status,"
                "output_text,output_hash,rejection_code,rejection_detail_json) "
                "VALUES(?,?,'TEACHING_SPEC','spec-00060',?,'BUSINESS_REJECTED',"
                "?,?, 'AUTO_EVIDENCE_INVALID',?)",
                (
                    operation,
                    job["id"],
                    str(ordinal) * 64,
                    output,
                    hashlib.sha256(output.encode()).hexdigest(),
                    json.dumps(issue),
                ),
            )
            if ordinal:
                connection.execute(
                    "INSERT INTO auto_knowledge_repair_reservations("
                    "job_id,stage,shard_key,ordinal,operation_id) VALUES(?,?,?,?,?)",
                    (job["id"], "TEACHING_SPEC", "spec-00060", ordinal, operation),
                )
        connection.execute(
            "UPDATE auto_knowledge_jobs SET status='FAILED',model_calls_made=3,"
            "repair_calls_made=2,error_code='AUTO_REPAIR_LIMIT',"
            "error_message='The 2 targeted repairs for this automatic-map shard "
            "were exhausted.',completed_at=? WHERE id=?",
            ("2026-09-27T10:19:30.433Z", job["id"]),
        )
        connection.execute(
            "UPDATE auto_knowledge_targets SET status='FAILED' WHERE active_job_id=?",
            (job["id"],),
        )
        connection.execute(
            "INSERT INTO auto_knowledge_job_receipts("
            "job_id,target_key,corpus_fingerprint,status,source_snapshot_hash,"
            "model_calls_made,detail_json) VALUES(?,?,?,'FAILED',?,3,?)",
            (
                job["id"],
                job["target_key"],
                job["corpus_fingerprint"],
                digest(json.loads(job["source_snapshot_json"])),
                json.dumps({"error_code": "AUTO_REPAIR_LIMIT"}),
            ),
        )

    assert service.reconcile(force=True)["RECOVERED_SAFE_FAILURE"] == 1
    with database.connect() as connection:
        recovery = connection.execute(
            "SELECT reason,blocked_operation_ids_json "
            "FROM auto_knowledge_job_recovery_receipts WHERE job_id=?",
            (job["id"],),
        ).fetchone()
        connection.execute(
            "UPDATE auto_knowledge_jobs SET status='RUNNING' WHERE id=?", (job["id"],)
        )
    assert recovery["reason"] == "EVIDENCE_SCOPE_REPAIR_V1"
    assert json.loads(recovery["blocked_operation_ids_json"])[-1] == f"{base}-r2"

    output, dispatched = service.generator._run_with_repairs(  # type: ignore[attr-defined]
        job_id=str(job["id"]),
        stage="TEACHING_SPEC",
        shard_key="spec-00060",
        operation_base=base,
        workspace_id="workspace-a",
        schema=AutoKnowledgeSpecSetDraft,
        instructions="Build a grounded Teaching Spec for this frozen node batch.",
        context={"knowledge_nodes": [{"key": "core", "evidence_ids": ["e1"]}]},
        validate=lambda _value: None,
    )
    assert dispatched is True
    assert output.specs[0].items[0].evidence_ids == ["e1"]
    assert "atomic node" in learning.calls[-1]["instructions"]

    with database.connect() as connection:
        repairs = connection.execute(
            "SELECT ordinal,operation_id FROM auto_knowledge_repair_reservations "
            "WHERE job_id=? AND stage='TEACHING_SPEC' AND shard_key='spec-00060' "
            "ORDER BY ordinal",
            (job["id"],),
        ).fetchall()
    assert [tuple(row) for row in repairs] == [
        (1, f"{base}-r1"),
        (2, f"{base}-r2"),
        (3, f"{base}-r3"),
    ]

    other_base = f"akm-{digest(str(job['id']))[:16]}-s-00061"
    with database.connect() as connection:
        for ordinal in (1, 2):
            connection.execute(
                "INSERT INTO auto_knowledge_repair_reservations("
                "job_id,stage,shard_key,ordinal,operation_id) VALUES(?,?,?,?,?)",
                (
                    job["id"],
                    "TEACHING_SPEC",
                    "spec-00061",
                    ordinal,
                    f"{other_base}-r{ordinal}",
                ),
            )
    with pytest.raises(ApiError) as denied:
        service.generator._reserve_repair(  # type: ignore[attr-defined]
            str(job["id"]), "TEACHING_SPEC", "spec-00061", other_base
        )
    assert denied.value.code == "AUTO_REPAIR_LIMIT"


def test_evidence_scope_r3_normalizes_only_foreign_citations_without_a_model_call(
    tmp_path: Path,
) -> None:
    """An exhausted exact r3 may remove only surplus foreign evidence locally.

    The original provider response stays BUSINESS_REJECTED.  This is a narrow
    recovery for a complete, saved r3 response where every affected item still
    has at least one citation from its own atomic node; it must never reserve
    r4 or send another request.
    """

    settings = settings_at(tmp_path).model_copy(
        update={
            "auto_knowledge_map_enabled": True,
            "auto_knowledge_map_allow_billable": True,
        }
    )
    database = Database(settings)
    database.initialize()
    private_workspace(database)
    ready_document(
        database,
        document_id="evidence-normalization-doc",
        chunk_id="e1",
        content="The local recovery must preserve each node's own evidence.",
    )
    learning = RecordingLearning()
    service = AutoKnowledgeMapService(
        database,
        settings,
        learning,  # type: ignore[arg-type]
    )
    assert service.reconcile(force=True)["QUEUED"] == 1

    issue = {
        "code": "AUTO_EVIDENCE_INVALID",
        "details": {},
        "message": "A Teaching Spec cited evidence outside its atomic node.",
    }
    r2_issue = {
        "code": "AUTO_EVIDENCE_INVALID",
        "details": {"attempt": "r2"},
        "message": "A Teaching Spec cited evidence outside its atomic node.",
    }
    instructions = "Build a grounded Teaching Spec for this frozen node batch."
    context = {
        "knowledge_nodes": [
            {"key": "core-a", "evidence_ids": ["e1"]},
            {"key": "core-b", "evidence_ids": ["e2"]},
        ]
    }
    rejected_payload = {
        "specs": [
            {
                "node_key": "core-a",
                "change_reason": "First frozen node",
                "items": [
                    {
                        "item_id": "a-required",
                        "requirement": "REQUIRED",
                        "objective": "Explain the first node",
                        "acceptance": "Use its primary source",
                        "evidence_ids": ["e1", "e2"],
                    }
                ],
            },
            {
                "node_key": "core-b",
                "change_reason": "Second frozen node",
                "items": [
                    {
                        "item_id": "b-required",
                        "requirement": "REQUIRED",
                        "objective": "Explain the second node",
                        "acceptance": "Use its primary source",
                        "evidence_ids": ["e2"],
                    }
                ],
            },
        ]
    }
    rejected_json = canonical_json(rejected_payload)
    with database.connect() as connection:
        job = connection.execute("SELECT * FROM auto_knowledge_jobs").fetchone()
        base = f"akm-{digest(str(job['id']))[:16]}-s-00060"
        r3 = f"{base}-r3"
        for ordinal, suffix in enumerate(("", "-r1", "-r2", "-r3")):
            operation = f"{base}{suffix}"
            connection.execute(
                "INSERT INTO auto_knowledge_model_attempts("
                "operation_id,job_id,stage,shard_key,input_hash,status,output_text,"
                "output_hash,rejection_code,rejection_detail_json) "
                "VALUES(?,?,'TEACHING_SPEC','spec-00060',?,'BUSINESS_REJECTED',"
                "?,?, 'AUTO_EVIDENCE_INVALID',?)",
                (
                    operation,
                    job["id"],
                    str(ordinal) * 64,
                    rejected_json,
                    hashlib.sha256(rejected_json.encode()).hexdigest(),
                    canonical_json(r2_issue if ordinal == 2 else issue),
                ),
            )
            if ordinal:
                connection.execute(
                    "INSERT INTO auto_knowledge_repair_reservations("
                    "job_id,stage,shard_key,ordinal,operation_id) VALUES(?,?,?,?,?)",
                    (job["id"], "TEACHING_SPEC", "spec-00060", ordinal, operation),
                )
        original_receipt = {"error_code": "AUTO_REPAIR_LIMIT"}
        connection.execute(
            "UPDATE auto_knowledge_jobs SET status='FAILED',model_calls_made=4,"
            "repair_calls_made=2,error_code='AUTO_REPAIR_LIMIT',"
            "error_message='The 3 targeted repairs for this automatic-map shard were exhausted.',"
            "completed_at=? WHERE id=?",
            ("2026-09-27T12:45:00.000Z", job["id"]),
        )
        connection.execute(
            "UPDATE auto_knowledge_targets SET status='FAILED' WHERE active_job_id=?",
            (job["id"],),
        )
        connection.execute(
            "INSERT INTO auto_knowledge_job_receipts("
            "job_id,target_key,corpus_fingerprint,status,source_snapshot_hash,"
            "model_calls_made,detail_json) VALUES(?,?,?,'FAILED',?,4,?)",
            (
                job["id"],
                job["target_key"],
                job["corpus_fingerprint"],
                digest(json.loads(job["source_snapshot_json"])),
                canonical_json(original_receipt),
            ),
        )
        prior_json = canonical_json(
            {
                "job_id": job["id"],
                "status": "FAILED",
                "detail": original_receipt,
            }
        )
        connection.execute(
            "INSERT INTO auto_knowledge_job_recovery_receipts("
            "id,job_id,reason,prior_receipt_json,prior_receipt_hash,"
            "blocked_operation_ids_json) VALUES(?,?,?,?,?,?)",
            (
                "evidence-scope-r3-authorized",
                job["id"],
                "EVIDENCE_SCOPE_REPAIR_V1",
                prior_json,
                hashlib.sha256(prior_json.encode()).hexdigest(),
                canonical_json([base, f"{base}-r1", f"{base}-r2"]),
            ),
        )
        effective_instructions = (
            instructions + "\nThe previous complete response was rejected. Correct these exact "
            "issues and return a shorter valid response without repeating invalid "
            "content: "
            + canonical_json(r2_issue)
            + "\nFinal atomic-evidence repair: for every specs[i].items[*] "
            "entry, cite only evidence IDs from the matching node_key's "
            "knowledge_nodes[i].evidence_ids. Never cite a neighbouring "
            "node or any other source; recheck every item before returning."
        )
        request_hash = digest(
            {
                "builder": BUILDER_VERSION,
                "operation": r3,
                "schema": "AutoKnowledgeSpecSetDraft",
                "instructions": effective_instructions,
                "context": context,
                "max_output_tokens": AUTO_MODEL_MAX_OUTPUT_TOKENS,
            }
        )
        connection.execute(
            "INSERT INTO learning_operations(workspace_id,id,request_hash,kind,status) "
            "VALUES('workspace-a',?,?,'auto.knowledge.map','FAILED')",
            (r3, request_hash),
        )

    assert service.reconcile(force=True)["RECOVERED_SAFE_FAILURE"] == 1
    with database.connect() as connection:
        recovery = connection.execute(
            "SELECT reason,blocked_operation_ids_json FROM auto_knowledge_job_recovery_receipts "
            "WHERE job_id=? ORDER BY created_at,reason",
            (job["id"],),
        ).fetchall()
    assert {row["reason"] for row in recovery} == {
        "EVIDENCE_SCOPE_NORMALIZATION_V1",
        "EVIDENCE_SCOPE_REPAIR_V1",
    }
    normalization = next(
        row for row in recovery if row["reason"] == "EVIDENCE_SCOPE_NORMALIZATION_V1"
    )
    assert json.loads(normalization["blocked_operation_ids_json"])[-1] == r3

    # V52 chose r3's rejection feedback when reconstructing the immutable r3
    # request.  Model work was never dispatched and no artifact was written,
    # so this exact terminal state gets one separately recorded retry.
    conflict_receipt = {"error_code": "AUTO_ARTIFACT_CONFLICT"}
    with database.connect() as connection:
        connection.execute(
            "UPDATE auto_knowledge_jobs SET status='FAILED',"
            "error_code='AUTO_ARTIFACT_CONFLICT',"
            "error_message='The local evidence normalization no longer matches its "
            "immutable recovery evidence.',completed_at=? WHERE id=?",
            ("2026-09-27T12:46:00.000Z", job["id"]),
        )
        connection.execute(
            "UPDATE auto_knowledge_targets SET status='FAILED' WHERE active_job_id=?",
            (job["id"],),
        )
        connection.execute(
            "INSERT INTO auto_knowledge_job_receipts("
            "job_id,target_key,corpus_fingerprint,status,source_snapshot_hash,"
            "model_calls_made,detail_json) VALUES(?,?,?,'FAILED',?,4,?)",
            (
                job["id"],
                job["target_key"],
                job["corpus_fingerprint"],
                digest(json.loads(job["source_snapshot_json"])),
                canonical_json(conflict_receipt),
            ),
        )
    assert service.reconcile(force=True)["RECOVERED_SAFE_FAILURE"] == 1
    with database.connect() as connection:
        recovery = connection.execute(
            "SELECT reason FROM auto_knowledge_job_recovery_receipts "
            "WHERE job_id=? ORDER BY created_at,reason",
            (job["id"],),
        ).fetchall()
        connection.execute(
            "UPDATE auto_knowledge_jobs SET status='RUNNING' WHERE id=?", (job["id"],)
        )
    assert {row["reason"] for row in recovery} == {
        "EVIDENCE_SCOPE_NORMALIZATION_RETRY_V1",
        "EVIDENCE_SCOPE_NORMALIZATION_V1",
        "EVIDENCE_SCOPE_REPAIR_V1",
    }

    def validate_specs(value: Any) -> None:
        for spec in value.specs:
            allowed = {"core-a": {"e1"}, "core-b": {"e2"}}[spec.node_key]
            for item in spec.items:
                assert set(item.evidence_ids) <= allowed
                assert item.evidence_ids

    output, dispatched = service.generator._run_with_repairs(  # type: ignore[attr-defined]
        job_id=str(job["id"]),
        stage="TEACHING_SPEC",
        shard_key="spec-00060",
        operation_base=base,
        workspace_id="workspace-a",
        schema=AutoKnowledgeSpecSetDraft,
        instructions=instructions,
        context=context,
        validate=validate_specs,
        normalize_local_recovery=lambda value: service.generator._normalize_atomic_evidence(  # type: ignore[attr-defined]
            value, {"core-a": {"e1"}, "core-b": {"e2"}}
        ),
    )
    assert dispatched is False
    assert learning.calls == []
    assert output.specs[0].items[0].evidence_ids == ["e1"]

    with database.connect() as connection:
        raw_attempt = connection.execute(
            "SELECT status,output_hash FROM auto_knowledge_model_attempts WHERE operation_id=?",
            (r3,),
        ).fetchone()
        artifact = connection.execute(
            "SELECT model_operation_id,output_json FROM auto_knowledge_job_artifacts "
            "WHERE job_id=? AND stage='TEACHING_SPEC' AND shard_key='spec-00060'",
            (job["id"],),
        ).fetchone()
        repairs = connection.execute(
            "SELECT ordinal FROM auto_knowledge_repair_reservations WHERE job_id=? "
            "AND stage='TEACHING_SPEC' AND shard_key='spec-00060' ORDER BY ordinal",
            (job["id"],),
        ).fetchall()
    assert tuple(raw_attempt) == (
        "BUSINESS_REJECTED",
        hashlib.sha256(rejected_json.encode()).hexdigest(),
    )
    assert artifact["model_operation_id"] == r3
    assert json.loads(artifact["output_json"])["specs"][0]["items"][0]["evidence_ids"] == ["e1"]
    assert [row["ordinal"] for row in repairs] == [1, 2, 3]

    # A second frozen Teaching-Spec shard in the same course must receive its
    # own one-shot evidence-scope repair; the first shard's receipt must not
    # consume the authorization for all later shards.
    second_base = f"akm-{digest(str(job['id']))[:16]}-s-00061"
    with database.connect() as connection:
        for ordinal, suffix in enumerate(("", "-r1", "-r2")):
            operation = f"{second_base}{suffix}"
            connection.execute(
                "INSERT INTO auto_knowledge_model_attempts("
                "operation_id,job_id,stage,shard_key,input_hash,status,output_text,"
                "output_hash,rejection_code,rejection_detail_json) "
                "VALUES(?,?,'TEACHING_SPEC','spec-00061',?,'BUSINESS_REJECTED',"
                "?,?, 'AUTO_EVIDENCE_INVALID',?)",
                (
                    operation,
                    job["id"],
                    f"second-{ordinal}".ljust(64, "0"),
                    rejected_json,
                    hashlib.sha256(rejected_json.encode()).hexdigest(),
                    canonical_json(issue),
                ),
            )
            if ordinal:
                connection.execute(
                    "INSERT INTO auto_knowledge_repair_reservations("
                    "job_id,stage,shard_key,ordinal,operation_id) VALUES(?,?,?,?,?)",
                    (job["id"], "TEACHING_SPEC", "spec-00061", ordinal, operation),
                )
        connection.execute(
            "UPDATE auto_knowledge_jobs SET status='FAILED',"
            "error_code='AUTO_REPAIR_LIMIT',"
            "error_message='The 2 targeted repairs for this automatic-map shard "
            "were exhausted.',completed_at=? WHERE id=?",
            ("2026-09-27T12:45:30.000Z", job["id"]),
        )
        connection.execute(
            "UPDATE auto_knowledge_targets SET status='FAILED' WHERE active_job_id=?",
            (job["id"],),
        )
        connection.execute(
            "INSERT INTO auto_knowledge_job_receipts("
            "job_id,target_key,corpus_fingerprint,status,source_snapshot_hash,"
            "model_calls_made,detail_json) VALUES(?,?,?,'FAILED',?,4,?)",
            (
                job["id"],
                job["target_key"],
                job["corpus_fingerprint"],
                digest(json.loads(job["source_snapshot_json"])),
                canonical_json(original_receipt),
            ),
        )
    assert service.reconcile(force=True)["RECOVERED_SAFE_FAILURE"] == 1
    with database.connect() as connection:
        scope_receipts = connection.execute(
            "SELECT blocked_operation_ids_json FROM auto_knowledge_job_recovery_receipts "
            "WHERE job_id=? AND reason='EVIDENCE_SCOPE_REPAIR_V1' "
            "ORDER BY blocked_operation_ids_json",
            (job["id"],),
        ).fetchall()
    assert {
        tuple(json.loads(row["blocked_operation_ids_json"])) for row in scope_receipts
    } == {
        (base, f"{base}-r1", f"{base}-r2"),
        (second_base, f"{second_base}-r1", f"{second_base}-r2"),
    }


def test_safe_validation_failure_uses_one_targeted_repair_and_reuses_stage_contract(
    tmp_path: Path,
) -> None:
    settings = settings_at(tmp_path).model_copy(
        update={
            "auto_knowledge_map_enabled": True,
            "auto_knowledge_map_allow_billable": True,
        }
    )
    database = Database(settings)
    database.initialize()
    private_workspace(database)
    ready_document(
        database,
        document_id="repair-doc",
        chunk_id="repair-chunk",
        content="A bounded response must account for this source.",
    )
    learning = RepairingLearning()
    service = AutoKnowledgeMapService(
        database,
        settings,
        learning=learning,  # type: ignore[arg-type]
    )
    service.reconcile(force=True)

    result = service.run_once("repair-worker")

    assert result is not None and result["status"] == "READY"
    assert len(learning.calls) == 3
    with database.connect() as connection:
        job = connection.execute(
            "SELECT * FROM auto_knowledge_jobs"
        ).fetchone()
        course = connection.execute(
            "SELECT * FROM courses WHERE id=?", (job["course_id"],)
        ).fetchone()
        operations = connection.execute(
            "SELECT status FROM learning_operations ORDER BY created_at,rowid"
        ).fetchall()
        artifacts = connection.execute(
            "SELECT COUNT(*) FROM auto_knowledge_job_artifacts"
        ).fetchone()[0]
    assert job["repair_calls_made"] == 1
    assert [row["status"] for row in operations] == ["FAILED", "COMPLETED", "COMPLETED"]
    assert artifacts == 2
    assert learning.calls[0]["max_output_tokens"] == 8_000
    assert "previous complete response" in learning.calls[1]["instructions"].lower()
    assert "AUTO_SOURCE_COVERAGE_INCOMPLETE" in learning.calls[1]["instructions"]

    # A repaired shard is still a completed durable artifact. Reopening the
    # same frozen job must reconstruct the exact repaired request identity and
    # reuse it without another provider dispatch or an artifact-hash conflict.
    calls_before_restart = len(learning.calls)
    restarted = AutoKnowledgeMapService(database, settings, learning)  # type: ignore[arg-type]
    _map, _specs, dispatched = restarted.generator.generate(
        job_id=str(job["id"]),
        workspace_id="workspace-a",
        course=dict(course),
        evidence=restarted._evidence(job),
    )
    assert dispatched == 0
    assert len(learning.calls) == calls_before_restart

    # Production exposed this exact historical failure before the repaired
    # artifact rehydration fix was deployed. It is recoverable only when the
    # accepted repaired artifact and its rejected predecessor are both durable.
    with database.connect() as connection:
        connection.execute(
            "UPDATE auto_knowledge_jobs SET status='FAILED',"
            "error_code='AUTO_ARTIFACT_CONFLICT',error_message=?,completed_at=? "
            "WHERE id=?",
            (
                "A persisted generation shard no longer matches its frozen input.",
                "2026-09-27T00:00:00.000Z",
                job["id"],
            ),
        )
        connection.execute(
            "UPDATE auto_knowledge_targets SET status='FAILED' WHERE active_job_id=?",
            (job["id"],),
        )
        connection.execute(
            "UPDATE auto_knowledge_job_receipts SET status='FAILED' WHERE job_id=?",
            (job["id"],),
        )
    assert restarted.reconcile(force=True)["RECOVERED_SAFE_FAILURE"] == 1
    with database.connect() as connection:
        recovered = connection.execute(
            "SELECT status,error_code FROM auto_knowledge_jobs WHERE id=?", (job["id"],)
        ).fetchone()
        reason = connection.execute(
            "SELECT reason FROM auto_knowledge_job_recovery_receipts WHERE job_id=?",
            (job["id"],),
        ).fetchone()[0]
    assert dict(recovered) == {"status": "QUEUED", "error_code": None}
    assert reason == "REPAIRED_ARTIFACT_REHYDRATION_V1"


def test_legacy_rejection_feedback_allows_one_second_exact_recovery(
    tmp_path: Path,
) -> None:
    """A historical empty rejection detail can be repaired once after V45.

    Production can already contain the first immutable rehydration receipt:
    that recovery exposed that older CONTRACT_REJECTED attempts did not retain
    their normalized validation feedback.  The reconstructed feedback fix is a
    distinct, bounded recovery and must never make the job generally retryable.
    """

    settings = settings_at(tmp_path).model_copy(
        update={
            "auto_knowledge_map_enabled": True,
            "auto_knowledge_map_allow_billable": True,
        }
    )
    database = Database(settings)
    database.initialize()
    private_workspace(database)
    ready_document(
        database,
        document_id="legacy-feedback-doc",
        chunk_id="legacy-feedback-chunk",
        content="Legacy validation feedback must be reconstructed deterministically.",
    )
    learning = RepairingLearning()
    service = AutoKnowledgeMapService(database, settings, learning)  # type: ignore[arg-type]
    service.reconcile(force=True)
    completed = service.run_once("legacy-feedback-worker")
    assert completed is not None and completed["status"] == "READY"

    with database.connect() as connection:
        job = connection.execute("SELECT * FROM auto_knowledge_jobs").fetchone()
        rejected = connection.execute(
            "SELECT operation_id FROM auto_knowledge_model_attempts "
            "WHERE job_id=? AND status='BUSINESS_REJECTED'",
            (job["id"],),
        ).fetchone()
        connection.execute(
            "UPDATE auto_knowledge_model_attempts SET status='CONTRACT_REJECTED',"
            "output_text='{}',output_hash=?,rejection_code='ValidationError',"
            "rejection_detail_json='{}' WHERE operation_id=?",
            (hashlib.sha256(b"{}").hexdigest(), rejected["operation_id"]),
        )
        prior_receipt = {
            "job_id": job["id"],
            "target_key": job["target_key"],
            "corpus_fingerprint": job["corpus_fingerprint"],
            "status": "FAILED",
            "source_snapshot_hash": digest(json.loads(job["source_snapshot_json"])),
        }
        prior_json = json.dumps(prior_receipt, sort_keys=True, separators=(",", ":"))
        connection.execute(
            "INSERT INTO auto_knowledge_job_recovery_receipts("
            "id,job_id,reason,prior_receipt_json,prior_receipt_hash,"
            "blocked_operation_ids_json) VALUES(?,?,?,?,?,'[]')",
            (
                "prior-repaired-artifact-recovery",
                job["id"],
                "REPAIRED_ARTIFACT_REHYDRATION_V1",
                prior_json,
                hashlib.sha256(prior_json.encode()).hexdigest(),
            ),
        )
        connection.execute(
            "UPDATE auto_knowledge_jobs SET status='FAILED',"
            "error_code='AUTO_ARTIFACT_CONFLICT',error_message=?,completed_at=? "
            "WHERE id=?",
            (
                "A persisted generation shard no longer matches its frozen input.",
                "2026-09-27T00:00:00.000Z",
                job["id"],
            ),
        )
        connection.execute(
            "UPDATE auto_knowledge_targets SET status='FAILED' WHERE active_job_id=?",
            (job["id"],),
        )
        connection.execute(
            "UPDATE auto_knowledge_job_receipts SET status='FAILED',detail_json=? "
            "WHERE job_id=?",
            (json.dumps({"error_code": "AUTO_ARTIFACT_CONFLICT"}), job["id"]),
        )

    assert service.reconcile(force=True)["RECOVERED_SAFE_FAILURE"] == 1
    with database.connect() as connection:
        reasons = {
            row[0]
            for row in connection.execute(
                "SELECT reason FROM auto_knowledge_job_recovery_receipts WHERE job_id=?",
                (job["id"],),
            ).fetchall()
        }
    assert reasons == {
        "REPAIRED_ARTIFACT_REHYDRATION_V1",
        "LEGACY_REJECTION_FEEDBACK_REHYDRATION_V1",
    }

    # The new recovery reason is immutable and one-shot. A repeat of the same
    # terminal state remains visible instead of silently reopening again.
    with database.connect() as connection:
        connection.execute(
            "UPDATE auto_knowledge_jobs SET status='FAILED',"
            "error_code='AUTO_ARTIFACT_CONFLICT',error_message=?,completed_at=? "
            "WHERE id=?",
            (
                "A persisted generation shard no longer matches its frozen input.",
                "2026-09-27T00:01:00.000Z",
                job["id"],
            ),
        )
        connection.execute(
            "UPDATE auto_knowledge_targets SET status='FAILED' WHERE active_job_id=?",
            (job["id"],),
        )
        connection.execute(
            "INSERT INTO auto_knowledge_job_receipts("
            "job_id,target_key,corpus_fingerprint,status,source_snapshot_hash,"
            "model_calls_made,detail_json) VALUES(?,?,?,'FAILED',?,0,?)",
            (
                job["id"],
                job["target_key"],
                job["corpus_fingerprint"],
                digest(json.loads(job["source_snapshot_json"])),
                json.dumps({"error_code": "AUTO_ARTIFACT_CONFLICT"}),
            ),
        )
    assert service.reconcile(force=True).get("RECOVERED_SAFE_FAILURE", 0) == 0


def test_targeted_repair_budget_is_bounded_per_shard_not_per_course(
    tmp_path: Path,
) -> None:
    settings = settings_at(tmp_path)
    database = Database(settings)
    database.initialize()
    private_workspace(database)
    ready_document(
        database,
        document_id="many-shards-doc",
        chunk_id="many-shards-chunk",
        content="grounded concept " * 3_000,
    )
    learning = MultiShardRepairingLearning()
    service = AutoKnowledgeMapService(database, settings, learning)  # type: ignore[arg-type]
    service.reconcile(force=True)

    result = service.run_once("many-shards-repair-worker")

    assert result is not None and result["status"] == "READY"
    assert len(learning.rejected_operations) == 3
    with database.connect() as connection:
        repairs = connection.execute(
            "SELECT stage,shard_key,ordinal FROM auto_knowledge_repair_reservations "
            "ORDER BY stage,shard_key,ordinal"
        ).fetchall()
    assert len(repairs) == 3
    assert all(row["ordinal"] == 1 for row in repairs)


def test_live_incomplete_response_is_saved_then_repaired_with_larger_bound(
    tmp_path: Path,
) -> None:
    settings = settings_at(tmp_path).model_copy(
        update={
            "app_env": "development",
            "rag_provider_mode": "openai",
            "v3_model": "deepseek-flash",
            "v3_model_api_key": SecretStr("offline-contract-only"),
            "v3_model_base_url": "https://api.deepseek.com",
            "v3_daily_model_calls_per_user": 30,
            "v3_daily_model_calls_per_user_course": 30,
        }
    )
    database = Database(settings)
    database.initialize()
    private_workspace(database)
    ready_document(
        database,
        document_id="incomplete-doc",
        chunk_id="incomplete-chunk",
        content="One bounded concept for the incomplete-response regression.",
    )
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        context = json.loads(str(body["input"]))["authorized_context"]
        schema_name = str(body["text"]["format"]["name"])
        if schema_name == "AutoKnowledgeMapDraft":
            ids = [item["id"] for item in context["frozen_source_segments"]]
            output = {
                "title": "Recovered map",
                "modules": [
                    {
                        "key": "module",
                        "title": "Recovered module",
                        "description": "Grounded module",
                        "major": "OTHER",
                    }
                ],
                "nodes": [
                    {
                        "key": "node",
                        "parent_key": "module",
                        "title": "Recovered node",
                        "description": "Grounded node",
                        "major": "OTHER",
                        "prerequisite_keys": [],
                        "evidence_ids": ids,
                    }
                ],
                "dispositions": [
                    {
                        "evidence_id": value,
                        "status": "MAPPED",
                        "reason": "Grounded",
                        "node_keys": ["node"],
                    }
                    for value in ids
                ],
            }
        else:
            output = {
                "specs": [
                    {
                        "node_key": context["knowledge_nodes"][0]["key"],
                        "change_reason": "Recovered after a bounded response",
                        "items": [
                            {
                                "item_id": "required",
                                "requirement": "REQUIRED",
                                "objective": "Explain the recovered concept",
                                "acceptance": "Explain it correctly",
                                "evidence_ids": context["knowledge_nodes"][0][
                                    "evidence_ids"
                                ][:1],
                            }
                        ],
                    }
                ]
            }
        payload = response_payload(output, len(requests))
        if len(requests) == 1:
            payload["status"] = "incomplete"
            payload["incomplete_details"] = {"reason": "max_output_tokens"}
        return httpx.Response(200, json=payload)

    provider = LearningProvider(settings)
    provider.client = OpenAI(
        api_key="offline-contract-only",
        base_url="https://api.deepseek.com",
        max_retries=0,
        timeout=60,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    learning = LearningOrchestrator(
        database,
        settings,
        HybridRetriever(ChunkRepository(database), FixedEmbeddingProvider()),
    )
    learning.provider = provider
    service = AutoKnowledgeMapService(database, settings, learning)

    service.reconcile(force=True)
    result = service.run_once("incomplete-http-worker")

    assert result is not None and result["status"] == "READY"
    assert len(requests) == 3
    assert all(request["max_output_tokens"] == 8_000 for request in requests)
    assert "MODEL_INCOMPLETE" in requests[1]["instructions"]
    with database.connect() as connection:
        attempts = connection.execute(
            "SELECT status,rejection_code,rejection_detail_json,output_hash "
            "FROM auto_knowledge_model_attempts ORDER BY created_at,operation_id"
        ).fetchall()
        job = connection.execute("SELECT * FROM auto_knowledge_jobs").fetchone()
        course = connection.execute(
            "SELECT * FROM courses WHERE id=?", (job["course_id"],)
        ).fetchone()
    assert [row["status"] for row in attempts] == [
        "CONTRACT_REJECTED",
        "ACCEPTED",
        "ACCEPTED",
    ]
    assert attempts[0]["rejection_code"] == "MODEL_INCOMPLETE"
    assert json.loads(attempts[0]["rejection_detail_json"])["code"] == "MODEL_INCOMPLETE"
    assert all(len(row["output_hash"]) == 64 for row in attempts)

    requests_before_restart = len(requests)
    restarted = AutoKnowledgeMapService(database, settings, learning)
    _map, _specs, dispatched = restarted.generator.generate(
        job_id=str(job["id"]),
        workspace_id="workspace-a",
        course=dict(course),
        evidence=restarted._evidence(job),
    )
    assert dispatched == 0
    assert len(requests) == requests_before_restart


def test_legacy_schema_rejection_feedback_is_reconstructed_from_saved_output() -> None:
    feedback = OrchestratorDraftGenerator._durable_rejection_feedback(
        {
            "rejection_code": "ValidationError",
            "rejection_detail_json": "{}",
            "output_text": "{}",
        },  # type: ignore[arg-type]
        AutoKnowledgeMapDraft,
    )

    assert feedback["code"] == "SCHEMA_INVALID"
    assert feedback["issues"]


def test_merge_prunes_empty_model_groupings_without_dropping_grounded_nodes() -> None:
    draft = AutoKnowledgeMapDraft.model_validate(
        {
            "title": "Shard",
            "modules": [
                {
                    "key": "used",
                    "title": "Used module",
                    "description": "Contains a grounded node",
                    "major": "OTHER",
                },
                {
                    "key": "empty",
                    "title": "Empty model grouping",
                    "description": "No atomic child",
                    "major": "OTHER",
                },
            ],
            "nodes": [
                {
                    "key": "atomic",
                    "parent_key": "used",
                    "title": "Grounded atom",
                    "description": "Grounded in the source",
                    "major": "OTHER",
                    "prerequisite_keys": [],
                    "evidence_ids": ["seg_one"],
                }
            ],
            "dispositions": [
                {
                    "evidence_id": "seg_one",
                    "status": "MAPPED",
                    "reason": "Mapped",
                    "node_keys": ["atomic"],
                },
                {
                    "evidence_id": "seg_two",
                    "status": "MAPPED",
                    "reason": "Provider claimed a mapping without citing the segment",
                    "node_keys": ["atomic"],
                },
            ],
        }
    )

    merged = OrchestratorDraftGenerator._merge_maps(
        {
            "name": "Course",
        },
        [(draft, {"seg_one": "chunk_one", "seg_two": "chunk_two"})],
    )

    assert [module.title for module in merged.modules] == ["Used module"]
    assert len(merged.nodes) == 1
    assert merged.nodes[0].evidence_ids == ["chunk_one"]
    dispositions = {item.evidence_id: item for item in merged.dispositions}
    assert dispositions["chunk_one"].status == "MAPPED"
    assert dispositions["chunk_two"].status == "REVIEW_REQUIRED"
    assert dispositions["chunk_two"].node_keys == []


def test_final_mapped_disposition_failure_gets_one_audited_local_recovery(
    tmp_path: Path,
) -> None:
    settings = settings_at(tmp_path).model_copy(
        update={
            "auto_knowledge_map_enabled": True,
            "auto_knowledge_map_allow_billable": True,
        }
    )
    database = Database(settings)
    database.initialize()
    private_workspace(database)
    ready_document(
        database,
        document_id="final-disposition-doc",
        chunk_id="final-disposition-chunk",
        content="One grounded concept for deterministic final validation.",
    )
    learning = RecordingLearning()
    service = AutoKnowledgeMapService(database, settings, learning)  # type: ignore[arg-type]
    service.reconcile(force=True)
    completed = service.run_once("final-disposition-worker")
    assert completed is not None and completed["status"] == "READY"
    calls_before_recovery = len(learning.calls)

    with database.connect() as connection:
        job = connection.execute("SELECT * FROM auto_knowledge_jobs").fetchone()
        connection.execute(
            "UPDATE auto_knowledge_jobs SET status='FAILED',"
            "error_code='AUTO_SOURCE_COVERAGE_INCOMPLETE',error_message=?,completed_at=? "
            "WHERE id=?",
            (
                "A mapped source disposition must be cited by an atomic node.",
                "2026-09-27T00:00:00.000Z",
                job["id"],
            ),
        )
        connection.execute(
            "UPDATE auto_knowledge_targets SET status='FAILED' WHERE active_job_id=?",
            (job["id"],),
        )
        connection.execute(
            "UPDATE auto_knowledge_job_receipts SET status='FAILED' WHERE job_id=?",
            (job["id"],),
        )

    assert service.reconcile(force=True)["RECOVERED_SAFE_FAILURE"] == 1
    assert service.reconcile(force=True).get("RECOVERED_SAFE_FAILURE", 0) == 0
    with database.connect() as connection:
        recovered = connection.execute(
            "SELECT status,error_code FROM auto_knowledge_jobs WHERE id=?", (job["id"],)
        ).fetchone()
        reason = connection.execute(
            "SELECT reason FROM auto_knowledge_job_recovery_receipts WHERE job_id=?",
            (job["id"],),
        ).fetchone()[0]
    assert dict(recovered) == {"status": "QUEUED", "error_code": None}
    assert reason == "FINAL_DISPOSITION_NORMALIZATION_V1"
    assert len(learning.calls) == calls_before_recovery


def test_provider_output_cannot_silently_drop_a_frozen_source_segment(tmp_path: Path) -> None:
    database, service, generator = service_at(tmp_path)
    ready_document(
        database,
        document_id="coverage-one",
        chunk_id="coverage-chunk-one",
        content="First distinct concept.",
    )
    ready_document(
        database,
        document_id="coverage-two",
        chunk_id="coverage-chunk-two",
        content="Second distinct concept that must also be represented.",
    )
    original_generate = generator.generate

    def incomplete_generate(**kwargs):
        map_draft, spec_draft, calls = original_generate(**kwargs)
        map_draft.nodes[0].evidence_ids = ["coverage-chunk-one"]
        spec_draft.specs[0].items[0].evidence_ids = ["coverage-chunk-one"]
        return map_draft, spec_draft, calls

    generator.generate = incomplete_generate  # type: ignore[method-assign]
    service.reconcile(force=True)

    result = service.run_once("coverage-worker")

    assert result == {
        "job_id": result["job_id"],
        "status": "FAILED",
        "error": "AUTO_SOURCE_COVERAGE_INCOMPLETE",
    }
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM knowledge_tree_versions").fetchone()[0] == 0
        receipt = connection.execute(
            "SELECT status,model_calls_made,detail_json FROM auto_knowledge_job_receipts"
        ).fetchone()
    assert receipt["status"] == "FAILED"
    assert receipt["model_calls_made"] == 2
    assert json.loads(receipt["detail_json"])["error_code"] == (
        "AUTO_SOURCE_COVERAGE_INCOMPLETE"
    )


def test_machine_validated_campus_tree_is_resolved_without_becoming_official(
    tmp_path: Path,
) -> None:
    settings = settings_at(tmp_path)
    database = Database(settings)
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO courses(id,name,course_type,visibility,publication_status) "
            "VALUES('campus-course','Campus course','official','public','draft')"
        )
        connection.execute(
            "INSERT INTO courses(id,name,owner_user_id,course_type,visibility,publication_status) "
            "VALUES('campus-private','Private corpus','admin','user','private','private')"
        )
        connection.execute(
            "INSERT INTO learning_workspaces(id,owner_user_id,course_id,private_course_id) "
            "VALUES('workspace-campus','admin','campus-course','campus-private')"
        )
    ready_document(
        database,
        document_id="campus-doc",
        chunk_id="campus-chunk",
        content="A campus source with a teachable concept.",
        course_id="campus-course",
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE courses SET publication_status='published' WHERE id='campus-course'"
        )
    generator = FakeGenerator()
    service = AutoKnowledgeMapService(
        database,
        settings,
        learning=object(),  # type: ignore[arg-type]
        generator=generator,
    )

    service.reconcile(force=True)
    result = service.run_once("campus-worker")

    assert result is not None and result["status"] == "READY"
    state = KnowledgeService(database).snapshot("workspace-campus", "admin")
    build_status = service.status("campus-course", "admin")
    assert state["selected_tree"] == "AUTO_COURSE"
    assert build_status["status"] == "READY"
    assert build_status["machine_generated"] is True
    assert build_status["human_reviewed"] is False
    assert state["auto_course_tree"]["machine_generated"] is True
    assert state["auto_course_tree"]["label"] == "AI整理 · 未经人工审核"
    atomic = next(node for node in state["registry"] if node["kind"] == "ATOMIC")
    assert atomic["source"] == "AUTO_COURSE"
    with database.connect() as connection:
        workspace = connection.execute(
            "SELECT * FROM learning_workspaces WHERE id='workspace-campus'"
        ).fetchone()
        tree = connection.execute(
            "SELECT tree.status,node.status AS node_status,metadata.status AS spec_status "
            "FROM auto_course_tree_activations AS activation "
            "JOIN knowledge_tree_versions AS tree ON tree.id=activation.tree_version_id "
            "JOIN knowledge_tree_memberships AS membership "
            "ON membership.tree_version_id=tree.id "
            "JOIN knowledge_nodes AS node ON node.id=membership.node_id "
            "LEFT JOIN teaching_spec_metadata AS metadata ON metadata.node_id=node.id "
            "AND metadata.version=membership.teaching_spec_version "
            "WHERE node.kind='ATOMIC'"
        ).fetchone()
        assessable = AssessmentService._atomic_node(connection, workspace, atomic["id"])
    orchestrator = object.__new__(LearningOrchestrator)
    orchestrator.db = database
    resolved = orchestrator.node(workspace, atomic["id"])

    assert tree["status"] == "DRAFT"
    assert tree["node_status"] == "CANDIDATE"
    assert tree["spec_status"] == "DRAFT"
    assert resolved["spec_version"] == assessable["spec_version"] == 1

    ready_document(
        database,
        document_id="private-supplement",
        chunk_id="private-supplement-chunk",
        content="A learner-only supplement that must remain private.",
        course_id="campus-private",
    )
    service.reconcile(force=True)
    supplement = service.run_once("supplement-worker")
    assert supplement is not None and supplement["status"] == "READY"

    supplemented = KnowledgeService(database).snapshot("workspace-campus", "admin")
    assert supplemented["selected_tree"] == "PERSONALIZED"
    assert supplemented["personalized_tree"]["machine_generated"] is True
    assert {member["source"] for member in supplemented["personalized_tree"]["members"]} == {
        "AUTO_COURSE",
        "PRIVATE",
    }
