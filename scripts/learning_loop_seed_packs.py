#!/usr/bin/env python3
"""Preflight or apply the two real learning-loop seed candidates."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "rag-api"))

from app.learning.learning_loop_seeds import apply_seed, plan_seed  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--course", action="append", dest="courses")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--actor-user-id", default="")
    args = parser.parse_args()
    courses = args.courses or [
        "cs3481",
        "campus-https-canvas-cityu-edu-hk-70578-70e4246363",
    ]
    actor = args.actor_user_id.strip() or os.getenv("ADMIN_USER_IDS", "").split(",")[0].strip()
    connection = sqlite3.connect(args.database)
    connection.row_factory = sqlite3.Row
    try:
        plans = [plan_seed(connection, course_id) for course_id in courses]
        result: dict[str, object] = {
            "mode": "APPLY" if args.apply else "PREFLIGHT",
            "database": str(args.database.resolve()),
            "plans": [plan.public() for plan in plans],
        }
        if args.apply:
            if not actor:
                raise SystemExit("--actor-user-id or ADMIN_USER_IDS is required for --apply")
            result["applications"] = [
                apply_seed(connection, plan=plan, actor_user_id=actor) for plan in plans
            ]
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
