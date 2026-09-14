#!/usr/bin/env python3
"""Seed a synthetic-but-valid hierarchical knowledge tree into an isolated database.

This is a TEST-ONLY fixture that walks the same integrity triggers V3 uses:
memberships are inserted while the tree version is DRAFT, then the version is
translated to PUBLISHED through the real status-transition trigger, so the
resulting rows are indistinguishable from a reviewed official tree from the point
of view of every query and trigger that reads them.

It must never run against anything outside `work/`, and it must never be called
in integrated/production mode.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "rag-api"))

from app.config import Settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.learning.workspaces import join_course  # noqa: E402

TREE_ID = "e2e-official-tree-v1"
ROOT_NODE = "e2e-tree-root"
NODE_LEARNING = "e2e-tree-clustering"
NODE_LEARNED = "e2e-tree-kmeans"
WORK_ROOT = ROOT / "work"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _spec_content(items: list[dict]) -> str:
    return json.dumps(items, ensure_ascii=False, sort_keys=True)


def _insert_node(connection: sqlite3.Connection, node_id: str, title: str, major: str) -> None:
    connection.execute(
        "INSERT INTO knowledge_nodes("
        "id,course_id,owner_user_id,title,description,major,kind,status) "
        "VALUES(?,'cs3481',NULL,?,?,?,'ATOMIC','PUBLISHED')",
        (node_id, title, f"Synthetic {title} for the closure suite", major),
    )


def seed_tree_fixture(db: Database, owner: str) -> dict:
    """Seed the tree and return {root, learning, learned, workspace_id}."""

    workspace = join_course(db, "cs3481", owner, 10)
    workspace_id = workspace["id"]
    with db.connect() as connection:
        # Composite root (published, canonical).
        connection.execute(
            "INSERT INTO knowledge_nodes("
            "id,course_id,owner_user_id,title,description,major,kind,status) "
            "VALUES(?,'cs3481',NULL,'数据科学基础','Synthetic root for the closure suite',"
            "'CS','COMPOSITE','PUBLISHED')",
            (ROOT_NODE,),
        )
        _insert_node(connection, NODE_LEARNING, "聚类分析", "CS")
        _insert_node(connection, NODE_LEARNED, "K-means 聚类", "CS")

        # Two REQUIRED items on the partially-covered node, one on the fully
        # covered node. Inserting teaching_specs fires the real fan-out trigger
        # that maintains teaching_spec_metadata and teaching_items.
        learning_items = [
            {
                "item_id": "clustering-concepts",
                "requirement": "REQUIRED",
                "objective": "Explain the synthetic clustering concepts",
                "acceptance": "State both concepts",
                "evidence_ids": [],
            },
            {
                "item_id": "clustering-metrics",
                "requirement": "REQUIRED",
                "objective": "Explain the synthetic clustering metrics",
                "acceptance": "State one metric",
                "evidence_ids": [],
            },
        ]
        learned_items = [
            {
                "item_id": "kmeans-algorithm",
                "requirement": "REQUIRED",
                "objective": "Explain the synthetic K-means algorithm",
                "acceptance": "State the update rule",
                "evidence_ids": [],
            }
        ]
        for node_id, items in (
            (NODE_LEARNING, learning_items),
            (NODE_LEARNED, learned_items),
        ):
            content = _spec_content(items)
            connection.execute(
                "INSERT INTO teaching_specs(node_id,version,content_json,content_hash) "
                "VALUES(?,1,?,?)",
                (node_id, content, _digest(content)),
            )

        # The official tree version starts DRAFT so memberships may be inserted;
        # review metadata is present so the real transition trigger accepts
        # DRAFT -> PUBLISHED.
        tree_hash = _digest(json.dumps({"fixture": TREE_ID}, sort_keys=True))
        connection.execute(
            "INSERT INTO knowledge_tree_versions("
            "id,course_id,workspace_id,owner_user_id,tree_kind,version,status,title,"
            "change_reason,content_hash,reviewed_by_user_id,reviewed_at) "
            "VALUES(?,'cs3481',NULL,NULL,'OFFICIAL',1,'DRAFT','Synthetic closure tree',"
            "'Seeded by the closure test fixture',?,'e2e-admin-reviewer',"
            "'2026-09-14T00:00:00.000Z')",
            (TREE_ID, tree_hash),
        )
        for node_id, parent, ordinal, spec in (
            (ROOT_NODE, None, 0, None),
            (NODE_LEARNING, ROOT_NODE, 0, 1),
            (NODE_LEARNED, ROOT_NODE, 1, 1),
        ):
            connection.execute(
                "INSERT INTO knowledge_tree_memberships("
                "tree_version_id,node_id,parent_node_id,ordinal,teaching_spec_version) "
                "VALUES(?,?,?,?,?)",
                (TREE_ID, node_id, parent, ordinal, spec),
            )
        connection.execute(
            "UPDATE knowledge_tree_versions SET status='PUBLISHED' WHERE id=?", (TREE_ID,)
        )

        # Delivery evidence: the same rows V3 teach() writes. The partially
        # covered node gets 1 of 2 REQUIRED items covered (LEARNING); the other
        # node gets its single REQUIRED item covered (LEARNED).
        def new_id(prefix: str) -> str:
            import uuid

            return prefix + uuid.uuid4().hex[:12]

        def journey(node_id: str) -> str:
            row = connection.execute(
                "SELECT * FROM learning_journeys WHERE workspace_id=? AND node_id=? "
                "AND spec_version=1",
                (workspace_id, node_id),
            ).fetchone()
            if row is not None:
                return row["id"]
            journey_id = new_id("e2e-journey-")
            connection.execute(
                "INSERT INTO learning_journeys(id,workspace_id,node_id,spec_version) "
                "VALUES(?,?,?,1)",
                (journey_id, workspace_id, node_id),
            )
            return journey_id

        def cover(node_id: str, item_id: str) -> None:
            journey_id = journey(node_id)
            unit_id = new_id("e2e-unit-")
            # content_json must list the section the evidence references, and the
            # unit must belong to the same journey/node/spec - both enforced by
            # the real delivery-evidence context trigger.
            content_json = json.dumps({"sections": [{"section_id": "synthetic-section"}]})
            connection.execute(
                "INSERT INTO teaching_units("
                "id,journey_id,operation_id,workflow,content_json,plan_json,"
                "provenance_json) VALUES(?,?,'e2e-operation','TEACHING',?,'{}','{}')",
                (unit_id, journey_id, content_json),
            )
            # LEGACY_PRESERVED is the same shape migration 015 backfills from
            # pre-plan teaching units; it keeps the trigger's plan-link clause
            # out of play while remaining valid evidence for coverage counting.
            connection.execute(
                "INSERT INTO teaching_delivery_evidence("
                "id,journey_id,node_id,spec_version,item_id,teaching_unit_id,"
                "section_id,plan_version_id,plan_unit_key,content_hash,"
                "validation_status,validation_reason) "
                "VALUES(?,?,?,1,?,?,?,NULL,NULL,NULL,'LEGACY_PRESERVED',"
                "'Seeded by the closure test fixture')",
                (
                    "e2e-evidence-" + item_id,
                    journey_id,
                    node_id,
                    item_id,
                    unit_id,
                    "synthetic-section",
                ),
            )

        cover(NODE_LEARNING, "clustering-concepts")
        cover(NODE_LEARNED, "kmeans-algorithm")

    return {
        "root": ROOT_NODE,
        "learning": NODE_LEARNING,
        "learned": NODE_LEARNED,
        "workspace_id": workspace_id,
    }


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: seed_tree_fixture.py DATABASE_PATH [OWNER]")
    target = Path(sys.argv[1]).resolve()
    # The E2E flow hands over the database `prepare_full_e2e.py` already built;
    # opening it directly keeps one shared file for the server and every seeder.
    if not target.is_file() or WORK_ROOT not in target.parents:
        raise ValueError("An existing database file under work/ is required")
    db = Database(
        Settings(
            database_path=target,
            upload_dir=target.parent / "uploads",
            v3_enabled=True,
        )
    )
    seed_tree_fixture(db, sys.argv[2] if len(sys.argv) > 2 else "e2e-owner")
    print("Seeded one synthetic hierarchical tree.")


if __name__ == "__main__":
    main()
