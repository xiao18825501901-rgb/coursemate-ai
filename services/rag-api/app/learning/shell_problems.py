"""Record completed shell problems into the V3 versioned problem ledger.

The refreshed shell's problem lane persists the original question and the
server-derived solution steps in ``cmui_messages``. This module maps those
completed rows into the V3 normalized ledger so the whole business process is
traceable from stable, versioned, owner/course-controlled ids:

    learning_problems          -> the original problem (workspace scoped)
    problem_revisions          -> its versioned, immutable revision (TEXT,
                                 VALIDATED with a content hash)
    learning_solutions/steps   -> the completed solution and its numbered steps

The UI keeps its own navigation table (``cmui_bridges``) and the V3 rows keep
the teaching facts; the bridge row stores ``problem_revision_id`` and
``solution_id`` as the verifiable link. No answer is ever regenerated here, and
no plan-based solve pipeline is touched.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from typing import Any

from app.learning.orchestrator import encode

TEXT_INPUT_KIND = "TEXT"


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _load_existing(
    connection: sqlite3.Connection, problem_id: str
) -> dict[str, Any] | None:
    problem = connection.execute(
        "SELECT * FROM learning_problems WHERE id=?", (problem_id,)
    ).fetchone()
    if problem is None:
        return None
    revision = connection.execute(
        "SELECT id FROM problem_revisions WHERE problem_id=? ORDER BY revision DESC LIMIT 1",
        (problem_id,),
    ).fetchone()
    solution = connection.execute(
        "SELECT id FROM learning_solutions WHERE problem_id=? ORDER BY version DESC LIMIT 1",
        (problem_id,),
    ).fetchone()
    steps = [
        str(row[0])
        for row in connection.execute(
            "SELECT id FROM learning_steps WHERE solution_id=? ORDER BY ordinal",
            (solution["id"],),
        )
    ] if solution is not None else []
    return {
        "problem_id": problem_id,
        "problem_revision_id": revision["id"] if revision is not None else None,
        "solution_id": solution["id"] if solution is not None else None,
        "step_ids": steps,
        "replayed": True,
    }


def record_shell_problem(
    database: Any,
    *,
    workspace_id: str,
    course_id: str,
    question: str,
    steps: list[dict[str, Any]],
    operation_id: str,
) -> dict[str, Any]:
    """Record (or replay) one completed shell problem run.

    ``operation_id`` is the stable cmui problem run id; the problem id derives
    from it so a retry after any interruption replays the same rows instead of
    creating a second revision.
    """

    problem_id = f"shell-{operation_id}"
    with database.connect() as connection:
        existing = _load_existing(connection, problem_id)
        if existing is not None:
            return existing

    revision_id = "prev_" + uuid.uuid4().hex
    solution_id = "sol_" + uuid.uuid4().hex
    provenance = {
        "source": "cmui_problem_run",
        "run_id": operation_id,
        "course_id": course_id,
    }
    ordered_steps = [
        {
            "number": int(step.get("number") or 0),
            "title": str(step.get("title") or ""),
            "content": str(step.get("content") or ""),
        }
        for step in steps
        if int(step.get("number") or 0) >= 1
    ]
    try:
        with database.connect() as connection:
            connection.execute(
                "INSERT INTO learning_problems("
                "id,workspace_id,version,question,conditions_json,source_refs_json,"
                "attempt_id,assistance"
                ") VALUES(?,?,1,?,'{}',?,?,'ANSWER_EXPOSED')",
                (
                    problem_id,
                    workspace_id,
                    question,
                    encode(provenance),
                    operation_id,
                ),
            )
            connection.execute(
                "INSERT INTO problem_revisions("
                "id,problem_id,workspace_id,revision,input_kind,question_text,"
                "question_transcription,transcription_status,visual_uncertainties_json,"
                "problem_index_entry_id,input_document_version_id,input_source_sha256,"
                "source_locator_json,content_hash,validation_status"
                ") VALUES(?,?,?,1,'TEXT',?,?,"
                "'NOT_APPLICABLE','[]',NULL,NULL,NULL,?,?,'VALIDATED')",
                (
                    revision_id,
                    problem_id,
                    workspace_id,
                    question,
                    question,
                    encode(provenance),
                    _hash_text(question),
                ),
            )
            connection.execute(
                "INSERT INTO learning_solutions(id,problem_id,version,content_json) "
                "VALUES(?,?,1,?)",
                (
                    solution_id,
                    problem_id,
                    encode(
                        {
                            "source": "cmui_problem_run",
                            "run_id": operation_id,
                            "steps": [
                                {"number": s["number"], "title": s["title"]}
                                for s in ordered_steps
                            ],
                        }
                    ),
                ),
            )
            step_ids: list[str] = []
            for ordinal, step in enumerate(ordered_steps, start=1):
                step_id = "step_" + uuid.uuid4().hex
                connection.execute(
                    "INSERT INTO learning_steps(id,solution_id,ordinal,content_json) "
                    "VALUES(?,?,?,?)",
                    (step_id, solution_id, ordinal, encode(step)),
                )
                step_ids.append(step_id)
    except sqlite3.IntegrityError:
        with database.connect() as connection:
            existing = _load_existing(connection, problem_id)
            if existing is not None:
                return existing
            raise
    return {
        "problem_id": problem_id,
        "problem_revision_id": revision_id,
        "solution_id": solution_id,
        "step_ids": step_ids,
        "replayed": False,
    }
