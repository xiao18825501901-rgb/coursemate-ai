import hashlib
import json
import sqlite3
from collections.abc import Callable
from typing import Any, Literal, TypeVar, cast
from uuid import uuid4

from pydantic import BaseModel

from app.config import Settings
from app.db import Database
from app.errors import ApiError
from app.learning.assessments import AssessmentService
from app.learning.compiler import (
    TEMPLATE_VERSION,
    assessment_template,
    compile_unit,
    problem_template,
    template,
    validate_plan,
    validate_unit,
)
from app.learning.course_policy import course_policy
from app.learning.knowledge import KnowledgeService
from app.learning.models import (
    AssessmentAbandonInput,
    AssessmentAssistInput,
    AssessmentGradeProposal,
    AssessmentStartInput,
    AssessmentSubmitInput,
    BridgeInput,
    GradePolicyDraftInput,
    NodeDraft,
    OperationInput,
    PersonalPlanInput,
    PreferenceInput,
    ProblemSolutionOutput,
    ReturnInput,
    SolveInput,
    TeachingItem,
    TeachingPlan,
    TeachingSpecDraft,
    TeachingUnitOutput,
    TeachInput,
)
from app.learning.plans import TeachingPlanRepository
from app.learning.problems import ProblemIndexScope, ProblemRepository
from app.learning.provider import LearningProvider, ProviderCallFailure, ProviderImage
from app.learning.workspaces import document_version_for, original_path, workspace_for
from app.rag.retrieval import HybridRetriever
from app.repositories.chunks import RetrievalAccess


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def identifier() -> str:
    return uuid4().hex


Output = TypeVar("Output", bound=BaseModel)


