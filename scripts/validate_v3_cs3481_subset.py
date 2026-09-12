"""Validate a non-published Stage 2 tree against an isolated CS3481 data copy.

This script never calls a model and refuses databases outside the repository's ignored work/
directory. The inserted nodes and tree are explicit engineering fixtures, not reviewed course
content and not candidates for automatic publication.
"""

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/rag-api"))

from app.config import Settings  # noqa: E402 - repository-local service bootstrap
from app.db import LATEST_V3_SCHEMA_VERSION, Database  # noqa: E402
from app.learning.knowledge import KnowledgeService  # noqa: E402
from app.learning.workspaces import join_course  # noqa: E402

COURSE_ID = "cs3481"
OWNER_ID = "stage2-cs3481-validator"
TREE_ID = "stage2-cs3481-candidate-tree"
ROOT_NODE_ID = "stage2-cs3481-transformations"
MATRIX_NODE_ID = "stage2-cs3481-transformation-matrices"
HOMOGENEOUS_NODE_ID = "stage2-cs3481-homogeneous-coordinates"


def encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def source_chunk(connection: sqlite3.Connection, term: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT chunks.id,chunk_source_versions.document_version_id,"
        "chunks.locator_type,chunks.locator_value "
        "FROM chunks JOIN chunk_source_versions "
        "ON chunk_source_versions.chunk_id=chunks.id "
        "JOIN document_versions ON document_versions.id="
        "chunk_source_versions.document_version_id "
        "WHERE chunks.course_id=? AND document_versions.source_scope='OFFICIAL' "
        "AND lower(chunks.content) LIKE ? ORDER BY chunks.document_id,chunks.ordinal LIMIT 1",
        (COURSE_ID, f"%{term}%"),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"No authorized CS3481 source chunk contains term: {term}")
    return row


def teaching_items(title: str, evidence_id: str) -> list[dict[str, object]]:
    return [
        {
            "item_id": "core_explanation",
            "requirement": "REQUIRED",
            "objective": f"Explain the role of {title} in the selected CS3481 material",
            "acceptance": "Persist a complete explanation and one worked application",
            "evidence_ids": [evidence_id],
        }
    ]


