import hashlib
import json
import sqlite3
from collections import defaultdict
from typing import Any
from uuid import uuid4

from app.db import Database
from app.errors import ApiError
from app.learning.models import PersonalPlanInput, TreeMembershipInput
from app.learning.workspaces import workspace_for


def _encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _assessment_state() -> dict[str, object]:
    # Formal assessment arrives in Stage 5. Absence is explicit, never score zero.
    return {"status": "NOT_ASSESSED", "raw_score": None, "grade_label": None}


def _has_cycle(adjacency: dict[str, set[str]], nodes: set[str]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> bool:
        if node_id in visiting:
            return True
        if node_id in visited:
            return False
        visiting.add(node_id)
        for child in adjacency.get(node_id, set()):
            if visit(child):
                return True
        visiting.remove(node_id)
        visited.add(node_id)
        return False

    return any(visit(node_id) for node_id in nodes if node_id not in visited)


class KnowledgeService:
    """Course-scoped Registry and immutable tree projections.

    The service stores structure and computes learning state from delivery evidence. It never
    writes Assessment results or copies node progress into a personalized tree.
    """

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _accessible_nodes(
        connection: sqlite3.Connection,
        workspace: sqlite3.Row,
        node_ids: set[str] | None = None,
    ) -> list[sqlite3.Row]:
        parameters: list[object] = [
            workspace["course_id"],
            workspace["owner_user_id"],
        ]
        id_clause = ""
        if node_ids is not None:
            placeholders = ",".join("?" for _ in node_ids)
            id_clause = f" AND id IN ({placeholders})"
            parameters.extend(sorted(node_ids))
        return connection.execute(
            "SELECT id,course_id,owner_user_id,title,description,major,kind,status,created_at "
            "FROM knowledge_nodes WHERE course_id=? AND ("
            "(owner_user_id=? AND status='PRIVATE') OR "
            "(owner_user_id IS NULL AND status='PUBLISHED'))"
            + id_clause
            + " ORDER BY created_at,id",
            parameters,
        ).fetchall()

    @staticmethod
    def _spec_version(
        connection: sqlite3.Connection,
        node: sqlite3.Row,
        requested: int | None,
    ) -> int | None:
        if node["kind"] == "COMPOSITE":
            if requested is not None:
                raise ApiError(
                    422,
                    "COMPOSITE_SPEC",
                    "Composite nodes aggregate atomic descendants and cannot pin a Teaching Spec.",
                )
            return None
        expected_status = "PRIVATE_ACTIVE" if node["owner_user_id"] else "PUBLISHED"
        row = connection.execute(
            "SELECT version FROM teaching_spec_metadata "
            "WHERE node_id=? AND status=? "
            + ("AND version=? " if requested is not None else "")
            + "ORDER BY version DESC LIMIT 1",
            (
                (node["id"], expected_status, requested)
                if requested is not None
                else (node["id"], expected_status)
            ),
        ).fetchone()
        if row is None:
            raise ApiError(
                422,
                "SPEC_NOT_AVAILABLE",
                "An active Teaching Spec is required for every atomic tree member.",
            )
        return int(row["version"])

    @staticmethod
    def _validate_graph(
        nodes: dict[str, sqlite3.Row],
        memberships: list[TreeMembershipInput],
        prerequisites: set[tuple[str, str]],
    ) -> None:
        node_ids = set(nodes)
        parent_by_node = {member.node_id: member.parent_node_id for member in memberships}
        sibling_positions: set[tuple[str | None, int]] = set()
        children: dict[str, set[str]] = defaultdict(set)
        for member in memberships:
            sibling = (member.parent_node_id, member.ordinal)
            if sibling in sibling_positions:
                raise ApiError(
                    422,
                    "TREE_ORDER_CONFLICT",
                    "Sibling positions must be unique within one tree version.",
                )
            sibling_positions.add(sibling)
            if member.parent_node_id is not None:
                if member.parent_node_id not in node_ids:
                    raise ApiError(
                        422,
                        "TREE_ORPHAN",
                        "Every parent must be a member of the same tree version.",
                    )
                children[member.parent_node_id].add(member.node_id)
        for parent_id in children:
            if nodes[parent_id]["kind"] == "ATOMIC":
                raise ApiError(
                    422,
                    "ATOMIC_PARENT",
                    "An atomic knowledge node cannot contain child nodes.",
                )
        if _has_cycle(children, node_ids):
            raise ApiError(422, "TREE_CYCLE", "The hierarchy cannot contain a cycle.")
        for node_id, node in nodes.items():
            if node["kind"] == "COMPOSITE" and not children.get(node_id):
                raise ApiError(
                    422,
                    "EMPTY_COMPOSITE",
                    "A composite tree member must contain at least one child.",
                )
        prerequisite_graph: dict[str, set[str]] = defaultdict(set)
        for node_id, prerequisite_id in prerequisites:
            if node_id not in node_ids or prerequisite_id not in node_ids:
                raise ApiError(
                    422,
                    "MISSING_PREREQUISITE",
                    "Every prerequisite must be included in the same tree version.",
                )
            if node_id == prerequisite_id:
                raise ApiError(
                    422,
                    "PREREQUISITE_CYCLE",
                    "A node cannot be its own prerequisite.",
                )
            prerequisite_graph[prerequisite_id].add(node_id)
        if _has_cycle(prerequisite_graph, node_ids):
            raise ApiError(
                422,
                "PREREQUISITE_CYCLE",
                "The prerequisite graph must be acyclic.",
            )
        if set(parent_by_node) != node_ids:
            raise ApiError(422, "TREE_INVALID", "The tree membership set is incomplete.")

    @staticmethod
    def _official_prerequisites(
        connection: sqlite3.Connection,
        course_id: str,
        selected: set[str],
    ) -> set[tuple[str, str]]:
        tree = connection.execute(
            "SELECT id FROM knowledge_tree_versions WHERE course_id=? "
            "AND tree_kind='OFFICIAL' AND status='PUBLISHED'",
            (course_id,),
        ).fetchone()
        if tree is None:
            return set()
        result: set[tuple[str, str]] = set()
        for row in connection.execute(
            "SELECT node_id,prerequisite_node_id FROM knowledge_prerequisite_edges "
            "WHERE tree_version_id=?",
            (tree["id"],),
        ):
            if row["node_id"] in selected:
                if row["prerequisite_node_id"] not in selected:
                    raise ApiError(
                        422,
                        "MISSING_PREREQUISITE",
                        "The personalized plan omits a required official prerequisite.",
                    )
                result.add((row["node_id"], row["prerequisite_node_id"]))
        return result

    def create_personal_plan(
        self,
        connection: sqlite3.Connection,
        workspace: sqlite3.Row,
        payload: PersonalPlanInput,
    ) -> dict[str, Any]:
        requested_ids = {member.node_id for member in payload.memberships}
        rows = self._accessible_nodes(connection, workspace, requested_ids)
        nodes = {row["id"]: row for row in rows}
        if set(nodes) != requested_ids:
            raise ApiError(404, "NODE_NOT_FOUND", "A knowledge node was not found.")
        resolved_members = [
            {
                "node_id": member.node_id,
                "parent_node_id": member.parent_node_id,
                "ordinal": member.ordinal,
                "spec_version": self._spec_version(
                    connection, nodes[member.node_id], member.spec_version
                ),
            }
            for member in payload.memberships
        ]
        prerequisites = {
            (edge.node_id, edge.prerequisite_node_id) for edge in payload.prerequisites
        }
        prerequisites |= self._official_prerequisites(
            connection, workspace["course_id"], requested_ids
        )
        self._validate_graph(nodes, payload.memberships, prerequisites)
        previous = connection.execute(
            "SELECT id,version FROM knowledge_tree_versions WHERE workspace_id=? "
            "AND tree_kind='PERSONALIZED' AND status='ACTIVE'",
            (workspace["id"],),
        ).fetchone()
        version = int(
            connection.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM knowledge_tree_versions "
                "WHERE workspace_id=? AND tree_kind='PERSONALIZED'",
                (workspace["id"],),
            ).fetchone()[0]
        )
        content = {
            "title": payload.title,
            "memberships": resolved_members,
            "prerequisites": [
                {"node_id": node_id, "prerequisite_node_id": prerequisite_id}
                for node_id, prerequisite_id in sorted(prerequisites)
            ],
        }
        tree_id = "tree_" + uuid4().hex
        connection.execute(
            "INSERT INTO knowledge_tree_versions("
            "id,course_id,workspace_id,owner_user_id,tree_kind,version,status,title,"
            "change_reason,content_hash,base_tree_version_id) "
            "VALUES(?,?,?,?,? ,?,'DRAFT',?,?,?,?)",
            (
                tree_id,
                workspace["course_id"],
                workspace["id"],
                workspace["owner_user_id"],
                "PERSONALIZED",
                version,
                payload.title,
                payload.change_reason,
                hashlib.sha256(_encode(content).encode()).hexdigest(),
                previous["id"] if previous is not None else None,
            ),
        )
        for member in resolved_members:
            connection.execute(
                "INSERT INTO knowledge_tree_memberships("
                "tree_version_id,node_id,parent_node_id,ordinal,teaching_spec_version) "
                "VALUES(?,?,?,?,?)",
                (
                    tree_id,
                    member["node_id"],
                    member["parent_node_id"],
                    member["ordinal"],
                    member["spec_version"],
                ),
            )
        for node_id, prerequisite_id in sorted(prerequisites):
            connection.execute(
                "INSERT INTO knowledge_prerequisite_edges("
                "tree_version_id,node_id,prerequisite_node_id) VALUES(?,?,?)",
                (tree_id, node_id, prerequisite_id),
            )
        if previous is not None:
            connection.execute(
                "UPDATE knowledge_tree_versions SET status='RETIRED' WHERE id=?",
                (previous["id"],),
            )
        connection.execute(
            "UPDATE knowledge_tree_versions SET status='ACTIVE' WHERE id=?",
            (tree_id,),
        )
        return {
            "id": tree_id,
            "kind": "PERSONALIZED",
            "status": "ACTIVE",
            "version": version,
            "title": payload.title,
            "change_reason": payload.change_reason,
            "base_tree_version_id": previous["id"] if previous is not None else None,
            "members": resolved_members,
            "prerequisites": content["prerequisites"],
            "evidence_ids": [],
        }

    @staticmethod
    def _atomic_learning(
        connection: sqlite3.Connection,
        workspace_id: str,
        node_id: str,
        spec_version: int | None,
    ) -> dict[str, Any]:
        historical_query = (
            "SELECT spec_version FROM learning_journeys WHERE workspace_id=? "
            "AND node_id=? AND status='LEARNED'"
        )
        historical_parameters: tuple[object, ...] = (workspace_id, node_id)
        if spec_version is not None:
            historical_query += " AND spec_version!=?"
            historical_parameters += (spec_version,)
        historical_query += " ORDER BY spec_version"
        historical = [
            int(row[0])
            for row in connection.execute(historical_query, historical_parameters)
        ]
        if spec_version is None:
            return {
                "status": "SPEC_UNAVAILABLE",
                "spec_version": None,
                "required_total": 0,
                "covered_required": 0,
                "historical_learned_spec_versions": historical,
            }
        required = int(
            connection.execute(
                "SELECT COUNT(*) FROM teaching_items WHERE node_id=? AND spec_version=? "
                "AND requirement='REQUIRED'",
                (node_id, spec_version),
            ).fetchone()[0]
        )
        covered = int(
            connection.execute(
                "SELECT COUNT(DISTINCT items.item_id) FROM teaching_items AS items "
                "JOIN learning_journeys AS journey ON journey.node_id=items.node_id "
                "AND journey.spec_version=items.spec_version AND journey.workspace_id=? "
                "JOIN teaching_delivery_evidence AS coverage ON coverage.journey_id=journey.id "
                "AND coverage.item_id=items.item_id "
                "WHERE items.node_id=? AND items.spec_version=? "
                "AND items.requirement='REQUIRED' AND coverage.validation_status IN "
                "('VALIDATED','LEGACY_PRESERVED')",
                (workspace_id, node_id, spec_version),
            ).fetchone()[0]
        )
        if required == 0:
            status = "SPEC_UNAVAILABLE"
        elif covered == 0:
            status = "NOT_STARTED"
        elif covered < required:
            status = "LEARNING"
        else:
            status = "LEARNED"
        return {
            "status": status,
            "spec_version": spec_version,
            "required_total": required,
            "covered_required": min(covered, required),
            "historical_learned_spec_versions": historical,
        }

    def _tree_payload(
        self,
        connection: sqlite3.Connection,
        workspace: sqlite3.Row,
        row: sqlite3.Row | None,
        *,
        missing_status: str,
    ) -> dict[str, Any]:
        if row is None:
            return {
                "status": missing_status,
                "members": [],
                "prerequisites": [],
            }
        memberships = connection.execute(
            "SELECT membership.node_id,membership.parent_node_id,membership.ordinal,"
            "membership.teaching_spec_version,node.title,node.description,node.major,"
            "node.kind,node.status AS node_status,node.owner_user_id,node.course_id "
            "FROM knowledge_tree_memberships AS membership "
            "JOIN knowledge_nodes AS node ON node.id=membership.node_id "
            "WHERE membership.tree_version_id=? "
            "ORDER BY COALESCE(membership.parent_node_id,''),membership.ordinal,node.id",
            (row["id"],),
        ).fetchall()
        for member in memberships:
            same_course = member["course_id"] == workspace["course_id"]
            private_owner = (
                member["owner_user_id"] == workspace["owner_user_id"]
                and member["node_status"] == "PRIVATE"
            )
            reviewed_canonical = (
                member["owner_user_id"] is None and member["node_status"] == "PUBLISHED"
            )
            if not same_course or not (private_owner or reviewed_canonical):
                raise ApiError(
                    409,
                    "TREE_SOURCE_UNAVAILABLE",
                    "This knowledge tree references a source that is no longer available.",
                )
        atomic_states = {
            member["node_id"]: self._atomic_learning(
                connection,
                workspace["id"],
                member["node_id"],
                member["teaching_spec_version"],
            )
            for member in memberships
            if member["kind"] == "ATOMIC"
        }
        children: dict[str, set[str]] = defaultdict(set)
        for member in memberships:
            if member["parent_node_id"] is not None:
                children[member["parent_node_id"]].add(member["node_id"])
        kinds = {member["node_id"]: member["kind"] for member in memberships}

        def atomic_descendants(node_id: str, seen: set[str] | None = None) -> set[str]:
            visited = set() if seen is None else set(seen)
            if node_id in visited:
                return set()
            visited.add(node_id)
            if kinds.get(node_id) == "ATOMIC":
                return {node_id}
            result: set[str] = set()
            for child_id in children.get(node_id, set()):
                result |= atomic_descendants(child_id, visited)
            return result

        states: dict[str, dict[str, Any]] = dict(atomic_states)
        for member in memberships:
            if member["kind"] != "COMPOSITE":
                continue
            descendants = atomic_descendants(member["node_id"])
            descendant_states = [atomic_states[node_id] for node_id in descendants]
            status_values = {str(state["status"]) for state in descendant_states}
            if descendant_states and status_values == {"LEARNED"}:
                status = "LEARNED"
            elif status_values <= {"NOT_STARTED"} or not descendant_states:
                status = "NOT_STARTED"
            elif status_values <= {"SPEC_UNAVAILABLE"}:
                status = "SPEC_UNAVAILABLE"
            else:
                status = "LEARNING"
            states[member["node_id"]] = {
                "status": status,
                "spec_version": None,
                "required_total": sum(
                    int(state["required_total"]) for state in descendant_states
                ),
                "covered_required": sum(
                    int(state["covered_required"]) for state in descendant_states
                ),
                "atomic_descendant_count": len(descendants),
                "historical_learned_spec_versions": [],
            }
        members = [
            {
                "node_id": member["node_id"],
                "parent_node_id": member["parent_node_id"],
                "ordinal": member["ordinal"],
                "spec_version": member["teaching_spec_version"],
                "title": member["title"],
                "description": member["description"],
                "major": member["major"],
                "kind": member["kind"],
                "source": "PRIVATE" if member["owner_user_id"] else "CANONICAL",
                "state": {
                    "learning": states[member["node_id"]],
                    "assessment": _assessment_state(),
                },
            }
            for member in memberships
        ]
        prerequisites = [
            dict(edge)
            for edge in connection.execute(
                "SELECT node_id,prerequisite_node_id FROM knowledge_prerequisite_edges "
                "WHERE tree_version_id=? ORDER BY prerequisite_node_id,node_id",
                (row["id"],),
            )
        ]
        return {
            "id": row["id"],
            "kind": row["tree_kind"],
            "status": row["status"],
            "version": row["version"],
            "title": row["title"],
            "change_reason": row["change_reason"],
            "base_tree_version_id": row["base_tree_version_id"],
            "members": members,
            "prerequisites": prerequisites,
        }

    def snapshot(self, workspace_id: str, owner: str) -> dict[str, Any]:
        workspace = workspace_for(self.database, workspace_id, owner)
        with self.database.connect() as connection:
            official = connection.execute(
                "SELECT * FROM knowledge_tree_versions WHERE course_id=? "
                "AND tree_kind='OFFICIAL' AND status='PUBLISHED'",
                (workspace["course_id"],),
            ).fetchone()
            personal = connection.execute(
                "SELECT * FROM knowledge_tree_versions WHERE workspace_id=? "
                "AND owner_user_id=? AND tree_kind='PERSONALIZED' AND status='ACTIVE'",
                (workspace_id, owner),
            ).fetchone()
            official_payload = self._tree_payload(
                connection,
                workspace,
                official,
                missing_status="NO_REVIEWED_TREE",
            )
            personal_payload = self._tree_payload(
                connection,
                workspace,
                personal,
                missing_status="NOT_CREATED",
            )
            selected_payload = personal_payload if personal is not None else official_payload
            selected_states = {
                member["node_id"]: member["state"]
                for member in selected_payload["members"]
            }
            registry_rows = self._accessible_nodes(connection, workspace)
            registry = []
            for node in registry_rows:
                state = selected_states.get(node["id"])
                if state is None:
                    if node["kind"] == "ATOMIC":
                        try:
                            spec_version = self._spec_version(connection, node, None)
                        except ApiError:
                            spec_version = None
                        learning = self._atomic_learning(
                            connection, workspace_id, node["id"], spec_version
                        )
                    else:
                        learning = {
                            "status": "NOT_STARTED",
                            "spec_version": None,
                            "required_total": 0,
                            "covered_required": 0,
                            "atomic_descendant_count": 0,
                            "historical_learned_spec_versions": [],
                        }
                    state = {"learning": learning, "assessment": _assessment_state()}
                aliases = [
                    alias[0]
                    for alias in connection.execute(
                        "SELECT alias FROM knowledge_node_aliases WHERE node_id=? "
                        "ORDER BY locale,normalized_alias",
                        (node["id"],),
                    )
                ]
                registry.append(
                    {
                        "id": node["id"],
                        "title": node["title"],
                        "description": node["description"],
                        "major": node["major"],
                        "kind": node["kind"],
                        "status": node["status"],
                        "source": "PRIVATE" if node["owner_user_id"] else "CANONICAL",
                        "aliases": aliases,
                        "state": state,
                    }
                )
        selected = "PERSONALIZED" if personal is not None else (
            "OFFICIAL" if official is not None else "NONE"
        )
        return {
            "workspace_id": workspace_id,
            "course_id": workspace["course_id"],
            "revision": workspace["revision"],
            "selected_tree": selected,
            "official_tree": official_payload,
            "personalized_tree": personal_payload,
            "registry": registry,
        }
