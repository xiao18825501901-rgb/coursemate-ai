"""M6D4: bulk, resumable official knowledge generation for one whole course.

The M6D1 builder produces ONE atomic node and ONE single-node DRAFT tree per
operation. A full course needs many nodes accumulated across batches and then
frozen into ONE final OFFICIAL DRAFT tree. This coordinator owns exactly that:

    plan (corpus-derived modules + atomic targets)
        -> per-node bounded generation through OfficialKnowledgeDraftBuilder
           (evidence validation, budget guards, reservations ledger)
        -> node-only canonicalization (no tree per batch)
        -> one short transaction: composite modules + memberships +
           prerequisites + ONE OFFICIAL DRAFT tree version
        -> plan row status FINALIZED (resumable, idempotent)

It never submits or approves publication. Composite nodes are created
deterministically from the plan (which is derived from the real corpus source
map), never from model output.
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
from app.learning.models import TreeMembershipInput
from app.learning.orchestrator import LearningOrchestrator
from app.learning.workspaces import join_course, workspace_for
from app.models import (
    OfficialKnowledgeCourseBuild,
    OfficialKnowledgeCourseBuildResult,
    OfficialKnowledgeCourseProgress,
    OfficialKnowledgeDraftGenerate,
)
from app.services.official_knowledge_draft_builder import (
    OfficialKnowledgeDraftBuilder,
    canonical_json,
    content_hash,
    corpus_fingerprint,
)

COURSE_BUILDER_VERSION = "M6D4_COURSE_V1"
MAX_COURSE_NODES = 60


class OfficialKnowledgeCourseBuilder:
    """Accumulates bounded node batches into one final OFFICIAL DRAFT tree."""

    def __init__(
        self,
        database: Database,
        settings: Settings,
        learning: LearningOrchestrator,
        node_builder: OfficialKnowledgeDraftBuilder,
    ) -> None:
        self.database = database
        self.settings = settings
        self.learning = learning
        self.node_builder = node_builder

    # ------------------------------------------------------------- identities

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
                "Official knowledge generation requires an official course corpus.",
            )
        return course

    def _plan_hash(self, payload: OfficialKnowledgeCourseBuild) -> str:
        return content_hash(payload.plan.model_dump())

    def _corpus_fingerprint(
        self, course_id: str, plan_hash: str, payload: OfficialKnowledgeCourseBuild
    ) -> str:
        with self.database.connect() as connection:
            versions = self.node_builder._official_versions(connection, course_id)  # noqa: SLF001
        return corpus_fingerprint(
            course_id,
            versions,
            builder_version=COURSE_BUILDER_VERSION,
            config={
                "plan_hash": plan_hash,
                "max_model_calls_per_batch": payload.max_model_calls_per_batch,
                "max_reserved_output_tokens_per_batch": payload.max_reserved_output_tokens_per_batch,
            },
        )

    @staticmethod
    def _plan_id(course_id: str, plan_hash: str, key: str) -> str:
        digest = content_hash([course_id, plan_hash, key])[:24]
        return f"official-node-{digest}"

    @staticmethod
    def _module_id(course_id: str, plan_hash: str, key: str) -> str:
        digest = content_hash([course_id, plan_hash, key])[:24]
        return f"official-module-{digest}"

    # ------------------------------------------------------------ plan ledger

    def _plan_row(self, connection: sqlite3.Connection, course_id: str) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM official_knowledge_generation_plans WHERE course_id=? "
            "AND status IN ('GENERATING','FINALIZED') ORDER BY updated_at DESC LIMIT 1",
            (course_id,),
        ).fetchone()

    def _upsert_plan(
        self,
        connection: sqlite3.Connection,
        *,
        course_id: str,
        plan_hash: str,
        plan_json: str,
        corpus_fingerprint: str,
    ) -> sqlite3.Row:
        row = self._plan_row(connection, course_id)
        if row is not None and row["plan_hash"] == plan_hash and row["status"] == "GENERATING":
            return row
        if row is not None and row["plan_hash"] != plan_hash:
            connection.execute(
                "UPDATE official_knowledge_generation_plans SET status='SUPERSEDED' "
                "WHERE course_id=? AND status IN ('GENERATING','FINALIZED')",
                (course_id,),
            )
            row = None
        if row is None:
            plan_id = "plan-" + uuid4().hex
            connection.execute(
                "INSERT INTO official_knowledge_generation_plans("
                "id,course_id,plan_hash,plan_json,builder_version,corpus_fingerprint,status) "
                "VALUES(?,?,?,?,?,?,'GENERATING')",
                (
                    plan_id,
                    course_id,
                    plan_hash,
                    plan_json,
                    COURSE_BUILDER_VERSION,
                    corpus_fingerprint,
                ),
            )
            row = connection.execute(
                "SELECT * FROM official_knowledge_generation_plans WHERE id=?", (plan_id,)
            ).fetchone()
        return row

    def _persist_progress(
        self,
        connection: sqlite3.Connection,
        plan_row: sqlite3.Row,
        progress: dict[str, str],
    ) -> None:
        connection.execute(
            "UPDATE official_knowledge_generation_plans SET "
            "progress_json=?,node_count=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE id=?",
            (canonical_json(progress), len(progress), plan_row["id"]),
        )

    # ------------------------------------------------------------- finalize

    def _finalize(
        self,
        *,
        course: sqlite3.Row,
        payload: OfficialKnowledgeCourseBuild,
        admin_user_id: str,
        plan_row: sqlite3.Row,
        plan_hash: str,
        corpus_fp: str,
        progress: dict[str, str],
    ) -> tuple[str, int]:
        plan = payload.plan
        module_ids = {m.module_key: self._module_id(course["id"], plan_hash, m.module_key) for m in plan.modules}
        node_ids = {n.node_key: self._plan_id(course["id"], plan_hash, n.node_key) for n in plan.nodes}
        key_to_id = {**module_ids, **node_ids}

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            fresh = self._plan_row(connection, course["id"])
            if fresh is not None and fresh["status"] == "FINALIZED" and fresh["plan_hash"] == plan_hash:
                return str(fresh["final_tree_version_id"]), int(
                    connection.execute(
                        "SELECT version FROM knowledge_tree_versions WHERE id=?",
                        (fresh["final_tree_version_id"],),
                    ).fetchone()["version"]
                )

            # All atomic targets must be canonicalized already.
            missing = [k for k in node_ids if k not in progress]
            if missing:
                raise ApiError(
                    409,
                    "OFFICIAL_COURSE_INCOMPLETE",
                    "Some plan nodes were not generated; resume the build first.",
                    details={"missingNodes": missing},
                )
            nodes: dict[str, sqlite3.Row] = {}
            for module in plan.modules:
                module_id = module_ids[module.module_key]
                row = connection.execute(
                    "SELECT * FROM knowledge_nodes WHERE id=?", (module_id,)
                ).fetchone()
                if row is None:
                    connection.execute(
                        "INSERT INTO knowledge_nodes("
                        "id,course_id,owner_user_id,title,description,major,kind,status) "
                        "VALUES(?,?,NULL,?,?,?,'COMPOSITE','CANDIDATE')",
                        (
                            module_id,
                            course["id"],
                            module.title,
                            module.description,
                            module.major,
                        ),
                    )
                    row = connection.execute(
                        "SELECT * FROM knowledge_nodes WHERE id=?", (module_id,)
                    ).fetchone()
                elif (
                    row["course_id"] != course["id"]
                    or row["owner_user_id"] is not None
                    or row["status"] not in {"CANDIDATE", "PUBLISHED"}
                    or row["kind"] != "COMPOSITE"
                ):
                    raise ApiError(409, "CANONICAL_NODE_CONFLICT", "A plan module id collides with different content.")
                nodes[module_id] = row
            for node_key, node_id in progress.items():
                row = connection.execute(
                    "SELECT * FROM knowledge_nodes WHERE id=?", (node_id,)
                ).fetchone()
                if (
                    row is None
                    or row["course_id"] != course["id"]
                    or row["owner_user_id"] is not None
                    or row["status"] not in {"CANDIDATE", "PUBLISHED"}
                ):
                    raise ApiError(409, "CANONICAL_NODE_CONFLICT", "A generated node is missing or invalid.")
                nodes[node_id] = row

            # Memberships: modules (roots or nested), atomic nodes under modules.
            parents: dict[str, str | None] = {}
            for module in plan.modules:
                parents[module_ids[module.module_key]] = (
                    key_to_id[module.parent_key] if module.parent_key else None
                )
            for node in plan.nodes:
                parents[node_ids[node.node_key]] = (
                    key_to_id[node.parent_key] if node.parent_key else None
                )
            order: list[str] = [module_ids[m.module_key] for m in plan.modules] + [
                node_ids[n.node_key] for n in plan.nodes
            ]
            memberships: list[TreeMembershipInput] = []
            children_count: dict[str | None, int] = {}
            for node_id in order:
                parent = parents[node_id]
                ordinal = children_count.get(parent, 0)
                children_count[parent] = ordinal + 1
                memberships.append(
                    TreeMembershipInput(
                        node_id=node_id,
                        parent_node_id=parent,
                        ordinal=ordinal,
                        spec_version=None if nodes[node_id]["kind"] == "COMPOSITE" else 1,
                    )
                )
            prerequisites: set[tuple[str, str]] = set()
            for node in plan.nodes:
                for prereq_key in node.prerequisites:
                    prerequisites.add((node_ids[node.node_key], node_ids[prereq_key]))
            KnowledgeService._validate_graph(nodes, memberships, prerequisites)  # noqa: SLF001

            version = int(
                connection.execute(
                    "SELECT COALESCE(MAX(version),0)+1 FROM knowledge_tree_versions "
                    "WHERE course_id=? AND tree_kind='OFFICIAL'",
                    (course["id"],),
                ).fetchone()[0]
            )
            tree_id = "official-tree-" + uuid4().hex
            title = f"{course['name']} official knowledge"[:200].strip()
            change_reason = (
                f"M6D4 bulk generation from verified corpus; operation "
                f"{payload.operation_id}; builder {COURSE_BUILDER_VERSION}"
            )[:500]
            tree_content = {
                "title": title,
                "corpus_fingerprint": corpus_fp,
                "plan_hash": plan_hash,
                "members": [
                    {
                        "node_id": member.node_id,
                        "parent_node_id": member.parent_node_id,
                        "ordinal": member.ordinal,
                        "teaching_spec_version": member.spec_version,
                    }
                    for member in memberships
                ],
                "prerequisites": [
                    {"node_id": a, "prerequisite_node_id": b}
                    for a, b in sorted(prerequisites)
                ],
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
                    title,
                    change_reason,
                    content_hash(tree_content),
                    corpus_fp,
                ),
            )
            for member in memberships:
                connection.execute(
                    "INSERT INTO knowledge_tree_memberships("
                    "tree_version_id,node_id,parent_node_id,ordinal,teaching_spec_version) "
                    "VALUES(?,?,?,?,?)",
                    (tree_id, member.node_id, member.parent_node_id, member.ordinal, member.spec_version),
                )
            for node_id, prereq_id in sorted(prerequisites):
                connection.execute(
                    "INSERT INTO knowledge_prerequisite_edges("
                    "tree_version_id,node_id,prerequisite_node_id) VALUES(?,?,?)",
                    (tree_id, node_id, prereq_id),
                )
            connection.execute(
                "UPDATE official_knowledge_generation_plans SET status='FINALIZED',"
                "final_tree_version_id=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                "WHERE id=?",
                (tree_id, plan_row["id"]),
            )
            return tree_id, version

    # ---------------------------------------------------------------- entry

    def build(
        self,
        course_id: str,
        payload: OfficialKnowledgeCourseBuild,
        *,
        admin_user_id: str,
    ) -> OfficialKnowledgeCourseBuildResult:
        plan = payload.plan
        if len(plan.nodes) > MAX_COURSE_NODES:
            raise ApiError(
                422,
                "OFFICIAL_COURSE_TOO_LARGE",
                f"At most {MAX_COURSE_NODES} atomic targets per course plan.",
            )
        course = self._course(course_id)
        plan_hash = self._plan_hash(payload)
        corpus_fp = self._corpus_fingerprint(course_id, plan_hash, payload)
        plan_json = canonical_json(payload.plan.model_dump())

        with self.database.connect() as connection:
            existing = self._plan_row(connection, course_id)
            existing_finalized = (
                existing is not None
                and existing["status"] == "FINALIZED"
                and existing["plan_hash"] == plan_hash
                and existing["corpus_fingerprint"] == corpus_fp
            )
            if payload.dry_run:
                progress: dict[str, str] = {}
                if existing is not None and existing["plan_hash"] == plan_hash:
                    progress = json.loads(existing["progress_json"])
                progress_model = OfficialKnowledgeCourseProgress(
                    course_id=course_id,
                    plan_hash=plan_hash,
                    corpus_fingerprint=corpus_fp,
                    builder_version=COURSE_BUILDER_VERSION,
                    status=existing["status"] if existing is not None else "GENERATING",
                    node_total=len(plan.nodes),
                    node_completed=len(progress),
                    completed_node_ids=progress,
                    final_tree_version_id=existing["final_tree_version_id"]
                    if existing is not None
                    else None,
                )
                return OfficialKnowledgeCourseBuildResult(
                    course_id=course_id,
                    operation_id=payload.operation_id,
                    dry_run=True,
                    existing_finalized=existing_finalized,
                    progress=progress_model,
                    model_calls_made=0,
                    reserved_output_tokens_booked=0,
                    final_tree_version_id=existing["final_tree_version_id"]
                    if existing_finalized
                    else None,
                )
            if existing_finalized:
                tree_id = str(existing["final_tree_version_id"])
                version = int(
                    connection.execute(
                        "SELECT version FROM knowledge_tree_versions WHERE id=?", (tree_id,)
                    ).fetchone()["version"]
                )
                progress = json.loads(existing["progress_json"])
                return OfficialKnowledgeCourseBuildResult(
                    course_id=course_id,
                    operation_id=payload.operation_id,
                    dry_run=False,
                    existing_finalized=True,
                    progress=OfficialKnowledgeCourseProgress(
                        course_id=course_id,
                        plan_hash=plan_hash,
                        corpus_fingerprint=corpus_fp,
                        builder_version=COURSE_BUILDER_VERSION,
                        status="FINALIZED",
                        node_total=len(plan.nodes),
                        node_completed=len(progress),
                        completed_node_ids=progress,
                        final_tree_version_id=tree_id,
                    ),
                    model_calls_made=0,
                    reserved_output_tokens_booked=0,
                    final_tree_version_id=tree_id,
                )

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            plan_row = self._upsert_plan(
                connection,
                course_id=course_id,
                plan_hash=plan_hash,
                plan_json=plan_json,
                corpus_fingerprint=corpus_fp,
            )
        assert plan_row is not None
        progress = json.loads(plan_row["progress_json"])

        join_course(self.database, course_id, admin_user_id, self.settings.user_course_max_courses)
        workspace = workspace_for(
            self.database,
            self._admin_workspace_id(course_id, admin_user_id),
            admin_user_id,
        )
        per_call = self.settings.v3_max_output_tokens
        planned_calls = self.node_builder.plan_calls(
            payload.max_model_calls_per_batch,
            payload.max_reserved_output_tokens_per_batch,
        )
        if planned_calls == 0:
            raise ApiError(
                429,
                "OFFICIAL_DRAFT_BUDGET_EXCEEDED",
                "The per-batch reserved-output-token ceiling cannot cover one model call.",
            )
        fp_payload = OfficialKnowledgeDraftGenerate(
            operation_id=payload.operation_id,
            max_nodes=1,
            max_model_calls=payload.max_model_calls_per_batch,
            max_reserved_output_tokens=payload.max_reserved_output_tokens_per_batch,
        )
        total_calls = 0
        for target in plan.nodes:
            node_id = self._plan_id(course_id, plan_hash, target.node_key)
            if target.node_key in progress:
                with self.database.connect() as connection:
                    row = connection.execute(
                        "SELECT * FROM knowledge_nodes WHERE id=?", (node_id,)
                    ).fetchone()
                if (
                    row is not None
                    and row["course_id"] == course_id
                    and row["owner_user_id"] is None
                ):
                    continue
            evidence = self.node_builder.official_evidence(
                workspace, course, query=target.evidence_queries[0]
            )
            if not evidence:
                raise ApiError(
                    422,
                    "OFFICIAL_DRAFT_EVIDENCE_UNAVAILABLE",
                    "No official corpus chunks matched this node's evidence queries.",
                    details={"nodeKey": target.node_key},
                )
            node, spec, calls = self.node_builder.generate_drafts(
                workspace=workspace,
                course=course,
                official_evidence=evidence,
                operation_id=f"{payload.operation_id}-{target.node_key}",
                max_model_calls=payload.max_model_calls_per_batch,
                max_reserved_output_tokens=payload.max_reserved_output_tokens_per_batch,
                planned_calls=planned_calls,
                max_nodes=1,
                topic=target.title,
                node_key=target.node_key,
            )
            total_calls += calls
            cited = self.node_builder.validate_outputs(node, spec, evidence)
            self.node_builder.canonicalize_node(
                course=course,
                node_id=node_id,
                node=node,
                spec=spec,
                cited_evidence=cited,
                official_evidence=evidence,
                fingerprint=corpus_fp,
                admin_user_id=admin_user_id,
                fingerprint_payload=fp_payload,
                fingerprint_builder_version=COURSE_BUILDER_VERSION,
                fingerprint_config={
                    "plan_hash": plan_hash,
                    "max_model_calls_per_batch": payload.max_model_calls_per_batch,
                    "max_reserved_output_tokens_per_batch": payload.max_reserved_output_tokens_per_batch,
                },
            )
            progress[target.node_key] = node_id
            with self.database.connect() as connection:
                self._persist_progress(connection, plan_row, progress)

        with self.database.connect() as connection:
            plan_row = connection.execute(
                "SELECT * FROM official_knowledge_generation_plans WHERE id=?",
                (plan_row["id"],),
            ).fetchone()
            assert plan_row is not None
        tree_id, tree_version = self._finalize(
            course=course,
            payload=payload,
            admin_user_id=admin_user_id,
            plan_row=plan_row,
            plan_hash=plan_hash,
            corpus_fp=corpus_fp,
            progress=progress,
        )
        progress_model = OfficialKnowledgeCourseProgress(
            course_id=course_id,
            plan_hash=plan_hash,
            corpus_fingerprint=corpus_fp,
            builder_version=COURSE_BUILDER_VERSION,
            status="FINALIZED",
            node_total=len(plan.nodes),
            node_completed=len(progress),
            completed_node_ids=progress,
            final_tree_version_id=tree_id,
        )
        return OfficialKnowledgeCourseBuildResult(
            course_id=course_id,
            operation_id=payload.operation_id,
            dry_run=False,
            existing_finalized=False,
            progress=progress_model,
            model_calls_made=total_calls,
            reserved_output_tokens_booked=total_calls * per_call,
            final_tree_version_id=tree_id,
        )

    def status(self, course_id: str) -> OfficialKnowledgeCourseProgress:
        with self.database.connect() as connection:
            row = self._plan_row(connection, course_id)
            if row is None:
                raise ApiError(
                    404,
                    "OFFICIAL_COURSE_PLAN_NOT_FOUND",
                    "No generation plan exists for this course.",
                )
            progress = json.loads(row["progress_json"])
            plan_nodes = json.loads(row["plan_json"])["nodes"]
            return OfficialKnowledgeCourseProgress(
                course_id=course_id,
                plan_hash=row["plan_hash"],
                corpus_fingerprint=row["corpus_fingerprint"],
                builder_version=row["builder_version"],
                status=row["status"],
                node_total=len(plan_nodes),
                node_completed=len(progress),
                completed_node_ids=progress,
                final_tree_version_id=row["final_tree_version_id"],
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
