"""M6D1: turn the real official corpus into a reviewable OFFICIAL DRAFT tree.

The builder connects the pieces the platform already has, in the order a human
reviewer can audit:

    official corpus (document versions + chunks)
        -> controlled admin learning workspace
        -> bounded model drafts through LearningOrchestrator (reservations +
           run evidence, never a second provider client)
        -> strict official-evidence validation
        -> one short canonicalization transaction
        -> OFFICIAL + DRAFT tree version (never PUBLISHED)

The builder never submits a publication request and never approves one: the
existing independent-review gate stays the only path from DRAFT to live content.
"""

import hashlib
import json
import sqlite3
from typing import Any
from uuid import uuid4

from app.config import Settings
from app.db import Database
from app.errors import ApiError
from app.learning.knowledge import KnowledgeService
from app.learning.models import (
    OfficialKnowledgeDraftBundleOutput,
    OfficialNodeDraftOutput,
    OfficialTeachingSpecDraftOutput,
    TreeMembershipInput,
)
from app.learning.orchestrator import LearningOrchestrator
from app.learning.workspaces import join_course, workspace_for
from app.models import (
    OfficialKnowledgeDraftBudget,
    OfficialKnowledgeDraftCorpus,
    OfficialKnowledgeDraftGenerate,
    OfficialKnowledgeDraftGeneration,
)

BUILDER_VERSION = "M6D1_V1"
MAX_OFFICIAL_DRAFT_NODES = 10
MAX_OFFICIAL_DRAFT_MODEL_CALLS = 20
MAX_OFFICIAL_DRAFT_RESERVED_OUTPUT_TOKENS = 20_000
RETRIEVAL_TOP_K = 3


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def corpus_fingerprint(
    course_id: str,
    versions: list[sqlite3.Row],
    *,
    builder_version: str,
    config: dict[str, object],
) -> str:
    """Stable fingerprint over the current OFFICIAL corpus + builder identity.

    No timestamps or random values: identical corpus + config always hashes to
    the same fingerprint, which is what makes generation idempotent.
    """

    return content_hash(
        {
            "builder_version": builder_version,
            "course_id": course_id,
            "config": config,
            "documents": [
                {
                    "version_id": str(row["id"]),
                    "version": int(row["version"]),
                    "sha256": row["sha256"],
                    "status": row["status"],
                }
                for row in versions
            ],
        }
    )