def validate(database_path: Path) -> dict[str, object]:
    database_path = database_path.resolve()
    work_root = (ROOT / "work").resolve()
    if not database_path.is_file() or not database_path.is_relative_to(work_root):
        raise ValueError("Use an existing isolated database file under repository work/")
    evidence_path = database_path.parent / "stage2-subset-evidence.json"
    if evidence_path.exists():
        raise ValueError("Use a fresh isolated copy; validation evidence already exists")

    database = Database(
        Settings(
            database_path=database_path,
            upload_dir=database_path.parent / "uploads",
            v3_enabled=True,
        )
    )
    database.initialize()
    workspace = join_course(database, COURSE_ID, OWNER_ID, limit=1)
    with database.connect() as connection:
        versions = [
            int(row[0])
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        if versions != list(range(1, LATEST_V3_SCHEMA_VERSION + 1)):
            raise RuntimeError("The isolated copy is not at the current V3 Schema version")
        if connection.execute(
            "SELECT 1 FROM knowledge_tree_versions WHERE course_id=? "
            "AND tree_kind='OFFICIAL' AND status='PUBLISHED'",
            (COURSE_ID,),
        ).fetchone():
            raise RuntimeError("This validation requires a copy without a published official tree")

        matrix_source = source_chunk(connection, "transformation")
        homogeneous_source = source_chunk(connection, "homogeneous")
        fixtures = (
            (ROOT_NODE_ID, "Transformations", "COMPOSITE", None),
            (
                MATRIX_NODE_ID,
                "Transformation matrices",
                "ATOMIC",
                matrix_source,
            ),
            (
                HOMOGENEOUS_NODE_ID,
                "Homogeneous coordinates",
                "ATOMIC",
                homogeneous_source,
            ),
        )
        for node_id, title, kind, source in fixtures:
            connection.execute(
                "INSERT INTO knowledge_nodes("
                "id,course_id,owner_user_id,title,description,major,kind,status) "
                "VALUES(?,?,NULL,?,?,? ,?,'CANDIDATE')",
                (
                    node_id,
                    COURSE_ID,
                    title,
                    "Unreviewed Stage 2 structure fixture backed by course material",
                    "CS",
                    kind,
                ),
            )
            if source is None:
                continue
            items = teaching_items(title, source["id"])
            content = encode(items)
            connection.execute(
                "INSERT INTO teaching_specs(node_id,version,content_json,content_hash) "
                "VALUES(?,1,?,?)",
                (node_id, content, hashlib.sha256(content.encode()).hexdigest()),
            )
            connection.execute(
                "INSERT INTO material_evidence("
                "id,node_id,document_version_id,chunk_id,owner_user_id,source_scope,"
                "locator_type,locator_value) VALUES(?,?,?,?,NULL,'OFFICIAL',?,?)",
                (
                    f"evidence-{node_id}",
                    node_id,
                    source["document_version_id"],
                    source["id"],
                    source["locator_type"],
                    source["locator_value"],
                ),
            )

        tree_content = {
            "members": [ROOT_NODE_ID, MATRIX_NODE_ID, HOMOGENEOUS_NODE_ID],
            "hierarchy": [
                [ROOT_NODE_ID, MATRIX_NODE_ID],
                [ROOT_NODE_ID, HOMOGENEOUS_NODE_ID],
            ],
            "prerequisites": [[HOMOGENEOUS_NODE_ID, MATRIX_NODE_ID]],
        }
        connection.execute(
            "INSERT INTO knowledge_tree_versions("
            "id,course_id,workspace_id,owner_user_id,tree_kind,version,status,title,"
            "change_reason,content_hash) VALUES(?,?,NULL,NULL,'OFFICIAL',1,'DRAFT',?,?,?)",
            (
                TREE_ID,
                COURSE_ID,
                "CS3481 Stage 2 candidate subset",
                "SUPPLEMENTAL ENGINEERING DECISION: local structure validation only",
                hashlib.sha256(encode(tree_content).encode()).hexdigest(),
            ),
        )
        memberships = (
            (ROOT_NODE_ID, None, 0, None),
            (MATRIX_NODE_ID, ROOT_NODE_ID, 0, 1),
            (HOMOGENEOUS_NODE_ID, ROOT_NODE_ID, 1, 1),
        )
        for node_id, parent_id, ordinal, spec_version in memberships:
            connection.execute(
                "INSERT INTO knowledge_tree_memberships("
                "tree_version_id,node_id,parent_node_id,ordinal,teaching_spec_version) "
                "VALUES(?,?,?,?,?)",
                (TREE_ID, node_id, parent_id, ordinal, spec_version),
            )
        connection.execute(
            "INSERT INTO knowledge_prerequisite_edges("
            "tree_version_id,node_id,prerequisite_node_id) VALUES(?,?,?)",
            (TREE_ID, HOMOGENEOUS_NODE_ID, MATRIX_NODE_ID),
        )

    snapshot = KnowledgeService(database).snapshot(str(workspace["id"]), OWNER_ID)
    with database.connect() as connection:
        row = connection.execute(
            "SELECT status,reviewed_by_user_id,reviewed_at FROM knowledge_tree_versions "
            "WHERE id=?",
            (TREE_ID,),
        ).fetchone()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        result = {
            "course_id": COURSE_ID,
            "schema_versions": versions,
            "tree_status": row["status"],
            "reviewed_by_user_id": row["reviewed_by_user_id"],
            "reviewed_at": row["reviewed_at"],
            "tree_members": connection.execute(
                "SELECT COUNT(*) FROM knowledge_tree_memberships WHERE tree_version_id=?",
                (TREE_ID,),
            ).fetchone()[0],
            "hierarchy_edges": connection.execute(
                "SELECT COUNT(*) FROM knowledge_tree_memberships "
                "WHERE tree_version_id=? AND parent_node_id IS NOT NULL",
                (TREE_ID,),
            ).fetchone()[0],
            "prerequisite_edges": connection.execute(
                "SELECT COUNT(*) FROM knowledge_prerequisite_edges WHERE tree_version_id=?",
                (TREE_ID,),
            ).fetchone()[0],
            "material_evidence_rows": connection.execute(
                "SELECT COUNT(*) FROM material_evidence WHERE node_id IN (?,?)",
                (MATRIX_NODE_ID, HOMOGENEOUS_NODE_ID),
            ).fetchone()[0],
            "learner_official_view": snapshot["official_tree"]["status"],
            "candidate_nodes_visible_to_learner": any(
                node["id"] in {ROOT_NODE_ID, MATRIX_NODE_ID, HOMOGENEOUS_NODE_ID}
                for node in snapshot["registry"]
            ),
            "model_calls": 0,
            "integrity": integrity,
            "foreign_key_violations": len(foreign_keys),
        }
    expected = {
        "tree_status": "DRAFT",
        "learner_official_view": "NO_REVIEWED_TREE",
        "candidate_nodes_visible_to_learner": False,
        "tree_members": 3,
        "hierarchy_edges": 2,
        "prerequisite_edges": 1,
        "material_evidence_rows": 2,
        "model_calls": 0,
        "integrity": "ok",
        "foreign_key_violations": 0,
    }
    if any(result[key] != value for key, value in expected.items()):
        raise RuntimeError("Stage 2 subset validation failed; inspect content-free evidence")
    evidence_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    arguments = parser.parse_args()
    print(json.dumps(validate(arguments.database)))
