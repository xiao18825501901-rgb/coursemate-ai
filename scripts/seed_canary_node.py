#!/usr/bin/env python3
"""Seed one zero-coverage teaching node for the live canary (test-only).

C1/C2 need a real node whose REQUIRED items start UNCOVERED, so the live
two-stage teaching + model coverage review + real coverage submission can be
observed from zero. The acceptance statements are authored criteria (not the
deterministic test reviewer's echo trick): the real reviewer must judge the
teaching content on its own terms.

Refuses to run against anything outside ``work/``; never used in production.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "rag-api"))

from app.config import Settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.learning.workspaces import join_course  # noqa: E402

NODE = "canary-clustering-zero"
ITEM_A = "canary-item-a"
ITEM_B = "canary-item-b"


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("usage: seed_canary_node.py DATABASE_PATH OWNER")
    target = Path(sys.argv[1]).resolve()
    owner = sys.argv[2]
    work_root = (ROOT / "work").resolve()
    if not target.is_file() or work_root not in target.parents:
        raise ValueError("An existing database file under work/ is required")
    database = Database(
        Settings(
            database_path=target,
            upload_dir=target.parent / "uploads",
            v3_enabled=True,
        )
    )
    database.initialize()
    join_course(database, "cs3481", owner, 10)
    content = json.dumps(
        [
            {
                "item_id": ITEM_A,
                "requirement": "REQUIRED",
                "objective": "Explain why DBSCAN uses a density condition for core points.",
                "acceptance": "解释核心点的密度判定条件（eps 邻域与 MinPts），并说明噪声点如何产生。",
                "evidence_ids": [],
            },
            {
                "item_id": ITEM_B,
                "requirement": "REQUIRED",
                "objective": "Explain how clusters grow from core points.",
                "acceptance": "说明密度可达与密度相连如何把一个聚类扩张，并给出判断边界点的规则。",
                "evidence_ids": [],
            },
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO knowledge_nodes(id,course_id,owner_user_id,title,description,"
            "major,kind,status) VALUES(?,'cs3481',NULL,'聚类：DBSCAN 密度条件（canary）',"
            "'Live canary teaching node, zero coverage','CS','ATOMIC','PUBLISHED')",
            (NODE,),
        )
        connection.execute(
            "INSERT INTO teaching_specs(node_id,version,content_json,content_hash) "
            "VALUES(?,1,?,?)",
            (NODE, content, hashlib.sha256(content.encode()).hexdigest()),
        )
    print(json.dumps({"node": NODE, "items": [ITEM_A, ITEM_B], "spec_version": 1}))


if __name__ == "__main__":
    main()