class LearningOrchestrator:
    def __init__(self, database: Database, settings: Settings, retriever: HybridRetriever) -> None:
        self.db = database
        self.settings = settings
        self.retriever = retriever
        self.provider = LearningProvider(settings)
        self.knowledge = KnowledgeService(database)
        self.plans = TeachingPlanRepository(database)
        self.problems = ProblemRepository(database)
        self.assessments = AssessmentService(database)

    def problem_index(
        self,
        workspace_id: str,
        owner: str,
        *,
        scope: ProblemIndexScope,
        query: str | None,
        document_version_id: str | None,
        filename: str | None,
        question_number: str | None,
        question_part: str | None,
        locator_type: str | None,
        locator_value: str | None,
        limit: int,
    ) -> dict[str, Any]:
        return self.problems.list_index(
            workspace_id,
            owner,
            scope=scope,
            query=query,
            document_version_id=document_version_id,
            filename=filename,
            question_number=question_number,
            question_part=question_part,
            locator_type=locator_type,
            locator_value=locator_value,
            limit=limit,
        )

    def node(self, workspace: sqlite3.Row, node_id: str) -> dict[str, Any]:
        with self.db.connect() as db:
            row = db.execute(
                "SELECT * FROM knowledge_nodes WHERE id=? AND course_id=? "
                "AND ((owner_user_id=? AND status='PRIVATE') OR status='PUBLISHED')",
                (node_id, workspace["course_id"], workspace["owner_user_id"]),
            ).fetchone()
            spec = (
                db.execute(
                    "SELECT teaching_specs.* FROM teaching_specs "
                    "JOIN teaching_spec_metadata AS metadata "
                    "ON metadata.node_id=teaching_specs.node_id "
                    "AND metadata.version=teaching_specs.version "
                    "WHERE teaching_specs.node_id=? "
                    "AND metadata.status IN ('PRIVATE_ACTIVE','PUBLISHED') "
                    "ORDER BY teaching_specs.version DESC LIMIT 1",
                    (node_id,),
                ).fetchone()
                if row is not None and row["kind"] == "ATOMIC"
                else None
            )
        if row is None:
            raise ApiError(404, "NODE_NOT_FOUND", "The knowledge node was not found.")
        if row["kind"] == "ATOMIC" and spec is None:
            raise ApiError(
                409,
                "SPEC_NOT_AVAILABLE",
                "The atomic knowledge node has no active Teaching Spec.",
            )
        return {
            "id": row["id"],
            "course_id": row["course_id"],
            "title": row["title"],
            "description": row["description"],
            "major": row["major"],
            "kind": row["kind"],
            "status": row["status"],
            "created_at": row["created_at"],
            "spec_version": spec["version"] if spec is not None else None,
            "spec_hash": spec["content_hash"] if spec is not None else None,
            "items": json.loads(spec["content_json"]) if spec is not None else [],
        }

    def create_node(self, workspace_id: str, owner: str, draft: NodeDraft) -> dict[str, Any]:
        workspace = workspace_for(self.db, workspace_id, owner)
        evidence_ids = {e for item in draft.items for e in item.evidence_ids}
        self.check_evidence(workspace, evidence_ids)
        node_id = identifier()
        content = encode([item.model_dump() for item in draft.items])
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                db.execute(
                    "SELECT COUNT(*) FROM knowledge_nodes WHERE course_id=? AND owner_user_id=?",
                    (workspace["course_id"], owner),
                ).fetchone()[0]
                >= 200
            ):
                raise ApiError(429, "NODE_QUOTA", "Private node quota reached.")
            db.execute(
                "INSERT INTO "
                "knowledge_nodes(id,course_id,owner_user_id,title,description,major,kind,status)"
                " VALUES(?,?,?,?,?,?,?,'PRIVATE')",
                (
                    node_id,
                    workspace["course_id"],
                    owner,
                    draft.title,
                    draft.description,
                    draft.major,
                    draft.kind,
                ),
            )
            if draft.kind == "ATOMIC":
                db.execute(
                    "INSERT INTO teaching_specs VALUES(?,1,?,?)",
                    (node_id, content, hashlib.sha256(content.encode()).hexdigest()),
                )
            db.execute(
                "UPDATE learning_workspaces SET revision=revision+1 WHERE id=?", (workspace_id,)
            )
        return self.node(workspace, node_id)

    def knowledge_state(self, workspace_id: str, owner: str) -> dict[str, Any]:
        return self.knowledge.snapshot(workspace_id, owner)

    def start_assessment(
        self,
        workspace_id: str,
        owner: str,
        request: AssessmentStartInput,
    ) -> dict[str, Any]:
        def save(
            db: sqlite3.Connection,
            workspace: sqlite3.Row,
            _: Any,
        ) -> dict[str, Any]:
            result = self.assessments.start(db, workspace, request.node_id)
            self.cursor(
                db,
                workspace_id,
                node_id=request.node_id,
                assessment_session_id=result["id"],
                pane="ASSESSMENT",
            )
            return result

        return self.operate(
            workspace_id,
            owner,
            request,
            "assessment.start",
            lambda workspace: None,
            save,
            resource_identity={"node_id": request.node_id},
        )

    def assessment(
        self,
        workspace_id: str,
        owner: str,
        session_id: str,
    ) -> dict[str, Any]:
        return self.assessments.view(workspace_id, owner, session_id)

    def submit_assessment(
        self,
        workspace_id: str,
        owner: str,
        session_id: str,
        request: AssessmentSubmitInput,
    ) -> dict[str, Any]:
        def prepare(workspace: sqlite3.Row) -> AssessmentGradeProposal | None:
            prepared = self.assessments.prepare_submission(
                workspace,
                session_id,
                request.answers,
            )
            grader_context = self.assessments.grader_context(prepared)
            if grader_context is None:
                return None
            instructions, template_version = assessment_template()
            proposal, _run = self.generate(
                workspace_id,
                request.operation_id,
                AssessmentGradeProposal,
                instructions=instructions,
                context=grader_context,
                role="grader",
                template_version=template_version,
                schema_version="v3.2",
            )
            return proposal

        def save(
            db: sqlite3.Connection,
            workspace: sqlite3.Row,
            proposal: AssessmentGradeProposal | None,
        ) -> dict[str, Any]:
            result = self.assessments.save_submission(
                db,
                workspace,
                session_id,
                request.answers,
                proposal,
            )
            self.cursor(
                db,
                workspace_id,
                node_id=result["node_id"],
                assessment_session_id=session_id,
                pane="ASSESSMENT",
            )
            return result

        return self.operate(
            workspace_id,
            owner,
            request,
            "assessment.submit",
            prepare,
            save,
            resource_identity={"assessment_session_id": session_id},
        )

    def assist_assessment(
        self,
        workspace_id: str,
        owner: str,
        session_id: str,
        request: AssessmentAssistInput,
    ) -> dict[str, Any]:
        def save(
            db: sqlite3.Connection,
            workspace: sqlite3.Row,
            _: Any,
        ) -> dict[str, Any]:
            return self.assessments.assist(
                db,
                workspace,
                session_id,
                request.blueprint_item_id,
                request.action,
            )

        return self.operate(
            workspace_id,
            owner,
            request,
            "assessment.assist",
            lambda workspace: None,
            save,
            resource_identity={"assessment_session_id": session_id},
        )

    def abandon_assessment(
        self,
        workspace_id: str,
        owner: str,
        session_id: str,
        request: AssessmentAbandonInput,
    ) -> dict[str, Any]:
        def save(
            db: sqlite3.Connection,
            workspace: sqlite3.Row,
            _: Any,
        ) -> dict[str, Any]:
            return self.assessments.abandon(db, workspace, session_id)

        return self.operate(
            workspace_id,
            owner,
            request,
            "assessment.abandon",
            lambda workspace: None,
            save,
            resource_identity={"assessment_session_id": session_id},
        )

    def create_grade_policy(
        self,
        owner: str,
        request: GradePolicyDraftInput,
    ) -> dict[str, Any]:
        return self.assessments.create_grade_policy(owner, request)

    def publish_grade_policy(self, owner: str, policy_id: str) -> dict[str, Any]:
        return self.assessments.publish_grade_policy(owner, policy_id)

    def personal_plan(
        self, workspace_id: str, owner: str, request: PersonalPlanInput
    ) -> dict[str, Any]:
        def save(
            db: sqlite3.Connection, workspace: sqlite3.Row, _: Any
        ) -> dict[str, Any]:
            return self.knowledge.create_personal_plan(db, workspace, request)

        return self.operate(
            workspace_id,
            owner,
            request,
            "personal.plan",
            lambda workspace: None,
            save,
        )

    def create_spec(
        self,
        workspace_id: str,
        owner: str,
        node_id: str,
        request: TeachingSpecDraft,
    ) -> dict[str, Any]:
        content = encode([item.model_dump() for item in request.items])
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        def prepare(workspace: sqlite3.Row) -> None:
            with self.db.connect() as db:
                node = db.execute(
                    "SELECT kind FROM knowledge_nodes WHERE id=? AND course_id=? "
                    "AND owner_user_id=? AND status='PRIVATE'",
                    (node_id, workspace["course_id"], owner),
                ).fetchone()
            if node is None:
                raise ApiError(404, "NODE_NOT_FOUND", "The knowledge node was not found.")
            if node["kind"] != "ATOMIC":
                raise ApiError(
                    422,
                    "ATOMIC_REQUIRED",
                    "Only atomic knowledge nodes have a Teaching Spec.",
                )
            self.check_evidence(
                workspace,
                {evidence_id for item in request.items for evidence_id in item.evidence_ids},
            )

        def save(
            db: sqlite3.Connection, workspace: sqlite3.Row, _: Any
        ) -> dict[str, Any]:
            node = db.execute(
                "SELECT kind FROM knowledge_nodes WHERE id=? AND course_id=? "
                "AND owner_user_id=? AND status='PRIVATE'",
                (node_id, workspace["course_id"], owner),
            ).fetchone()
            if node is None:
                raise ApiError(404, "NODE_NOT_FOUND", "The knowledge node was not found.")
            self.check_evidence(
                workspace,
                {evidence_id for item in request.items for evidence_id in item.evidence_ids},
            )
            latest = db.execute(
                "SELECT version,content_hash FROM teaching_specs WHERE node_id=? "
                "ORDER BY version DESC LIMIT 1",
                (node_id,),
            ).fetchone()
            if latest is not None and latest["content_hash"] == content_hash:
                raise ApiError(
                    409,
                    "SPEC_UNCHANGED",
                    "Create a new Teaching Spec only when its scope changes.",
                )
            version = int(latest["version"] if latest is not None else 0) + 1
            db.execute(
                "INSERT INTO teaching_specs(node_id,version,content_json,content_hash) "
                "VALUES(?,?,?,?)",
                (node_id, version, content, content_hash),
            )
            db.execute(
                "UPDATE teaching_spec_metadata SET change_reason=? "
                "WHERE node_id=? AND version=?",
                (request.change_reason, node_id, version),
            )
            return {
                "node_id": node_id,
                "version": version,
                "content_hash": content_hash,
                "items": [item.model_dump() for item in request.items],
                "learning_progress": "NOT_STARTED",
                "assessment_status": "NOT_ASSESSED",
                "evidence_ids": sorted(
                    {
                        evidence_id
                        for item in request.items
                        for evidence_id in item.evidence_ids
                    }
                ),
            }

        return self.operate(
            workspace_id,
            owner,
            request,
            "teaching.spec",
            prepare,
            save,
            resource_identity={"node_id": node_id},
        )

    def evidence_version(self, workspace: sqlite3.Row, evidence_id: str) -> sqlite3.Row:
        with self.db.connect() as db:
            row = db.execute(
                "SELECT document_versions.* FROM chunk_source_versions "
                "JOIN document_versions ON document_versions.id="
                "chunk_source_versions.document_version_id "
                "WHERE chunk_source_versions.chunk_id=?",
                (evidence_id,),
            ).fetchone()
        if row is None:
            raise ApiError(410, "SOURCE_UNAVAILABLE", "A source is no longer available.")
        is_course_source = (
            row["course_id"] == workspace["course_id"]
            and row["source_scope"] in {"OFFICIAL", "OWNER_COURSE"}
        )
        is_private_source = (
            row["course_id"] == workspace["private_course_id"]
            and row["source_scope"] == "WORKSPACE_PRIVATE"
        )
        if not (is_course_source or is_private_source):
            raise ApiError(410, "SOURCE_UNAVAILABLE", "A source is no longer available.")
        try:
            return document_version_for(self.db, row["id"], workspace["owner_user_id"])
        except ApiError as error:
            raise ApiError(
                410, "SOURCE_UNAVAILABLE", "A source is no longer available."
            ) from error

    def check_evidence(self, workspace: sqlite3.Row, evidence_ids: set[str]) -> None:
        for evidence_id in evidence_ids:
            self.evidence_version(workspace, evidence_id)

    def evidence(
        self, workspace: sqlite3.Row, query: str, scope: str = "union"
    ) -> list[dict[str, Any]]:
        courses = [workspace["course_id"], workspace["private_course_id"]]
        if scope != "union":
            courses = [courses[0 if scope == "official" else 1]]
        result: list[dict[str, Any]] = []
        for course in courses:
            source_scope: Literal["official", "mine"] = (
                "mine" if course == workspace["private_course_id"] else "official"
            )
            access = RetrievalAccess(
                owner_user_id=workspace["owner_user_id"], scope=source_scope
            )
            for hit in self.retriever.retrieve(
                course_id=course,
                query=query,
                top_k=3,
                access=access,
            ):
                version = self.evidence_version(workspace, hit.chunk_id)
                result.append(
                    {
                        "id": hit.chunk_id,
                        "document_id": hit.document_id,
                        "document_version_id": version["id"],
                        "document_version": version["sha256"],
                        "locator_type": hit.locator_type,
                        "locator_value": hit.locator_value,
                        "content": hit.content[:2500],
                        "scope": source_scope,
                        "source_scope": version["source_scope"],
                    }
                )
        return result

    def operate(
        self,
        workspace_id: str,
        owner: str,
        request: OperationInput,
        kind: str,
        prepare: Callable[[sqlite3.Row], Any],
        save: Callable[[sqlite3.Connection, sqlite3.Row, Any], dict[str, Any]],
        *,
        resource_identity: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        workspace = workspace_for(self.db, workspace_id, owner)
        request_hash = hashlib.sha256(
            encode(
                {
                    "kind": kind,
                    "resource_identity": resource_identity or {},
                    **request.model_dump(exclude={"revision"}),
                }
            ).encode()
        ).hexdigest()
        reserved_revision = request.revision + 1
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT * FROM learning_operations WHERE workspace_id=? AND id=?",
                (workspace_id, request.operation_id),
            ).fetchone()
            if previous:
                if previous["request_hash"] != request_hash:
                    raise ApiError(
                        409,
                        "OPERATION_REUSED",
                        "Operation ID already belongs to a different request.",
                    )
                if previous["status"] == "COMPLETED":
                    result = json.loads(previous["result_json"])
                    self.check_evidence(workspace, set(result.get("evidence_ids", [])))
                    return dict(result)
                raise ApiError(
                    409,
                    "OPERATION_" + previous["status"],
                    "Do not regenerate automatically. Check this operation's saved status.",
                )
            if db.execute(
                "SELECT 1 FROM learning_operations WHERE workspace_id=? AND status='RUNNING'",
                (workspace_id,),
            ).fetchone():
                raise ApiError(409, "WORKSPACE_BUSY", "Another bounded operation is running.")
            if (
                db.execute(
                    "SELECT COUNT(*) FROM learning_operations o JOIN learning_workspaces w ON "
                    "w.id=o.workspace_id "
                    "WHERE w.owner_user_id=? AND o.created_at>=date('now')",
                    (owner,),
                ).fetchone()[0]
                >= self.settings.v3_daily_operations
            ):
                raise ApiError(
                    429, "DAILY_QUOTA", "The daily learning-operation quota has been reached."
                )
            if (
                db.execute(
                    "UPDATE learning_workspaces SET revision=revision+1 WHERE id=? AND revision=?",
                    (workspace_id, request.revision),
                ).rowcount
                != 1
            ):
                raise ApiError(
                    409, "REVISION_CONFLICT", "Refresh shared state before another action."
                )
            db.execute(
                "INSERT INTO learning_operations(workspace_id,id,request_hash,kind,status) "
                "VALUES(?,?,?,?,'RUNNING')",
                (workspace_id, request.operation_id, request_hash, kind),
            )
            self.event(
                db, workspace_id, request.operation_id, "operation.started", {"workflow": kind}
            )
        # Network and expensive work never hold a SQLite write transaction.
        try:
            prepared = prepare(workspace)
            workspace = workspace_for(
                self.db, workspace_id, owner
            )  # permissions may change during generation
            with self.db.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                current = db.execute(
                    "SELECT revision FROM learning_workspaces WHERE id=?",
                    (workspace_id,),
                ).fetchone()
                if current is None or current["revision"] != reserved_revision:
                    raise ApiError(
                        409,
                        "REVISION_CONFLICT",
                        "The workspace changed while this operation was running; "
                        "the stale result was not saved.",
                    )
                result = save(db, workspace, prepared)
                result["revision"] = db.execute(
                    "SELECT revision FROM learning_workspaces WHERE id=?", (workspace_id,)
                ).fetchone()[0]
                result["operation_id"] = request.operation_id
                db.execute(
                    "UPDATE learning_operations SET status='COMPLETED',result_json=? WHERE "
                    "workspace_id=? AND id=?",
                    (encode(result), workspace_id, request.operation_id),
                )
                self.event(
                    db,
                    workspace_id,
                    request.operation_id,
                    kind + ".completed",
                    {"id": result.get("id"), "revision": result["revision"]},
                )
                return dict(result)
        except Exception as error:
            status = "FAILED" if isinstance(error, (ApiError, ValueError)) else "UNKNOWN"
            with self.db.connect() as db:
                db.execute(
                    "UPDATE learning_operations SET status=? WHERE workspace_id=? AND id=?",
                    (status, workspace_id, request.operation_id),
                )
                self.event(
                    db, workspace_id, request.operation_id, "operation.failed", {"status": status}
                )
            if isinstance(error, ApiError):
                raise
            raise ApiError(
                502,
                "MODEL_OUTPUT_REJECTED" if status == "FAILED" else "OPERATION_UNKNOWN",
                "No learning completion was saved; this request will not be retried automatically.",
            ) from error

    @staticmethod
    def event(
        db: sqlite3.Connection, workspace: str, operation: str, kind: str, payload: Any
    ) -> None:
        db.execute(
            "INSERT INTO learning_events(workspace_id,operation_id,kind,payload_json) "
            "VALUES(?,?,?,?)",
            (workspace, operation, kind, encode(payload)),
        )

    @staticmethod
    def cursor(db: sqlite3.Connection, workspace_id: str, **values: Any) -> None:
        previous = json.loads(
            db.execute(
                "SELECT cursor_json FROM learning_workspaces WHERE id=?", (workspace_id,)
            ).fetchone()[0]
        )
        db.execute(
            "UPDATE learning_workspaces SET cursor_json=? WHERE id=?",
            (encode({**previous, **values}), workspace_id),
        )

    def reserve_model_call(self, workspace_id: str, operation: str, role: str) -> str:
        reservation_id = identifier()
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            workspace = db.execute(
                "SELECT owner_user_id,course_id FROM learning_workspaces WHERE id=?",
                (workspace_id,),
            ).fetchone()
            if workspace is None:
                raise ApiError(404, "WORKSPACE_NOT_FOUND", "The workspace was not found.")
            user_calls = db.execute(
                "SELECT COUNT(*) FROM learning_model_call_reservations "
                "WHERE owner_user_id=? AND created_at>=date('now') AND status!='BLOCKED'",
                (workspace["owner_user_id"],),
            ).fetchone()[0]
            course_calls = db.execute(
                "SELECT COUNT(*) FROM learning_model_call_reservations "
                "WHERE owner_user_id=? AND course_id=? AND created_at>=date('now') "
                "AND status!='BLOCKED'",
                (workspace["owner_user_id"], workspace["course_id"]),
            ).fetchone()[0]
            if (
                user_calls >= self.settings.v3_daily_model_calls_per_user
                or course_calls >= self.settings.v3_daily_model_calls_per_user_course
            ):
                raise ApiError(
                    429,
                    "DAILY_MODEL_CALL_QUOTA",
                    "The daily model-call budget has been reached; no provider call was made.",
                )
            db.execute(
                "INSERT INTO learning_model_call_reservations("
                "id,workspace_id,operation_id,owner_user_id,course_id,role,"
                "reserved_output_tokens,status) VALUES(?,?,?,?,?,?,?,'RESERVED')",
                (
                    reservation_id,
                    workspace_id,
                    operation,
                    workspace["owner_user_id"],
                    workspace["course_id"],
                    role,
                    self.settings.v3_max_output_tokens,
                ),
            )
        return reservation_id

    def record_run(
        self,
        workspace_id: str,
        operation: str,
        run: dict[str, Any],
        reservation_id: str,
    ) -> None:
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO learning_model_run_evidence("
                "id,workspace_id,operation_id,role,model_id,provider_label,protocol,"
                "region_label,template_version,schema_version,input_hash,started_at,"
                "finished_at,latency_ms,input_tokens,output_tokens,status,error_class,"
                "provider_response_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    identifier(),
                    workspace_id,
                    operation,
                    run["role"],
                    run["model"],
                    run.get("provider", "UNRECORDED"),
                    run["protocol"],
                    run.get("region", "UNKNOWN"),
                    run.get("template_version", TEMPLATE_VERSION),
                    run.get("schema_version", "UNRECORDED"),
                    run.get("input_hash"),
                    run.get("started_at", "1970-01-01T00:00:00Z"),
                    run.get("finished_at", "1970-01-01T00:00:00Z"),
                    run.get("latency_ms", 0),
                    run.get("input_tokens", 0),
                    run.get("output_tokens", 0),
                    run.get("status", "UNKNOWN"),
                    run.get("error_class"),
                    run.get("provider_response_id"),
                ),
            )
            if (
                db.execute(
                    "UPDATE learning_model_call_reservations SET status=?,input_tokens=?,"
                    "output_tokens=?,finished_at=? WHERE id=? AND workspace_id=? "
                    "AND operation_id=? AND status='RESERVED'",
                    (
                        run.get("status", "UNKNOWN"),
                        run.get("input_tokens", 0),
                        run.get("output_tokens", 0),
                        run.get("finished_at", "1970-01-01T00:00:00Z"),
                        reservation_id,
                        workspace_id,
                        operation,
                    ),
                ).rowcount
                != 1
            ):
                raise ApiError(
                    409,
                    "MODEL_CALL_RESERVATION_CONFLICT",
                    "The model-call reservation could not be finalized safely.",
                )

    def generate(
        self,
        workspace_id: str,
        operation: str,
        schema: type[Output],
        *,
        instructions: str,
        context: dict[str, Any],
        role: str,
        template_version: str,
        schema_version: str,
        images: list[ProviderImage] | None = None,
    ) -> tuple[Output, dict[str, Any]]:
        reservation_id = self.reserve_model_call(workspace_id, operation, role)
        try:
            output, run = self.provider.generate(
                schema,
                instructions=instructions,
                context=context,
                role=role,
                template_version=template_version,
                schema_version=schema_version,
                images=images,
            )
        except ProviderCallFailure as error:
            self.record_run(workspace_id, operation, error.run, reservation_id)
            raise error.cause from error
        self.record_run(workspace_id, operation, run, reservation_id)
        return output, run

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(encode(value).encode()).hexdigest()

    def preference_version(
        self, workspace_id: str, preference: str, language: str
    ) -> dict[str, Any]:
        payload = {"preference": preference.strip(), "language": language}
        return self.plans.preference_version(workspace_id, self._hash(payload), payload)

    def cached_plan(
        self,
        *,
        workspace_id: str,
        node_id: str,
        journey_id: str,
        identity: dict[str, Any],
        cache_key: str,
        explicit_replan: bool,
    ) -> sqlite3.Row | None:
        return self.plans.cached_plan(
            workspace_id=workspace_id,
            node_id=node_id,
            journey_id=journey_id,
            identity=identity,
            cache_key=cache_key,
            explicit_replan=explicit_replan,
        )

    def invalidate_plan(self, plan_id: str, reason: str) -> None:
        self.plans.invalidate(plan_id, reason)

    def save_plan(
        self,
        *,
        workspace: sqlite3.Row,
        journey: sqlite3.Row,
        request: TeachInput,
        plan: TeachingPlan,
        run: dict[str, Any],
        preference: dict[str, Any],
        identity: dict[str, Any],
        cache_key: str,
        input_hash: str,
    ) -> sqlite3.Row:
        return self.plans.save(
            workspace=workspace,
            journey=journey,
            request_revision=request.revision,
            operation_id=request.operation_id,
            plan=plan,
            run=run,
            preference=preference,
            identity=identity,
            cache_key=cache_key,
            input_hash=input_hash,
            template_version=TEMPLATE_VERSION,
            model_id=self.provider.cache_model,
            protocol=self.provider.cache_protocol,
        )

    def resolve_plan(
        self,
        *,
        workspace: sqlite3.Row,
        journey: sqlite3.Row,
        node: dict[str, Any],
        request: TeachInput,
        items: list[TeachingItem],
        eligible: list[TeachingItem],
        evidence: list[dict[str, Any]],
        bridge: sqlite3.Row | None,
        planner_context: dict[str, Any],
    ) -> tuple[sqlite3.Row, TeachingPlan, bool]:
        preference = self.preference_version(
            workspace["id"], request.preference, request.language
        )
        source_version_ids = sorted(
            {
                f"{item['document_version_id']}:{item['document_version']}"
                for item in evidence
            }
        )
        identity = {
            "owner_user_id": workspace["owner_user_id"],
            "workspace_id": workspace["id"],
            "course_id": workspace["course_id"],
            "node_id": node["id"],
            "spec_version": journey["spec_version"],
            "spec_hash": node["spec_hash"],
            "preference_version": preference["version"],
            "preference_hash": preference["preference_hash"],
            "template_version": TEMPLATE_VERSION,
            "schema_version": "v3.2",
            "model_id": self.provider.cache_model,
            "protocol": self.provider.cache_protocol,
            "course_policy_version": planner_context["course_policy"]["version"],
            "source_version_ids": source_version_ids,
            "bridge_id": bridge["id"] if bridge is not None else None,
            "bridge_revision": bridge["revision"] if bridge is not None else None,
            "performance_trigger_ids": sorted(
                trigger["id"]
                for trigger in planner_context["performance_replan_triggers"]
            ),
        }
        cache_key = self._hash(identity)
        input_hash = self._hash(
            {
                "identity": identity,
                "eligible": [item.model_dump() for item in eligible],
            }
        )
        expected_case = "CASE_B" if request.preference.strip() else "CASE_A"
        cached = self.cached_plan(
            workspace_id=workspace["id"],
            node_id=node["id"],
            journey_id=journey["id"],
            identity=identity,
            cache_key=cache_key,
            explicit_replan=request.replan,
        )
        if cached is not None:
            try:
                plan = TeachingPlan.model_validate_json(cached["plan_json"])
                item_by_id = {item.item_id: item for item in items}
                planned_item_ids = {
                    item_id for unit in plan.units for item_id in unit.target_item_ids
                }
                if not planned_item_ids <= item_by_id.keys():
                    raise ValueError("Cached plan references a retired Teaching Item")
                validate_plan(
                    plan,
                    node_id=node["id"],
                    spec_version=journey["spec_version"],
                    eligible=[item_by_id[item_id] for item_id in planned_item_ids],
                    evidence_ids=[item["id"] for item in evidence],
                    bridge_id=request.bridge_id,
                    expected_case=expected_case,
                )
                delivered = self.plans.delivered_unit_keys(cached["id"])
                pending_items = {
                    item_id
                    for unit in plan.units
                    if unit.unit_key not in delivered
                    for item_id in unit.target_item_ids
                }
                if pending_items != {item.item_id for item in eligible}:
                    raise ValueError("Cached plan does not match remaining REQUIRED scope")
                return cached, plan, True
            except ValueError:
                self.invalidate_plan(cached["id"], "CACHE_REVALIDATION_FAILED")
        plan, run = self.generate(
            workspace["id"],
            request.operation_id,
            TeachingPlan,
            instructions=template("planner"),
            context=planner_context,
            role="planner",
            template_version=TEMPLATE_VERSION,
            schema_version="v3.2",
        )
        validate_plan(
            plan,
            node_id=node["id"],
            spec_version=journey["spec_version"],
            eligible=eligible,
            evidence_ids=[item["id"] for item in evidence],
            bridge_id=request.bridge_id,
            expected_case=expected_case,
        )
        stored = self.save_plan(
            workspace=workspace,
            journey=journey,
            request=request,
            plan=plan,
            run=run,
            preference=preference,
            identity=identity,
            cache_key=cache_key,
            input_hash=input_hash,
        )
        return stored, plan, False

    def solve(self, workspace_id: str, owner: str, request: SolveInput) -> dict[str, Any]:
        def prepare(workspace: sqlite3.Row) -> Any:
            nodes = [self.node(workspace, n) for n in request.node_ids]
            if any(n["kind"] != "ATOMIC" for n in nodes):
                raise ApiError(
                    422, "ATOMIC_REQUIRED", "Solution steps must reference atomic knowledge."
                )
            image_inputs: list[ProviderImage] = []
            indexed_entry: dict[str, Any] | None = None
            image_source: dict[str, Any] | None = None
            if request.problem_index_entry_id is not None:
                indexed_entry = self.problems.index_entry(
                    workspace_id, owner, request.problem_index_entry_id
                )
                question = cast(str, indexed_entry["question_text"])
                input_kind = "INDEXED"
                retrieval_query = question
            elif request.image_document_version_id is not None:
                image, image_source = self.problems.image_input(
                    workspace_id,
                    owner,
                    request.image_document_version_id,
                    max_bytes=self.settings.v3_problem_image_max_bytes,
                )
                image_inputs.append(image)
                question = request.question or "Transcribe and solve the supplied image question."
                input_kind = "IMAGE"
                retrieval_query = request.transcription_hint or request.question or "image question"
            else:
                question = cast(str, request.question)
                input_kind = "TEXT"
                retrieval_query = question
            evidence = self.evidence(workspace, retrieval_query, request.scope)
            if indexed_entry is not None and not any(
                item["id"] == indexed_entry["chunk_id"] for item in evidence
            ):
                source_scope = indexed_entry["source_scope"]
                evidence.insert(
                    0,
                    {
                        "id": indexed_entry["chunk_id"],
                        "document_id": indexed_entry["document_id"],
                        "document_version_id": indexed_entry["document_version_id"],
                        "document_version": indexed_entry["document_sha256"],
                        "locator_type": indexed_entry["locator_type"],
                        "locator_value": indexed_entry["locator_value"],
                        "content": indexed_entry["question_text"],
                        "scope": "mine"
                        if source_scope == "WORKSPACE_PRIVATE"
                        else "official",
                        "source_scope": source_scope,
                    },
                )
            instructions, template_version = problem_template()
            output, _run = self.generate(
                workspace_id,
                request.operation_id,
                ProblemSolutionOutput,
                instructions=instructions,
                context={
                    "input_kind": input_kind,
                    "question": question,
                    "transcription_hint": request.transcription_hint,
                    "indexed_source": indexed_entry,
                    "image_source": image_source,
                    "nodes": nodes,
                    "evidence": evidence,
                },
                role="problem",
                template_version=template_version,
                schema_version="ProblemSolutionOutput:v2",
                images=image_inputs,
            )
            if input_kind == "IMAGE" and output.question_transcription is None:
                raise ValueError("Image output must preserve a question transcription")
            allowed = {e["id"] for e in evidence}
            by_node = {node["id"]: node for node in nodes}
            for step in output.steps:
                for link in step.knowledge_links:
                    if link.resolution_status == "UNRESOLVED":
                        continue
                    node = by_node.get(cast(str, link.node_id))
                    if node is None or link.spec_version != node["spec_version"]:
                        raise ValueError("Unknown node or Teaching Spec in solution")
                    allowed_items = {item["item_id"] for item in node["items"]}
                    if link.item_id not in allowed_items:
                        raise ValueError("Unknown Teaching Item in solution")
            if any(not set(s.source_refs) <= allowed for s in output.steps):
                raise ValueError("Unknown source in solution")
            return output, evidence, {
                "input_kind": input_kind,
                "question": question,
                "indexed_entry": indexed_entry,
                "image_source": image_source,
            }

        def save(db: sqlite3.Connection, workspace: sqlite3.Row, prepared: Any) -> dict[str, Any]:
            output, evidence, problem_input = prepared
            self.check_evidence(workspace, {e["id"] for e in evidence})
            for node_id in request.node_ids:
                self.node(workspace, node_id)
            problem_id, solution_id, attempt_id = identifier(), identifier(), identifier()
            problem_revision_id, solution_revision_id = identifier(), identifier()
            evidence_ids = [e["id"] for e in evidence]
            input_kind = problem_input["input_kind"]
            indexed_entry = problem_input["indexed_entry"]
            image_source = problem_input["image_source"]
            question = (
                cast(str, output.question_transcription)
                if input_kind == "IMAGE"
                else cast(str, problem_input["question"])
            )
            db.execute(
                "INSERT INTO "
                "learning_problems(id,workspace_id,question,conditions_json,"
                "source_refs_json,attempt_id) VALUES(?,?,?,?,?,?)",
                (
                    problem_id,
                    workspace_id,
                    question,
                    encode(output.conditions),
                    encode(evidence_ids),
                    attempt_id,
                ),
            )
            problem_identity = {
                "input_kind": input_kind,
                "question": question,
                "question_transcription": output.question_transcription,
                "visual_uncertainties": output.visual_uncertainties,
                "problem_index_entry_id": (
                    indexed_entry["id"] if indexed_entry is not None else None
                ),
                "input_document_version_id": (
                    indexed_entry["document_version_id"]
                    if indexed_entry is not None
                    else image_source["document_version_id"]
                    if image_source is not None
                    else None
                ),
                "conditions": output.conditions,
                "evidence_ids": evidence_ids,
            }
            db.execute(
                "INSERT INTO problem_revisions("
                "id,problem_id,workspace_id,revision,input_kind,question_text,"
                "question_transcription,transcription_status,visual_uncertainties_json,"
                "problem_index_entry_id,input_document_version_id,input_source_sha256,"
                "source_locator_json,content_hash,validation_status) "
                "VALUES(?,?,?,1,?,?,?,?,?,?,?,?,?,?,'VALIDATED')",
                (
                    problem_revision_id,
                    problem_id,
                    workspace_id,
                    input_kind,
                    question,
                    output.question_transcription,
                    (
                        "UNCERTAIN"
                        if input_kind == "IMAGE" and output.visual_uncertainties
                        else "MODEL_PROPOSED"
                        if input_kind == "IMAGE"
                        else "NOT_APPLICABLE"
                    ),
                    encode(output.visual_uncertainties),
                    indexed_entry["id"] if indexed_entry is not None else None,
                    (
                        indexed_entry["document_version_id"]
                        if indexed_entry is not None
                        else image_source["document_version_id"]
                        if image_source is not None
                        else None
                    ),
                    (
                        indexed_entry["document_sha256"]
                        if indexed_entry is not None
                        else image_source["document_sha256"]
                        if image_source is not None
                        else None
                    ),
                    encode(
                        {
                            "question_number": indexed_entry["question_number"],
                            "question_part": indexed_entry["question_part"],
                            "locator_type": indexed_entry["locator_type"],
                            "locator_value": indexed_entry["locator_value"],
                        }
                        if indexed_entry is not None
                        else {}
                    ),
                    self._hash(problem_identity),
                ),
            )
            db.execute(
                "INSERT INTO problem_attempts("
                "id,workspace_id,problem_revision_id,assistance) "
                "VALUES(?,?,?,'ANSWER_EXPOSED')",
                (attempt_id, workspace_id, problem_revision_id),
            )
            steps: list[dict[str, Any]] = []
            for index, step_output in enumerate(output.steps):
                links = [
                    {**link.model_dump(), "id": identifier()}
                    for link in step_output.knowledge_links
                ]
                steps.append(
                    {
                        **step_output.model_dump(exclude={"knowledge_links"}),
                        "id": identifier(),
                        "ordinal": index + 1,
                        "knowledge_links": links,
                    }
                )
            result = {
                **output.model_dump(),
                "id": solution_id,
                "problem_id": problem_id,
                "problem_version": 1,
                "problem_revision": 1,
                "problem_revision_id": problem_revision_id,
                "solution_version": 1,
                "solution_revision": 1,
                "solution_revision_id": solution_revision_id,
                "attempt_id": attempt_id,
                "question": question,
                "input_kind": input_kind,
                "problem_index_entry_id": (
                    indexed_entry["id"] if indexed_entry is not None else None
                ),
                "input_document_version_id": (
                    indexed_entry["document_version_id"]
                    if indexed_entry is not None
                    else image_source["document_version_id"]
                    if image_source is not None
                    else None
                ),
                "steps": steps,
                "assistance": "ANSWER_EXPOSED",
                "evidence_ids": evidence_ids,
                "sources": [{k: v for k, v in e.items() if k != "content"} for e in evidence],
            }
            db.execute(
                "INSERT INTO learning_solutions VALUES(?,?,1,?)",
                (solution_id, problem_id, encode(result)),
            )
            db.execute(
                "INSERT INTO solution_revisions("
                "id,workspace_id,solution_id,problem_revision_id,attempt_id,revision,"
                "answer_origin,verification,content_hash,validation_status) "
                "VALUES(?,?,?,?,?,1,?,?,?,'VALIDATED')",
                (
                    solution_revision_id,
                    workspace_id,
                    solution_id,
                    problem_revision_id,
                    attempt_id,
                    output.answer_origin,
                    output.verification,
                    self._hash(output.model_dump()),
                ),
            )
            for step in steps:
                db.execute(
                    "INSERT INTO learning_steps VALUES(?,?,?,?)",
                    (step["id"], solution_id, step["ordinal"], encode(step)),
                )
                for link_ordinal, link in enumerate(step["knowledge_links"], start=1):
                    db.execute(
                        "INSERT INTO step_knowledge_links("
                        "id,workspace_id,solution_revision_id,step_id,ordinal,"
                        "resolution_status,node_id,spec_version,item_id,question_text,"
                        "reason,unresolved_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            link["id"],
                            workspace_id,
                            solution_revision_id,
                            step["id"],
                            link_ordinal,
                            link["resolution_status"],
                            link["node_id"],
                            link["spec_version"],
                            link["item_id"],
                            link["question_text"],
                            link["reason"],
                            link["unresolved_reason"],
                        ),
                    )
            self.cursor(
                db,
                workspace_id,
                problem_id=problem_id,
                solution_id=solution_id,
                step_id=steps[0]["id"],
                pane="PROBLEM",
            )
            return dict(result)

        return self.operate(workspace_id, owner, request, "solution", prepare, save)

    @staticmethod
    def journey(db: sqlite3.Connection, workspace_id: str, node: dict[str, Any]) -> sqlite3.Row:
        if node["kind"] != "ATOMIC" or node["spec_version"] is None:
            raise ApiError(
                422,
                "ATOMIC_REQUIRED",
                "A learning journey requires an atomic node with an active Teaching Spec.",
            )
        row = db.execute(
            "SELECT * FROM learning_journeys WHERE workspace_id=? AND node_id=? "
            "AND spec_version=?",
            (workspace_id, node["id"], node["spec_version"]),
        ).fetchone()
        if row is None:
            journey_id = identifier()
            db.execute(
                "INSERT INTO learning_journeys(id,workspace_id,node_id,spec_version) "
                "VALUES(?,?,?,?)",
                (journey_id, workspace_id, node["id"], node["spec_version"]),
            )
            row = db.execute("SELECT * FROM learning_journeys WHERE id=?", (journey_id,)).fetchone()
        return cast(sqlite3.Row, row)

    def bridge(self, workspace_id: str, owner: str, request: BridgeInput) -> dict[str, Any]:
        def save(db: sqlite3.Connection, workspace: sqlite3.Row, _: Any) -> dict[str, Any]:
            row = db.execute(
                "SELECT p.*,s.id AS solution_id,s.version AS solution_version,st.content_json "
                "AS step_json "
                "FROM learning_steps st JOIN learning_solutions s ON s.id=st.solution_id JOIN "
                "learning_problems p ON p.id=s.problem_id "
                "WHERE st.id=? AND p.workspace_id=?",
                (request.step_id, workspace_id),
            ).fetchone()
            if row is None:
                raise ApiError(404, "STEP_NOT_FOUND", "The step was not found.")
            step = json.loads(row["step_json"])
            link = db.execute(
                "SELECT link.*,revision.problem_revision_id,revision.attempt_id,"
                "revision.id AS saved_solution_revision_id "
                "FROM step_knowledge_links AS link "
                "JOIN solution_revisions AS revision "
                "ON revision.id=link.solution_revision_id "
                "WHERE link.workspace_id=? AND link.step_id=? AND "
                + ("link.id=?" if request.knowledge_link_id else "link.node_id=?"),
                (
                    workspace_id,
                    request.step_id,
                    request.knowledge_link_id or request.node_id,
                ),
            ).fetchone()
            if link is None or (
                request.node_id is not None and link["node_id"] != request.node_id
            ):
                raise ApiError(
                    422,
                    "STEP_LINK_MISMATCH",
                    "This step does not contain the selected knowledge question.",
                )
            if link["resolution_status"] == "UNRESOLVED":
                raise ApiError(
                    422,
                    "KNOWLEDGE_LINK_UNRESOLVED",
                    "This knowledge question is awaiting an authorized atomic-node binding.",
                )
            node_id = cast(str, link["node_id"])
            node = self.node(workspace, node_id)
            self.check_evidence(workspace, set(json.loads(row["source_refs_json"])))
            previous = db.execute(
                "SELECT snapshot_json FROM learning_bridges WHERE workspace_id=? AND step_id=? "
                "AND node_id=?",
                (workspace_id, request.step_id, node_id),
            ).fetchone()
            if previous:
                result = json.loads(previous[0])
            else:
                journey = self.journey(db, workspace_id, node)
                result = {
                    "id": identifier(),
                    "source_problem_id": row["id"],
                    "problem_version": row["version"],
                    "source_attempt_id": row["attempt_id"],
                    "solution_id": row["solution_id"],
                    "solution_version": row["solution_version"],
                    "problem_revision_id": link["problem_revision_id"],
                    "solution_revision_id": link["saved_solution_revision_id"],
                    "step_id": request.step_id,
                    "knowledge_link_id": link["id"],
                    "node_id": node_id,
                    "spec_version": link["spec_version"],
                    "item_id": link["item_id"],
                    "learning_session_id": journey["id"],
                    "target_learning_session": journey["id"],
                    "reason_for_learning": link["reason"],
                    "selected_question": link["question_text"],
                    "problem_snapshot": {
                        "question": row["question"],
                        "conditions": json.loads(row["conditions_json"]),
                        "step": step,
                    },
                    "return_anchor": "step-" + request.step_id,
                    "return_problem_id": row["id"],
                    "return_step_id": request.step_id,
                    "evidence_ids": json.loads(row["source_refs_json"]),
                }
                db.execute(
                    "INSERT INTO "
                    "learning_bridges(id,workspace_id,step_id,node_id,journey_id,"
                    "snapshot_json,status) VALUES(?,?,?,?,?,?,'OPEN')",
                    (
                        result["id"],
                        workspace_id,
                        request.step_id,
                        node_id,
                        journey["id"],
                        encode(result),
                    ),
                )
                validation = (
                    "VALIDATED"
                    if link["resolution_status"] == "VALIDATED"
                    else "LEGACY_PRESERVED"
                )
                db.execute(
                    "INSERT INTO learning_bridge_contexts("
                    "bridge_id,workspace_id,owner_user_id,course_id,problem_revision_id,"
                    "attempt_id,solution_revision_id,source_step_id,knowledge_link_id,"
                    "knowledge_node_ids_json,node_id,spec_version,item_id,reason_for_learning,"
                    "selected_question,target_learning_session,return_problem_id,return_step_id,"
                    "return_anchor,idempotency_key,validation_status) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        result["id"],
                        workspace_id,
                        owner,
                        workspace["course_id"],
                        link["problem_revision_id"],
                        link["attempt_id"],
                        link["saved_solution_revision_id"],
                        request.step_id,
                        link["id"],
                        encode([node_id]),
                        node_id,
                        link["spec_version"],
                        link["item_id"],
                        link["reason"],
                        link["question_text"],
                        journey["id"],
                        row["id"],
                        request.step_id,
                        result["return_anchor"],
                        self._hash({"workspace_id": workspace_id, "link_id": link["id"]}),
                        validation,
                    ),
                )
            self.cursor(
                db,
                workspace_id,
                bridge_id=result["id"],
                journey_id=result["learning_session_id"],
                node_id=node_id,
                pane="TEACHING",
            )
            return dict(result)

        return self.operate(workspace_id, owner, request, "bridge", lambda w: None, save)

    def teach(self, workspace_id: str, owner: str, request: TeachInput) -> dict[str, Any]:
        def prepare(workspace: sqlite3.Row) -> Any:
            node = self.node(workspace, request.node_id)
            if node["kind"] != "ATOMIC":
                raise ApiError(
                    422,
                    "ATOMIC_REQUIRED",
                    "Teach atomic descendants instead of a composite node.",
                )
            with self.db.connect() as db:
                journey = self.journey(db, workspace_id, node)
                spec = db.execute(
                    "SELECT content_json FROM teaching_specs WHERE node_id=? AND version=?",
                    (node["id"], journey["spec_version"]),
                ).fetchone()
                covered = {
                    r[0]
                    for r in db.execute(
                        "SELECT DISTINCT item_id FROM teaching_delivery_evidence "
                        "WHERE journey_id=? AND validation_status IN "
                        "('VALIDATED','LEGACY_PRESERVED','REVIEWED')",
                        (journey["id"],),
                    )
                }
                bridge = (
                    db.execute(
                        "SELECT * FROM learning_bridges WHERE id=? AND workspace_id=? AND "
                        "node_id=?",
                        (request.bridge_id, workspace_id, request.node_id),
                    ).fetchone()
                    if request.bridge_id
                    else None
                )
                replan_triggers = self.assessments.pending_replan(
                    db,
                    workspace,
                    node["id"],
                )
            if request.bridge_id and (
                bridge is None or bridge["status"] in ("CANCELLED", "SOURCE_UNAVAILABLE")
            ):
                raise ApiError(404, "BRIDGE_NOT_FOUND", "The active bridge was not found.")
            items = [TeachingItem.model_validate(i) for i in json.loads(spec[0])]
            uncovered_required = [
                i for i in items if i.item_id not in covered and i.requirement == "REQUIRED"
            ]
            replan_item_ids = {
                item_id
                for trigger in replan_triggers
                for item_id in trigger["item_ids"]
            }
            known_item_ids = {item.item_id for item in items}
            eligible_item_ids = {
                item.item_id for item in uncovered_required
            } | (replan_item_ids & known_item_ids)
            eligible = [item for item in items if item.item_id in eligible_item_ids]
            if not eligible:
                if replan_triggers:
                    raise ApiError(
                        409,
                        "REPLAN_SPEC_CHANGED",
                        "Pending performance evidence targets a retired Teaching Spec item.",
                    )
                raise ApiError(
                    409, "SCOPE_COMPLETE", "All REQUIRED teaching content has been saved."
                )
            evidence = self.evidence(workspace, node["title"])
            bridge_data = json.loads(bridge["snapshot_json"]) if bridge else None
            if bridge_data:
                self.check_evidence(workspace, set(bridge_data["evidence_ids"]))
            context = {
                "node_id": node["id"],
                "knowledge_node": node,
                "teaching_spec_version": journey["spec_version"],
                "spec_version": journey["spec_version"],
                "required_items": [
                    item.model_dump() for item in items if item.requirement == "REQUIRED"
                ],
                "recommended_items": [
                    item.model_dump() for item in items if item.requirement == "RECOMMENDED"
                ],
                "optional_items": [
                    item.model_dump() for item in items if item.requirement == "OPTIONAL"
                ],
                "eligible": [i.model_dump() for i in eligible],
                "covered_item_ids": sorted(covered),
                "performance_replan_triggers": replan_triggers,
                "planning_scope": (
                    "REMEDIATION_AND_REQUIRED"
                    if replan_triggers
                    else "UNCOVERED_REQUIRED"
                ),
                "preference": request.preference,
                "language": request.language,
                "major_policy": node["major"],
                "course_policy": course_policy(workspace["course_id"]).model_dump(),
                "learning_cursor": json.loads(workspace["cursor_json"]),
                "evidence": evidence,
                "bridge_id": request.bridge_id,
                "bridge": bridge_data,
                "output_budget": self.settings.v3_max_output_tokens,
            }
            plan_row, plan, plan_reused = self.resolve_plan(
                workspace=workspace,
                journey=journey,
                node=node,
                request=request,
                items=items,
                eligible=eligible,
                evidence=evidence,
                bridge=bridge,
                planner_context=context,
            )
            delivered = self.plans.delivered_unit_keys(plan_row["id"])
            unit_plan = next(
                (unit for unit in plan.units if unit.unit_key not in delivered), None
            )
            if unit_plan is None:
                raise ApiError(409, "SCOPE_COMPLETE", "The saved teaching plan is complete.")
            if unit_plan.stop_condition == "MISSING_EVIDENCE":
                raise ApiError(
                    409,
                    "MISSING_EVIDENCE",
                    "The saved plan identifies missing evidence; no teaching completion "
                    "was generated.",
                )
            selected_evidence_ids = set(unit_plan.selected_evidence_ids)
            selected_evidence = [
                item for item in evidence if item["id"] in selected_evidence_ids
            ]
            unit_context = {**context, "evidence": selected_evidence}
            instructions, compiled = compile_unit(
                major=node["major"],
                plan=plan,
                unit_plan=unit_plan,
                items=[i for i in items if i.item_id in unit_plan.target_item_ids],
                context=unit_context,
            )
            anchor = bridge_data["return_anchor"] if bridge_data else None
            unit, _run = self.generate(
                workspace_id,
                request.operation_id,
                TeachingUnitOutput,
                instructions=instructions,
                context={
                    "compiled": json.loads(compiled),
                    "plan": plan.model_dump(),
                    "plan_unit": unit_plan.model_dump(),
                    "return_anchor": anchor,
                },
                role="teacher",
                template_version=TEMPLATE_VERSION,
                schema_version="v3.2",
            )
            validate_unit(
                unit,
                plan=plan,
                unit_plan=unit_plan,
                node_ids={node["id"]},
                return_anchor=anchor,
            )
            return (
                journey["id"],
                node,
                items,
                plan_row,
                plan,
                unit_plan,
                unit,
                selected_evidence,
                plan_reused,
                replan_triggers,
            )

        def save(db: sqlite3.Connection, workspace: sqlite3.Row, data: Any) -> dict[str, Any]:
            (
                journey_id,
                node,
                items,
                plan_row,
                plan,
                unit_plan,
                unit,
                evidence,
                plan_reused,
                replan_triggers,
            ) = data
            self.node(workspace, node["id"])
            self.check_evidence(workspace, {e["id"] for e in evidence})
            current_plan = db.execute(
                "SELECT status,journey_id FROM teaching_plan_versions WHERE id=?",
                (plan_row["id"],),
            ).fetchone()
            if (
                current_plan is None
                or current_plan["status"] != "ACTIVE"
                or current_plan["journey_id"] != journey_id
                or db.execute(
                    "SELECT 1 FROM teaching_unit_plan_links WHERE plan_version_id=? "
                    "AND plan_unit_key=?",
                    (plan_row["id"], unit_plan.unit_key),
                ).fetchone()
            ):
                raise ApiError(
                    409,
                    "PLAN_CONFLICT",
                    "The teaching plan changed before this unit could be saved.",
                )
            unit_id = identifier()
            policy = course_policy(workspace["course_id"])
            saved_unit = {
                **unit.model_dump(),
                "display": {"question_prefix": policy.question_prefix},
                "plan_version": plan_row["version"],
                "plan_unit_key": unit_plan.unit_key,
                "plan_reused": plan_reused,
                "remediation_trigger_ids": [
                    trigger["id"]
                    for trigger in replan_triggers
                    if set(trigger["item_ids"]) & set(unit_plan.target_item_ids)
                ],
            }
            db.execute(
                "INSERT INTO "
                "teaching_units(id,journey_id,operation_id,workflow,content_json,"
                "plan_json,provenance_json) VALUES(?,?,?,'TEACHING',?,?,?)",
                (
                    unit_id,
                    journey_id,
                    request.operation_id,
                    encode(saved_unit),
                    encode(plan.model_dump()),
                    encode(
                        {
                            "prompt_version": TEMPLATE_VERSION,
                            "schema_version": plan.schema_version,
                            "spec_hash": node["spec_hash"],
                            "model": self.provider.cache_model,
                            "evidence_ids": [e["id"] for e in evidence],
                            "preference_version": plan_row["preference_version"],
                            "preference_hash": plan_row["preference_hash"],
                            "language": request.language,
                            "plan_version_id": plan_row["id"],
                            "plan_unit_key": unit_plan.unit_key,
                            "course_policy_version": policy.version,
                        }
                    ),
                ),
            )
            db.execute(
                "INSERT INTO teaching_unit_plan_links("
                "teaching_unit_id,plan_version_id,plan_unit_key) VALUES(?,?,?)",
                (unit_id, plan_row["id"], unit_plan.unit_key),
            )
            sections = {section.section_id: section for section in unit.sections}
            for proposal in unit.coverage_proposals:
                for section_id in proposal.section_ids:
                    section_hash = self._hash(sections[section_id].model_dump())
                    db.execute(
                        "INSERT INTO teaching_delivery_evidence("
                        "id,journey_id,node_id,spec_version,item_id,teaching_unit_id,"
                        "section_id,plan_version_id,plan_unit_key,content_hash,"
                        "validation_status,validation_reason) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,'VALIDATED',"
                        "'SERVER_SCHEMA_SCOPE_AND_PERSISTENCE_V1')",
                        (
                            identifier(),
                            journey_id,
                            node["id"],
                            plan.spec_version,
                            proposal.item_id,
                            unit_id,
                            section_id,
                            plan_row["id"],
                            unit_plan.unit_key,
                            section_hash,
                        ),
                    )
                db.execute(
                    "INSERT OR IGNORE INTO "
                    "learning_coverage(journey_id,item_id,unit_id,section_ids_json) "
                    "VALUES(?,?,?,?)",
                    (journey_id, proposal.item_id, unit_id, encode(proposal.section_ids)),
                )
            covered = {
                r[0]
                for r in db.execute(
                    "SELECT DISTINCT item_id FROM teaching_delivery_evidence "
                    "WHERE journey_id=? AND validation_status IN "
                    "('VALIDATED','LEGACY_PRESERVED','REVIEWED')",
                    (journey_id,),
                )
            }
            required = {i.item_id for i in items if i.requirement == "REQUIRED"}
            progress = "LEARNED" if required <= covered else "LEARNING"
            db.execute("UPDATE learning_journeys SET status=? WHERE id=?", (progress, journey_id))
            for trigger in replan_triggers:
                if set(trigger["item_ids"]) & set(unit_plan.target_item_ids):
                    db.execute(
                        "INSERT OR IGNORE INTO teaching_unit_remediations("
                        "trigger_id,teaching_unit_id) VALUES(?,?)",
                        (trigger["id"], unit_id),
                    )
            self.plans.complete_if_delivered(db, plan_row["id"])
            completed_plan = db.execute(
                "SELECT status FROM teaching_plan_versions WHERE id=?",
                (plan_row["id"],),
            ).fetchone()
            if completed_plan is not None and completed_plan["status"] == "COMPLETED":
                for trigger in replan_triggers:
                    remediated_items = {
                        str(row[0])
                        for row in db.execute(
                            "SELECT DISTINCT target.value "
                            "FROM teaching_unit_remediations AS remediation "
                            "JOIN teaching_unit_plan_links AS link "
                            "ON link.teaching_unit_id=remediation.teaching_unit_id "
                            "JOIN teaching_plan_units AS plan_unit "
                            "ON plan_unit.plan_version_id=link.plan_version_id "
                            "AND plan_unit.unit_key=link.plan_unit_key,"
                            "json_each(plan_unit.target_item_ids_json) AS target "
                            "WHERE remediation.trigger_id=?",
                            (trigger["id"],),
                        )
                    }
                    if set(trigger["item_ids"]) <= remediated_items:
                        db.execute(
                            "UPDATE learning_replan_triggers SET status='APPLIED',"
                            "applied_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                            "WHERE id=? AND status='PENDING'",
                            (trigger["id"],),
                        )
            if request.bridge_id:
                db.execute(
                    "UPDATE learning_bridges SET status=? WHERE id=? AND "
                    "workspace_id=?",
                    (
                        "READY_TO_RETURN" if progress == "LEARNED" else "LEARNING",
                        request.bridge_id,
                        workspace_id,
                    ),
                )
            self.cursor(
                db,
                workspace_id,
                node_id=node["id"],
                journey_id=journey_id,
                unit_id=unit_id,
                pane="TEACHING",
            )
            self.event(
                db,
                workspace_id,
                request.operation_id,
                "coverage.updated",
                {"node_id": node["id"], "progress": progress},
            )
            assessment_state = self.knowledge._atomic_assessment(
                db,
                workspace_id,
                node["id"],
            )
            return {
                **saved_unit,
                "id": unit_id,
                "journey_id": journey_id,
                "progress": progress,
                "assessment": assessment_state,
                "grade": assessment_state.get("grade_label")
                or assessment_state["status"],
                "evidence_ids": [e["id"] for e in evidence],
                "plan_version_id": plan_row["id"],
                "plan_version": plan_row["version"],
                "plan_unit_key": unit_plan.unit_key,
                "plan_reused": plan_reused,
            }

        return self.operate(workspace_id, owner, request, "unit", prepare, save)

    def return_bridge(
        self, workspace_id: str, owner: str, bridge_id: str, request: ReturnInput
    ) -> dict[str, Any]:
        def save(db: sqlite3.Connection, workspace: sqlite3.Row, _: Any) -> dict[str, Any]:
            row = db.execute(
                "SELECT * FROM learning_bridges WHERE id=? AND workspace_id=?",
                (bridge_id, workspace_id),
            ).fetchone()
            if row is None:
                raise ApiError(404, "BRIDGE_NOT_FOUND", "The bridge was not found.")
            result = json.loads(row["snapshot_json"])
            self.check_evidence(workspace, set(result["evidence_ids"]))
            db.execute(
                "UPDATE learning_bridges SET status=?,revision=revision+1 WHERE id=?",
                (request.status, bridge_id),
            )
            self.cursor(
                db,
                workspace_id,
                problem_id=result["source_problem_id"],
                solution_id=result["solution_id"],
                step_id=result["step_id"],
                pane="PROBLEM",
            )
            return {**result, "status": request.status}

        return self.operate(
            workspace_id,
            owner,
            request,
            "bridge.return",
            lambda w: None,
            save,
            resource_identity={"bridge_id": bridge_id},
        )

    def preferences(
        self, workspace_id: str, owner: str, request: PreferenceInput
    ) -> dict[str, Any]:
        def save(db: sqlite3.Connection, workspace: sqlite3.Row, _: Any) -> dict[str, Any]:
            db.execute(
                "UPDATE learning_workspaces SET mode=?,layout_json=? WHERE id=?",
                (request.mode, encode(request.layout.model_dump()), workspace_id),
            )
            return {"mode": request.mode, "layout": request.layout.model_dump()}

        return self.operate(workspace_id, owner, request, "preference", lambda w: None, save)

    def state(self, workspace_id: str, owner: str) -> dict[str, Any]:
        workspace = workspace_for(self.db, workspace_id, owner)
        knowledge = self.knowledge.snapshot(workspace_id, owner)
        nodes = [
            {
                "id": node["id"],
                "title": node["title"],
                "description": node["description"],
                "major": node["major"],
                "kind": node["kind"],
                "status": node["status"],
                "source": node["source"],
                "progress": node["state"]["learning"]["status"],
                "learning": node["state"]["learning"],
                "assessment": node["state"]["assessment"],
            }
            for node in knowledge["registry"]
        ]
        with self.db.connect() as db:
            solution_rows = db.execute(
                "SELECT s.id,s.content_json FROM learning_solutions s "
                "JOIN learning_problems p ON p.id=s.problem_id WHERE p.workspace_id=? "
                "ORDER BY s.rowid DESC LIMIT 25",
                (workspace_id,),
            ).fetchall()
            revision_by_solution = {
                row["solution_id"]: row
                for row in db.execute(
                    "SELECT revision.solution_id,revision.id AS solution_revision_id,"
                    "revision.revision AS solution_revision,problem_revision.* "
                    "FROM solution_revisions AS revision "
                    "JOIN problem_revisions AS problem_revision "
                    "ON problem_revision.id=revision.problem_revision_id "
                    "WHERE revision.workspace_id=? ORDER BY revision.revision",
                    (workspace_id,),
                )
            }
            links_by_step: dict[str, list[dict[str, Any]]] = {}
            for row in db.execute(
                "SELECT link.* FROM step_knowledge_links AS link "
                "JOIN learning_steps AS step ON step.id=link.step_id "
                "JOIN learning_solutions AS solution ON solution.id=step.solution_id "
                "JOIN learning_problems AS problem ON problem.id=solution.problem_id "
                "WHERE problem.workspace_id=? ORDER BY link.step_id,link.ordinal",
                (workspace_id,),
            ):
                links_by_step.setdefault(row["step_id"], []).append(
                    {
                        "id": row["id"],
                        "resolution_status": row["resolution_status"],
                        "node_id": row["node_id"],
                        "spec_version": row["spec_version"],
                        "item_id": row["item_id"],
                        "question_text": row["question_text"],
                        "reason": row["reason"],
                        "unresolved_reason": row["unresolved_reason"],
                    }
                )
            solutions = []
            for solution_row in solution_rows:
                solution = json.loads(solution_row["content_json"])
                for step in solution.get("steps", []):
                    step.setdefault("formulae", [])
                    step.setdefault("units", [])
                    step.setdefault("check", None)
                    step.setdefault("source_refs", [])
                    if step.get("id") in links_by_step:
                        step["knowledge_links"] = links_by_step[step["id"]]
                revision = revision_by_solution.get(solution_row["id"])
                if revision is not None:
                    solution.update(
                        problem_revision=int(revision["revision"]),
                        problem_revision_id=revision["id"],
                        solution_revision=int(revision["solution_revision"]),
                        solution_revision_id=revision["solution_revision_id"],
                        input_kind=revision["input_kind"],
                        problem_index_entry_id=revision["problem_index_entry_id"],
                        input_document_version_id=revision["input_document_version_id"],
                    )
                    solution.setdefault(
                        "question_transcription", revision["question_transcription"]
                    )
                    solution.setdefault(
                        "visual_uncertainties",
                        json.loads(revision["visual_uncertainties_json"]),
                    )
                solution.setdefault("conditions", [])
                solution.setdefault("common_mistakes", [])
                solution.setdefault("question_transcription", None)
                solution.setdefault("visual_uncertainties", [])
                solution.setdefault("verification", "NOT_INDEPENDENTLY_VERIFIED")
                solution.setdefault("sources", [])
                solutions.append(solution)
            bridges = [
                {**json.loads(r["snapshot_json"]), "status": r["status"]}
                for r in db.execute(
                    "SELECT * FROM learning_bridges WHERE workspace_id=? ORDER BY rowid DESC "
                    "LIMIT 50",
                    (workspace_id,),
                )
            ]
            units = [
                {
                    **json.loads(r["content_json"]),
                    "id": r["id"],
                    "journey_id": r["journey_id"],
                    "evidence_ids": json.loads(r["provenance_json"])["evidence_ids"],
                }
                for r in db.execute(
                    "SELECT u.* FROM teaching_units u JOIN learning_journeys j ON "
                    "j.id=u.journey_id "
                    "WHERE j.workspace_id=? ORDER BY u.rowid DESC LIMIT 25",
                    (workspace_id,),
                )
            ]
            operations = [
                dict(r)
                for r in db.execute(
                    "SELECT id,kind,status FROM learning_operations WHERE workspace_id=? ORDER "
                    "BY rowid DESC LIMIT 25",
                    (workspace_id,),
                )
            ]

        def safe(artifact: dict[str, Any]) -> dict[str, Any]:
            try:
                self.check_evidence(workspace, set(artifact.get("evidence_ids", [])))
                if artifact.get("input_kind") == "IMAGE":
                    version_id = artifact.get("input_document_version_id")
                    if not isinstance(version_id, str):
                        raise ApiError(
                            410, "SOURCE_UNAVAILABLE", "The image source is unavailable."
                        )
                    version = document_version_for(self.db, version_id, owner)
                    if original_path(self.db, version) is None:
                        raise ApiError(
                            410, "SOURCE_UNAVAILABLE", "The image source is unavailable."
                        )
                return artifact
            except ApiError:
                return {"id": artifact["id"], "status": "SOURCE_UNAVAILABLE"}

        return {
            "id": workspace_id,
            "course_id": workspace["course_id"],
            "revision": workspace["revision"],
            "mode": workspace["mode"],
            "layout": json.loads(workspace["layout_json"]),
            "cursor": json.loads(workspace["cursor_json"]),
            "nodes": nodes,
            "solutions": [safe(s) for s in solutions],
            "bridges": [safe(b) for b in bridges],
            "units": [safe(u) for u in units],
            "operations": operations,
        }
