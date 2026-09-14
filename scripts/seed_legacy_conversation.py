#!/usr/bin/env python3
"""Seed one pre-existing V3 conversation into an isolated E2E database copy.

The refreshed shell must keep the original question-and-answer history readable.
This inserts rows exactly as the existing V3 Q&A surface would, into the throwaway
`work/e2e-*` copy only, so the browser suite can prove the read-only legacy reader
works. It refuses to touch anything outside `work/`.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

WORK_ROOT = (Path(__file__).resolve().parents[1] / "work").resolve()


def seed(database_path: Path, owner: str) -> None:
    target = database_path.resolve()
    if not target.is_file():
        raise ValueError(f"E2E database does not exist: {target}")
    if WORK_ROOT not in target.parents:
        raise ValueError("Refusing to seed a database outside the work directory")
    if not owner.strip() or len(owner) > 200:
        raise ValueError("A bounded synthetic owner is required")

    connection = sqlite3.connect(target)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "INSERT OR REPLACE INTO conversations (id, owner_user_id, course_id, title) "
            "VALUES (?,?,?,?)",
            ("conv_ui_e2e_legacy", owner, "cs3481", "旧版问答：DBSCAN 核心点"),
        )
        connection.execute(
            "DELETE FROM messages WHERE conversation_id=?",
            ("conv_ui_e2e_legacy",),
        )
        for index, (role, content, citations) in enumerate(
            (
                ("user", "旧版提问：DBSCAN 怎么判断核心点？", []),
                (
                    "assistant",
                    "核心点在 eps 邻域内至少包含 MinPts 个点（含自身）。",
                    [
                        {
                            "document_id": "doc_ui_e2e",
                            "filename": "lecture_04_clustering.md",
                            "locator": "page:3",
                        }
                    ],
                ),
            )
        ):
            connection.execute(
                "INSERT INTO messages (id, conversation_id, role, content, citations_json, "
                "created_at) VALUES (?,?,?,?,?,?)",
                (
                    f"msg_ui_e2e_{index}",
                    "conv_ui_e2e_legacy",
                    role,
                    content,
                    json.dumps(citations, ensure_ascii=False),
                    f"2026-09-10T0{index + 1}:00:00.000Z",
                ),
            )
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: seed_legacy_conversation.py DATABASE_PATH OWNER")
    seed(Path(sys.argv[1]), sys.argv[2])
    print("Seeded one legacy V3 conversation.")