class OfficialKnowledgeDraftBuilder:
    """Builds one auditable OFFICIAL DRAFT per corpus+config fingerprint."""

    def __init__(
        self,
        database: Database,
        settings: Settings,
        learning: LearningOrchestrator,
    ) -> None:
        self.database = database
        self.settings = settings
        self.learning = learning

    # ------------------------------------------------------------------ corpus

    def _course(self, course_id: str) -> sqlite3.Row:
        with self.database.connect() as connection:
            course = connection.execute(
                "SELECT * FROM courses WHERE id=?", (course_id,)
            ).fetchone()
        if course is None:
            raise ApiError(404, "COURSE_NOT_FOUND", "The course was not found.")
        if course["course_type"] != "official":
            raise ApiError(
                409,
                "OFFICIAL_COURSE_REQUIRED",
                "Official knowledge drafts require an official course corpus.",
            )
        return course

    def _official_versions(
        self, connection: sqlite3.Connection, course_id: str
    ) -> list[sqlite3.Row]:
        versions = connection.execute(
            "SELECT version.id,version.document_id,version.version,version.sha256,"
            "version.filename,version.source_scope,documents.status "
            "FROM document_versions AS version "
            "JOIN documents ON documents.id=version.document_id "
            "WHERE version.course_id=? AND version.source_scope='OFFICIAL' "
            "AND version.version=(SELECT MAX(current.version) FROM document_versions "
            "AS current WHERE current.document_id=version.document_id) "
            "ORDER BY version.id",
            (course_id,),
        ).fetchall()
        if not versions:
            raise ApiError(
                409,
                "OFFICIAL_CORPUS_EMPTY",
                "The official corpus has no indexed document versions to build from.",
            )
        return versions

    def _chunk_count(
        self, connection: sqlite3.Connection, version_ids: list[str]
    ) -> int:
        placeholders = ",".join("?" for _ in version_ids)
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM chunks JOIN chunk_source_versions "
                "ON chunk_source_versions.chunk_id=chunks.id "
                f"WHERE chunk_source_versions.document_version_id IN ({placeholders})",
                version_ids,
            ).fetchone()[0]
        )

    def _fingerprint(
        self,
        course_id: str,
        versions: list[sqlite3.Row],
        payload: OfficialKnowledgeDraftGenerate,
    ) -> str:
        return corpus_fingerprint(
            course_id,
            versions,
            builder_version=BUILDER_VERSION,
            config={
                "max_nodes": payload.max_nodes,
                "max_model_calls": payload.max_model_calls,
                "max_reserved_output_tokens": payload.max_reserved_output_tokens,
            },
        )

    def _existing_draft(
        self, connection: sqlite3.Connection, course_id: str, fingerprint: str
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT id,version FROM knowledge_tree_versions "
            "WHERE course_id=? AND tree_kind='OFFICIAL' AND status='DRAFT' "
            "AND corpus_fingerprint=? ORDER BY version DESC LIMIT 1",
            (course_id, fingerprint),
        ).fetchone()

    # ---------------------------------------------------------------- evidence

    def official_evidence(
        self,
        workspace: sqlite3.Row,
        course: sqlite3.Row,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve official-course chunks and re-verify every binding.

        Only chunk ids whose document version belongs to THIS official course
        with source_scope='OFFICIAL' survive. Private workspace files and other
        courses are rejected before the provider ever sees them.
        """

        retrieved = self.learning.evidence(
            workspace, query or f"{course['name']} knowledge structure", scope="official"
        )
        verified: list[dict[str, Any]] = []
        with self.database.connect() as connection:
            for entry in retrieved:
                row = connection.execute(
                    "SELECT course_id,source_scope FROM document_versions WHERE id=?",
                    (entry.get("document_version_id"),),
                ).fetchone()
                if (
                    row is None
                    or row["course_id"] != course["id"]
                    or row["source_scope"] != "OFFICIAL"
                ):
                    continue
                if not entry.get("locator_type") or not entry.get("locator_value"):
                    continue
                if not entry.get("id"):
                    continue
                verified.append(entry)
        return verified

    @staticmethod
    def validate_outputs(
        node: OfficialNodeDraftOutput,
        spec: OfficialTeachingSpecDraftOutput,
        official_evidence: list[dict[str, Any]],
    ) -> set[str]:
        evidence_ids = {str(entry["id"]) for entry in official_evidence}
        node_ids = {item.item_id for item in node.items}
        spec_ids = {item.item_id for item in spec.items}
        if spec_ids != node_ids:
            raise ApiError(
                422,
                "OFFICIAL_DRAFT_INVALID",
                "The Teaching Spec draft must match the node draft item scope.",
            )
        cited: set[str] = set()
        for item in spec.items:
            if item.requirement == "REQUIRED" and not item.evidence_ids:
                raise ApiError(
                    422,
                    "OFFICIAL_DRAFT_EVIDENCE_REQUIRED",
                    "Every REQUIRED official item must cite official corpus evidence.",
                )
            for evidence_id in item.evidence_ids:
                if evidence_id not in evidence_ids:
                    raise ApiError(
                        422,
                        "OFFICIAL_DRAFT_EVIDENCE_REQUIRED",
                        "An item cites evidence outside the verified official corpus.",
                    )
                cited.add(evidence_id)
        return cited

    # ---------------------------------------------------------------- generation

    def _guard_call(
        self,
        calls_made: int,
        max_model_calls: int,
        max_reserved_output_tokens: int,
    ) -> None:
        per_call = self.settings.v3_max_output_tokens
        if calls_made + 1 > max_model_calls:
            raise ApiError(
                429,
                "OFFICIAL_DRAFT_BUDGET_EXCEEDED",
                "The requested model-call budget has been reached; no provider call was made.",
            )
        if (calls_made + 1) * per_call > max_reserved_output_tokens:
            raise ApiError(
                429,
                "OFFICIAL_DRAFT_BUDGET_EXCEEDED",
                "The reserved-output-token ceiling would be exceeded; no provider call was made.",
            )

    def plan_calls(
        self, max_model_calls: int, max_reserved_output_tokens: int
    ) -> int:
        per_call = self.settings.v3_max_output_tokens
        planned = min(max_model_calls, 2)
        if planned * per_call > max_reserved_output_tokens:
            planned = max_reserved_output_tokens // per_call
        return planned

    def generate_drafts(
        self,
        *,
        workspace: sqlite3.Row,
        course: sqlite3.Row,
        official_evidence: list[dict[str, Any]],
        operation_id: str,
        max_model_calls: int,
        max_reserved_output_tokens: int,
        planned_calls: int,
        max_nodes: int = 1,
        topic: str | None = None,
        node_key: str | None = None,
    ) -> tuple[OfficialNodeDraftOutput, OfficialTeachingSpecDraftOutput, int]:
        context = {
            "course_id": course["id"],
            "course_name": course["name"],
            "max_nodes": max_nodes,
            "topic": topic or "",
            "node_key": node_key or "",
            "evidence": [
                {
                    "id": entry["id"],
                    "document_id": entry["document_id"],
                    "document_version_id": entry["document_version_id"],
                    "locator_type": entry["locator_type"],
                    "locator_value": entry["locator_value"],
                    "content": entry["content"][:2500],
                }
                for entry in official_evidence
            ],
        }
        calls_made = 0
        workspace_id = str(workspace["id"])

        def run_operation(
            operation: str,
            kind: str,
            schema: type,
            instructions: str,
            role: str,
            call_context: dict[str, Any],
        ) -> Any:
            with self.database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT status FROM learning_operations WHERE workspace_id=? AND id=?",
                    (workspace_id, operation),
                ).fetchone()
                if existing is None:
                    connection.execute(
                        "INSERT INTO learning_operations("
                        "workspace_id,id,request_hash,kind,status) VALUES(?,?,?,?,'RUNNING')",
                        (
                            workspace_id,
                            operation,
                            content_hash({"operation": operation, "kind": kind}),
                            kind,
                        ),
                    )
                else:
                    # Resume/retry of the same logical operation re-opens it.
                    connection.execute(
                        "UPDATE learning_operations SET status='RUNNING' "
                        "WHERE workspace_id=? AND id=?",
                        (workspace_id, operation),
                    )
            try:
                output, _run = self.learning.generate(
                    workspace_id,
                    operation,
                    schema,
                    instructions=instructions,
                    context=call_context,
                    role=role,
                    template_version=BUILDER_VERSION,
                    schema_version=BUILDER_VERSION,
                )
            except Exception as error:
                status = (
                    "FAILED"
                    if isinstance(error, (ApiError, ValueError))
                    else "UNKNOWN"
                )
                with self.database.connect() as connection:
                    connection.execute(
                        "UPDATE learning_operations SET status=? "
                        "WHERE workspace_id=? AND id=?",
                        (status, workspace_id, operation),
                    )
                raise
            with self.database.connect() as connection:
                connection.execute(
                    "UPDATE learning_operations SET status='COMPLETED' "
                    "WHERE workspace_id=? AND id=?",
                    (workspace_id, operation),
                )
            return output

        topic_instruction = (
            f" The node topic scope is: {topic}."
            if topic
            else ""
        )
        if planned_calls == 1:
            self._guard_call(calls_made, max_model_calls, max_reserved_output_tokens)
            bundle = run_operation(
                f"{operation_id}-bundle",
                "official.draft.bundle",
                OfficialKnowledgeDraftBundleOutput,
                (
                    "Build ONE bounded ATOMIC knowledge node for the official course "
                    "grounded ONLY in the supplied official corpus evidence, plus its "
                    "validated Teaching Spec. Never invent facts outside the evidence."
                    + topic_instruction
                ),
                "teacher",
                context,
            )
            calls_made += 1
            return bundle.node, bundle.spec, calls_made
        self._guard_call(calls_made, max_model_calls, max_reserved_output_tokens)
        node = run_operation(
            f"{operation_id}-node",
            "official.draft.node",
            OfficialNodeDraftOutput,
            (
                "Draft ONE bounded ATOMIC knowledge node for the official course, "
                "grounded ONLY in the supplied official corpus evidence. Every item "
                "cites chunk ids from that evidence."
                + topic_instruction
            ),
            "teacher",
            context,
        )
        calls_made += 1
        self._guard_call(calls_made, max_model_calls, max_reserved_output_tokens)
        spec = run_operation(
            f"{operation_id}-spec",
            "official.draft.spec",
            OfficialTeachingSpecDraftOutput,
            (
                "Produce the validated Teaching Spec for the drafted official node: "
                "same item ids, each REQUIRED item grounded in the supplied official "
                "corpus evidence."
            ),
            "teacher",
            {**context, "node_draft": node.model_dump()},
        )
        calls_made += 1
        return node, spec, calls_made

    # ------------------------------------------------------------ canonicalize

    @staticmethod
    def _content_node_id(course: sqlite3.Row, node: OfficialNodeDraftOutput, spec: OfficialTeachingSpecDraftOutput) -> str:
        node_identity = content_hash(
            {
                "course_id": course["id"],
                "title": node.title,
                "major": node.major,
                "kind": node.kind,
                "items": [item.model_dump() for item in spec.items],
            }
        )
        return "official-node-" + node_identity[:24]

    def _canonicalize_node_tx(
        self,
        connection: sqlite3.Connection,
        *,
        course: sqlite3.Row,
        node_id: str,
        node: OfficialNodeDraftOutput,
        spec: OfficialTeachingSpecDraftOutput,
        cited_evidence: set[str],
        official_evidence: list[dict[str, Any]],
        fingerprint: str,
        admin_user_id: str,
        fingerprint_payload: OfficialKnowledgeDraftGenerate,
        fingerprint_builder_version: str = BUILDER_VERSION,
        fingerprint_config: dict[str, object] | None = None,
    ) -> list[str]:
        """Node + exact Spec + OFFICIAL evidence writes (no tree). Caller owns
        the transaction and has already verified the corpus fingerprint."""

        current_versions = self._official_versions(connection, course["id"])
        config = fingerprint_config if fingerprint_config is not None else {
            "max_nodes": fingerprint_payload.max_nodes,
            "max_model_calls": fingerprint_payload.max_model_calls,
            "max_reserved_output_tokens": fingerprint_payload.max_reserved_output_tokens,
        }
        if (
            corpus_fingerprint(
                course["id"],
                current_versions,
                builder_version=fingerprint_builder_version,
                config=config,
            )
            != fingerprint
        ):
            raise ApiError(
                409,
                "OFFICIAL_CORPUS_CHANGED",
                "The official corpus changed during generation; nothing was written.",
            )
        node_row = connection.execute(
            "SELECT * FROM knowledge_nodes WHERE id=?", (node_id,)
        ).fetchone()
        if node_row is None:
            connection.execute(
                "INSERT INTO knowledge_nodes("
                "id,course_id,owner_user_id,title,description,major,kind,status) "
                "VALUES(?,?,NULL,?,?,?,?,'CANDIDATE')",
                (
                    node_id,
                    course["id"],
                    node.title,
                    node.description,
                    node.major,
                    node.kind,
                ),
            )
        else:
            if (
                node_row["course_id"] != course["id"]
                or node_row["owner_user_id"] is not None
                or node_row["status"] not in {"CANDIDATE", "PUBLISHED"}
                or node_row["title"] != node.title
                or node_row["description"] != node.description
                or node_row["major"] != node.major
                or node_row["kind"] != node.kind
            ):
                raise ApiError(
                    409,
                    "CANONICAL_NODE_CONFLICT",
                    "An existing canonical node id collides with different content.",
                )
        spec_content = canonical_json([item.model_dump() for item in spec.items])
        spec_hash = hashlib.sha256(spec_content.encode("utf-8")).hexdigest()
        spec_row = connection.execute(
            "SELECT content_hash FROM teaching_specs WHERE node_id=? AND version=1",
            (node_id,),
        ).fetchone()
        if spec_row is None:
            connection.execute(
                "INSERT INTO teaching_specs(node_id,version,content_json,content_hash) "
                "VALUES(?,1,?,?)",
                (node_id, spec_content, spec_hash),
            )
        elif spec_row["content_hash"] != spec_hash:
            raise ApiError(
                409,
                "CANONICAL_NODE_CONFLICT",
                "The canonical node's Teaching Spec no longer matches its identity.",
            )
        connection.execute(
            "UPDATE teaching_spec_metadata SET created_by_user_id=?,change_reason=? "
            "WHERE node_id=? AND version=1",
            (admin_user_id, spec.change_reason[:2000], node_id),
        )

        evidence_rows: list[str] = []
        by_id = {str(entry["id"]): entry for entry in official_evidence}
        for evidence_id in sorted(cited_evidence):
            entry = by_id[evidence_id]
            evidence_row_id = "official-evidence-" + uuid4().hex
            connection.execute(
                "INSERT OR IGNORE INTO material_evidence("
                "id,node_id,document_version_id,chunk_id,owner_user_id,"
                "source_scope,locator_type,locator_value,status) "
                "VALUES(?,?,?,?,NULL,'OFFICIAL',?,?,'ACTIVE')",
                (
                    evidence_row_id,
                    node_id,
                    entry["document_version_id"],
                    entry["id"],
                    entry["locator_type"],
                    entry["locator_value"],
                ),
            )
            evidence_rows.append(evidence_row_id)
        return evidence_rows

    def canonicalize_node(
        self,
        *,
        course: sqlite3.Row,
        node_id: str,
        node: OfficialNodeDraftOutput,
        spec: OfficialTeachingSpecDraftOutput,
        cited_evidence: set[str],
        official_evidence: list[dict[str, Any]],
        fingerprint: str,
        admin_user_id: str,
        fingerprint_payload: OfficialKnowledgeDraftGenerate,
        fingerprint_builder_version: str = BUILDER_VERSION,
        fingerprint_config: dict[str, object] | None = None,
    ) -> list[str]:
        """Node-only canonicalization for the bulk course builder (no tree)."""

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._canonicalize_node_tx(
                connection,
                course=course,
                node_id=node_id,
                node=node,
                spec=spec,
                cited_evidence=cited_evidence,
                official_evidence=official_evidence,
                fingerprint=fingerprint,
                admin_user_id=admin_user_id,
                fingerprint_payload=fingerprint_payload,
                fingerprint_builder_version=fingerprint_builder_version,
                fingerprint_config=fingerprint_config,
            )

    def _canonicalize(
        self,
        *,
        course: sqlite3.Row,
        node: OfficialNodeDraftOutput,
        spec: OfficialTeachingSpecDraftOutput,
        cited_evidence: set[str],
        official_evidence: list[dict[str, Any]],
        fingerprint: str,
        payload: OfficialKnowledgeDraftGenerate,
        admin_user_id: str,
    ) -> tuple[str, int, list[str], list[str]]:
        node_id = self._content_node_id(course, node, spec)
        tree_title = f"{course['name']} official knowledge draft"[:200].strip()
        change_reason = (
            f"AI-assisted official draft from verified corpus; "
            f"operation {payload.operation_id}; builder {BUILDER_VERSION}"
        )[:500]

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._existing_draft(connection, course["id"], fingerprint)
            if existing is not None:
                members = [
                    str(row["node_id"])
                    for row in connection.execute(
                        "SELECT node_id FROM knowledge_tree_memberships "
                        "WHERE tree_version_id=? ORDER BY ordinal,node_id",
                        (existing["id"],),
                    )
                ]
                return str(existing["id"]), int(existing["version"]), members, []
            evidence_rows = self._canonicalize_node_tx(
                connection,
                course=course,
                node_id=node_id,
                node=node,
                spec=spec,
                cited_evidence=cited_evidence,
                official_evidence=official_evidence,
                fingerprint=fingerprint,
                admin_user_id=admin_user_id,
                fingerprint_payload=payload,
            )

            node_row = connection.execute(
                "SELECT * FROM knowledge_nodes WHERE id=?", (node_id,)
            ).fetchone()
            assert node_row is not None
            memberships = [
                TreeMembershipInput(node_id=node_id, parent_node_id=None, ordinal=0, spec_version=1)
            ]
            # Reuse the project's existing graph validation: cycles, orphans,
            # atomic parents and prerequisite completeness are rejected here.
            KnowledgeService._validate_graph({node_id: node_row}, memberships, set())  # noqa: SLF001

            version = int(
                connection.execute(
                    "SELECT COALESCE(MAX(version),0)+1 FROM knowledge_tree_versions "
                    "WHERE course_id=? AND tree_kind='OFFICIAL'",
                    (course["id"],),
                ).fetchone()[0]
            )
            tree_id = "official-tree-" + uuid4().hex
            tree_content = {
                "title": tree_title,
                "corpus_fingerprint": fingerprint,
                "members": [
                    {
                        "node_id": node_id,
                        "parent_node_id": None,
                        "ordinal": 0,
                        "teaching_spec_version": 1,
                    }
                ],
                "prerequisites": [],
            }
            connection.execute(
                "INSERT INTO knowledge_tree_versions("
                "id,course_id,workspace_id,owner_user_id,tree_kind,version,status,"
                "title,change_reason,content_hash,corpus_fingerprint) "
                "VALUES(?,?,NULL,NULL,'OFFICIAL',?,'DRAFT',?,?,?,?)",
                (
                    tree_id,
                    course["id"],
                    version,
                    tree_title,
                    change_reason,
                    content_hash(tree_content),
                    fingerprint,
                ),
            )
            connection.execute(
                "INSERT INTO knowledge_tree_memberships("
                "tree_version_id,node_id,parent_node_id,ordinal,teaching_spec_version) "
                "VALUES(?,?,NULL,0,1)",
                (tree_id, node_id),
            )
            return tree_id, version, [node_id], evidence_rows

    # ------------------------------------------------------------------- entry

    def generate(
        self,
        course_id: str,
        payload: OfficialKnowledgeDraftGenerate,
        *,
        admin_user_id: str,
    ) -> OfficialKnowledgeDraftGeneration:
        if payload.max_nodes > MAX_OFFICIAL_DRAFT_NODES:
            raise ApiError(422, "OFFICIAL_DRAFT_LIMIT", "maxNodes exceeds the hard ceiling.")
        if payload.max_model_calls > MAX_OFFICIAL_DRAFT_MODEL_CALLS:
            raise ApiError(422, "OFFICIAL_DRAFT_LIMIT", "maxModelCalls exceeds the hard ceiling.")
        if payload.max_reserved_output_tokens > MAX_OFFICIAL_DRAFT_RESERVED_OUTPUT_TOKENS:
            raise ApiError(
                422, "OFFICIAL_DRAFT_LIMIT", "maxReservedOutputTokens exceeds the hard ceiling."
            )
        course = self._course(course_id)
        with self.database.connect() as connection:
            versions = self._official_versions(connection, course_id)
            chunk_count = self._chunk_count(
                connection, [str(row["id"]) for row in versions]
            )
            fingerprint = self._fingerprint(course_id, versions, payload)
            existing = self._existing_draft(connection, course_id, fingerprint)

        per_call = self.settings.v3_max_output_tokens
        planned_calls = self.plan_calls(
            payload.max_model_calls, payload.max_reserved_output_tokens
        )
        planned_reserved = planned_calls * per_call
        budget = OfficialKnowledgeDraftBudget(
            max_nodes=payload.max_nodes,
            max_model_calls=payload.max_model_calls,
            max_reserved_output_tokens=payload.max_reserved_output_tokens,
            planned_model_calls=planned_calls,
            planned_reserved_output_tokens=planned_reserved,
            model_calls_made=0,
            reserved_output_tokens_booked=0,
        )
        corpus = OfficialKnowledgeDraftCorpus(
            document_count=len(versions),
            chunk_count=chunk_count,
            version_count=len(versions),
        )
        if payload.dry_run:
            existing_nodes: list[str] = []
            if existing is not None:
                with self.database.connect() as connection:
                    existing_nodes = [
                        str(row["node_id"])
                        for row in connection.execute(
                            "SELECT node_id FROM knowledge_tree_memberships "
                            "WHERE tree_version_id=? ORDER BY ordinal,node_id",
                            (existing["id"],),
                        )
                    ]
            return OfficialKnowledgeDraftGeneration(
                course_id=course_id,
                operation_id=payload.operation_id,
                dry_run=True,
                existing_draft=existing is not None,
                tree_version_id=str(existing["id"]) if existing is not None else None,
                tree_version=int(existing["version"]) if existing is not None else None,
                node_ids=existing_nodes,
                corpus_fingerprint=fingerprint,
                corpus=corpus,
                budget=budget,
            )

        if planned_calls == 0:
            raise ApiError(
                429,
                "OFFICIAL_DRAFT_BUDGET_EXCEEDED",
                "The reserved-output-token ceiling cannot cover one model call.",
            )
        if existing is not None:
            with self.database.connect() as connection:
                members = [
                    str(row["node_id"])
                    for row in connection.execute(
                        "SELECT node_id FROM knowledge_tree_memberships "
                        "WHERE tree_version_id=? ORDER BY ordinal,node_id",
                        (existing["id"],),
                    )
                ]
            return OfficialKnowledgeDraftGeneration(
                course_id=course_id,
                operation_id=payload.operation_id,
                dry_run=False,
                existing_draft=True,
                tree_version_id=str(existing["id"]),
                tree_version=int(existing["version"]),
                node_ids=members,
                corpus_fingerprint=fingerprint,
                corpus=corpus,
                budget=budget,
            )

        join_course(self.database, course_id, admin_user_id, self.settings.user_course_max_courses)
        workspace = workspace_for(
            self.database, self._admin_workspace_id(course_id, admin_user_id), admin_user_id
        )
        official_evidence = self.official_evidence(workspace, course)
        if not official_evidence:
            raise ApiError(
                422,
                "OFFICIAL_DRAFT_EVIDENCE_UNAVAILABLE",
                "No official corpus chunks could be retrieved for this course.",
            )
        node, spec, calls_made = self.generate_drafts(
            workspace=workspace,
            course=course,
            official_evidence=official_evidence,
            operation_id=payload.operation_id,
            max_model_calls=payload.max_model_calls,
            max_reserved_output_tokens=payload.max_reserved_output_tokens,
            planned_calls=planned_calls,
            max_nodes=payload.max_nodes,
        )
        cited = self.validate_outputs(node, spec, official_evidence)
        tree_id, tree_version, node_ids, evidence_rows = self._canonicalize(
            course=course,
            node=node,
            spec=spec,
            cited_evidence=cited,
            official_evidence=official_evidence,
            fingerprint=fingerprint,
            payload=payload,
            admin_user_id=admin_user_id,
        )
        budget.model_calls_made = calls_made
        budget.reserved_output_tokens_booked = calls_made * per_call
        return OfficialKnowledgeDraftGeneration(
            course_id=course_id,
            operation_id=payload.operation_id,
            dry_run=False,
            existing_draft=False,
            tree_version_id=tree_id,
            tree_version=tree_version,
            node_ids=node_ids,
            corpus_fingerprint=fingerprint,
            corpus=corpus,
            budget=budget,
            evidence_chunk_count=len(official_evidence),
            evidence_rows=evidence_rows,
        )

    def _admin_workspace_id(self, course_id: str, admin_user_id: str) -> str:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id FROM learning_workspaces WHERE course_id=? AND owner_user_id=?",
                (course_id, admin_user_id),
            ).fetchone()
        if row is None:
            raise ApiError(404, "WORKSPACE_NOT_FOUND", "The admin workspace was not found.")
        return str(row["id"])
