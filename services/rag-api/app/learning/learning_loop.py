"""Evidence-first learning-loop orchestration over CourseJesus authorities.

This module does not retrieve course text, generate a grade, write LEARNED, or
own Pair/Task Agent data.  It stores ordered references to the existing
Question Engine, practice submission and evaluation records in the RAG
database.  Raw answers live only in ``practice_submission_revisions`` because
that is the canonical pre-evaluation submission boundary.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.db import Database


class LearningLoopError(ValueError):
    """A stable, non-sensitive learning-loop refusal."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


ExposureKind = Literal[
    "STEM", "HINT_REQUEST", "HINT", "DETAIL", "SOLUTION", "TARGETED_TEACHING"
]
ExposureChannel = Literal[
    "QUESTION", "TEACHING_PANE", "PROBLEM_PANE", "DETAIL_WINDOW", "HISTORY",
    "AUTHORIZED_SHARE",
]

_KINDS = {"STEM", "HINT_REQUEST", "HINT", "DETAIL", "SOLUTION", "TARGETED_TEACHING"}
_CHANNELS = {
    "QUESTION", "TEACHING_PANE", "PROBLEM_PANE", "DETAIL_WINDOW", "HISTORY",
    "AUTHORIZED_SHARE",
}


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _digest(value: Any) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


class LearningLoopService:
    """Small coordinator around current CourseJesus source and grade tables."""

    def __init__(
        self,
        database: Database,
        *,
        internal_user_ids: set[str] | None = None,
        test_environment: bool = False,
    ) -> None:
        self.database = database
        self.internal_user_ids = frozenset(internal_user_ids or ())
        self.test_environment = test_environment

    @staticmethod
    def _stable_operation(operation_id: str) -> str:
        value = operation_id.strip()
        if not 8 <= len(value) <= 120:
            raise LearningLoopError("OPERATION_ID_REQUIRED")
        return value

    @staticmethod
    def _command_replay(
        connection: sqlite3.Connection,
        *,
        owner_user_id: str,
        operation_id: str,
        action: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT action,input_hash,result_json FROM learning_loop_commands "
            "WHERE owner_user_id=? AND operation_id=?",
            (owner_user_id, operation_id),
        ).fetchone()
        if row is None:
            return None
        if row["action"] != action or row["input_hash"] != _digest(payload):
            raise LearningLoopError("IDEMPOTENCY_CONFLICT")
        return json.loads(row["result_json"])

    @staticmethod
    def _remember(
        connection: sqlite3.Connection,
        *,
        owner_user_id: str,
        operation_id: str,
        action: str,
        payload: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        connection.execute(
            "INSERT INTO learning_loop_commands("
            "owner_user_id,operation_id,action,input_hash,result_json) VALUES(?,?,?,?,?)",
            (owner_user_id, operation_id, action, _digest(payload), _canonical(result)),
        )
        return result

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        *,
        owner_user_id: str,
        workspace_id: str,
        cycle_id: str | None,
        kind: str,
        payload: dict[str, Any],
        event_id: str | None = None,
    ) -> int:
        forbidden = {
            "answer", "answer_text", "raw_answer", "prompt", "private_plan", "token",
            "secret", "reasoning", "source_text",
        }
        if forbidden & set(payload):
            raise LearningLoopError("ANALYTICS_PAYLOAD_FORBIDDEN")
        cursor = connection.execute(
            "INSERT INTO learning_loop_events("
            "event_id,owner_user_id,workspace_id,cycle_id,kind,payload_json) "
            "VALUES(?,?,?,?,?,?)",
            (
                event_id or _id("event"), owner_user_id, workspace_id, cycle_id, kind,
                _canonical(payload),
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _record_reliability_in_connection(
        connection: sqlite3.Connection,
        *,
        owner_user_id: str,
        cycle_id: str | None,
        operation_id: str,
        stage: str,
        status: str,
        latency_ms: int | None = None,
    ) -> dict[str, Any]:
        if stage not in {"FIRST_RENDER", "SAVE", "GRADE", "SOURCE", "RECOVERY", "TASK_AGENT"}:
            raise LearningLoopError("INVALID_RELIABILITY_STAGE")
        if status not in {"STARTED", "SUCCEEDED", "FAILED", "IN_FLIGHT", "CANCELLED", "UNKNOWN"}:
            raise LearningLoopError("INVALID_RELIABILITY_STATUS")
        if latency_ms is not None and latency_ms < 0:
            raise LearningLoopError("INVALID_RELIABILITY_LATENCY")
        terminal = {"SUCCEEDED", "FAILED", "CANCELLED", "UNKNOWN"}
        old = connection.execute(
            "SELECT * FROM learning_loop_reliability_facts WHERE operation_id=? AND stage=? "
            "AND status IN ('SUCCEEDED','FAILED','CANCELLED','UNKNOWN')",
            (operation_id, stage),
        ).fetchone()
        if old is not None:
            if old["status"] != status or old["owner_user_id"] != owner_user_id:
                raise LearningLoopError("RELIABILITY_FINAL_CONFLICT")
            return _dict(old)
        fact_id = _id("reliability")
        connection.execute(
            "INSERT OR IGNORE INTO learning_loop_reliability_facts("
            "id,owner_user_id,cycle_id,operation_id,stage,status,latency_ms) "
            "VALUES(?,?,?,?,?,?,?)",
            (fact_id, owner_user_id, cycle_id, operation_id, stage, status, latency_ms),
        )
        if status not in terminal:
            return {"id": fact_id, "status": status, "stage": stage}
        row = connection.execute(
            "SELECT * FROM learning_loop_reliability_facts WHERE operation_id=? "
            "AND stage=? AND status=?",
            (operation_id, stage, status),
        ).fetchone()
        return _dict(row)

    def record_reliability(
        self, *, owner_user_id: str, cycle_id: str | None, operation_id: str,
        stage: str, status: str, latency_ms: int | None = None,
    ) -> dict[str, Any]:
        operation_id = self._stable_operation(operation_id)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if cycle_id is not None:
                self._cycle(connection, owner_user_id, cycle_id)
            return self._record_reliability_in_connection(
                connection, owner_user_id=owner_user_id, cycle_id=cycle_id,
                operation_id=operation_id, stage=stage, status=status,
                latency_ms=latency_ms,
            )

    @staticmethod
    def _workspace(
        connection: sqlite3.Connection, owner_user_id: str, course_id: str
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM learning_workspaces WHERE owner_user_id=? AND course_id=?",
            (owner_user_id, course_id),
        ).fetchone()
        if row is None:
            raise LearningLoopError("WORKSPACE_NOT_FOUND")
        return row

    @staticmethod
    def _cycle(
        connection: sqlite3.Connection, owner_user_id: str, cycle_id: str
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM learning_loop_cycles WHERE id=? AND owner_user_id=?",
            (cycle_id, owner_user_id),
        ).fetchone()
        if row is None:
            raise LearningLoopError("NOT_FOUND")
        return row

    @staticmethod
    def _question(
        connection: sqlite3.Connection,
        *,
        owner_user_id: str,
        workspace_id: str,
        question_revision_id: str,
    ) -> dict[str, Any]:
        row = connection.execute(
            "SELECT question.id,question.course_id,question.owner_user_id,question.family_id,"
            "question.content_hash,question.created_at,question.prompt_text,provenance.node_id,"
            "provenance.spec_version,provenance.objective_id,provenance.blueprint_hash,"
            "provenance.publication_status "
            "FROM assessment_question_revisions AS question "
            "JOIN question_engine_provenance AS provenance "
            "ON provenance.question_revision_id=question.id "
            "JOIN learning_workspaces AS workspace ON workspace.id=provenance.workspace_id "
            "WHERE question.id=? AND provenance.workspace_id=? "
            "AND question.owner_user_id=? AND workspace.owner_user_id=? "
            "AND provenance.publication_status='READY'",
            (question_revision_id, workspace_id, owner_user_id, owner_user_id),
        ).fetchone()
        if row is None:
            raise LearningLoopError("QUESTION_NOT_AVAILABLE")
        criteria = [
            _dict(item)
            for item in connection.execute(
                "SELECT criterion_id,node_id,spec_version,item_id,dimension,description,"
                "max_fraction FROM assessment_rubric_criteria "
                "WHERE question_revision_id=? ORDER BY criterion_id",
                (question_revision_id,),
            ).fetchall()
        ]
        if not criteria:
            raise LearningLoopError("RUBRIC_NOT_AVAILABLE")
        return _dict(row) | {
            "rubric_revision": _digest(criteria),
            "family_evidence_ref": f"question-provenance:{question_revision_id}:{row['blueprint_hash']}",
        }

    @staticmethod
    def _active_target(
        connection: sqlite3.Connection,
        *,
        course_id: str,
        node_id: str,
        spec_version: int,
        objective_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT pack.*,target.node_id,target.spec_version,target.objective_id "
            "FROM learning_loop_pack_revisions AS pack "
            "JOIN learning_loop_pack_targets AS target ON target.pack_revision_id=pack.id "
            "JOIN learning_loop_course_flags AS flag ON flag.course_id=pack.course_id "
            "WHERE pack.course_id=? AND pack.status='ACTIVE' AND flag.enabled=1 "
            "AND target.node_id=? AND target.spec_version=? AND target.objective_id=?",
            (course_id, node_id, spec_version, objective_id),
        ).fetchone()
        if row is None:
            raise LearningLoopError("LEARNING_LOOP_NOT_ACTIVE_FOR_TARGET")
        return row

    def _is_internal(self, connection: sqlite3.Connection, owner_user_id: str) -> bool:
        if self.test_environment or owner_user_id in self.internal_user_ids:
            return True
        row = connection.execute(
            "SELECT internal FROM learning_loop_actor_classifications WHERE owner_user_id=?",
            (owner_user_id,),
        ).fetchone()
        return bool(row and row["internal"])

    @staticmethod
    def _related(left: sqlite3.Row | dict[str, Any], right: dict[str, Any]) -> bool:
        return (
            str(left["question_revision_id"] if "question_revision_id" in left.keys() else left["id"])
            == str(right["id"])
            or str(left["family_id"]) == str(right["family_id"])
            or str(left["question_content_hash"] if "question_content_hash" in left.keys() else left["content_hash"])
            == str(right["content_hash"])
        )

    def start(
        self,
        *,
        owner_user_id: str,
        operation_id: str,
        course_id: str,
        pair_ref: str,
        node_id: str,
        initial_question_revision_id: str,
    ) -> dict[str, Any]:
        operation_id = self._stable_operation(operation_id)
        payload = {
            "course_id": course_id,
            "pair_ref": pair_ref,
            "node_id": node_id,
            "initial_question_revision_id": initial_question_revision_id,
        }
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            workspace = self._workspace(connection, owner_user_id, course_id)
            question = self._question(
                connection,
                owner_user_id=owner_user_id,
                workspace_id=str(workspace["id"]),
                question_revision_id=initial_question_revision_id,
            )
            if question["node_id"] != node_id:
                raise LearningLoopError("QUESTION_SCOPE_MISMATCH")
            pack = self._active_target(
                connection,
                course_id=course_id,
                node_id=node_id,
                spec_version=int(question["spec_version"]),
                objective_id=str(question["objective_id"]),
            )
            replay = self._command_replay(
                connection, owner_user_id=owner_user_id, operation_id=operation_id,
                action="START", payload=payload,
            )
            if replay is not None:
                self._cycle(connection, owner_user_id, str(replay["id"]))
                return replay
            flag = connection.execute(
                "SELECT history_complete_from FROM learning_loop_course_flags WHERE course_id=?",
                (course_id,),
            ).fetchone()
            history_complete = bool(
                flag and flag["history_complete_from"]
                and str(question["created_at"]) >= str(flag["history_complete_from"])
            )
            cycle_id = _id("cycle")
            connection.execute(
                "INSERT INTO learning_loop_cycles("
                "id,owner_user_id,workspace_id,course_id,offering_id,pair_ref,node_id,"
                "spec_version,objective_id,pack_revision_id,state,internal,history_complete) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,'STARTED',?,?)",
                (
                    cycle_id, owner_user_id, workspace["id"], course_id, pack["offering_id"],
                    pair_ref, node_id, question["spec_version"], question["objective_id"],
                    pack["id"], int(self._is_internal(connection, owner_user_id)),
                    int(history_complete),
                ),
            )
            self._event(
                connection, owner_user_id=owner_user_id, workspace_id=str(workspace["id"]),
                cycle_id=cycle_id, kind="CYCLE_STARTED",
                payload={"course_id": course_id, "node_id": node_id, "pack_revision": pack["id"]},
            )
            assignment = self._assign_in_connection(
                connection,
                owner_user_id=owner_user_id,
                cycle_id=cycle_id,
                question=question,
                purpose="INITIAL",
                receipt=f"assignment:{operation_id}:initial",
            )
            self._record_reliability_in_connection(
                connection, owner_user_id=owner_user_id, cycle_id=cycle_id,
                operation_id=operation_id, stage="SOURCE", status="SUCCEEDED",
            )
            result = {
                "id": cycle_id,
                "state": "PRACTICING",
                "course_id": course_id,
                "node_id": node_id,
                "spec_version": int(question["spec_version"]),
                "objective_id": question["objective_id"],
                "pack_revision_id": pack["id"],
                "initial_assignment": assignment,
            }
            return self._remember(
                connection, owner_user_id=owner_user_id, operation_id=operation_id,
                action="START", payload=payload, result=result,
            )

    def _assign_in_connection(
        self,
        connection: sqlite3.Connection,
        *,
        owner_user_id: str,
        cycle_id: str,
        question: dict[str, Any],
        purpose: Literal["INITIAL", "DIAGNOSTIC", "TRANSFER", "RECHECK"],
        receipt: str,
    ) -> dict[str, Any]:
        cycle = self._cycle(connection, owner_user_id, cycle_id)
        if cycle["completed_at"] is not None:
            raise LearningLoopError("CYCLE_TERMINAL_USE_NEW_CYCLE")
        if cycle["state"] == "PAUSED":
            raise LearningLoopError("CYCLE_PAUSED")
        if (
            question["node_id"] != cycle["node_id"]
            or int(question["spec_version"]) != int(cycle["spec_version"])
            or question["objective_id"] != cycle["objective_id"]
        ):
            raise LearningLoopError("SCOPE_MISMATCH")
        if purpose in {"TRANSFER", "RECHECK"}:
            feedback = connection.execute(
                "SELECT feedback.* FROM learning_loop_feedback_deliveries AS feedback "
                "JOIN learning_loop_submission_links AS link "
                "ON link.id=feedback.submission_link_id "
                "JOIN learning_loop_assignments AS assignment ON assignment.id=link.assignment_id "
                "WHERE feedback.cycle_id=? AND assignment.purpose='INITIAL' "
                "ORDER BY feedback.delivered_sequence DESC LIMIT 1",
                (cycle_id,),
            ).fetchone()
            if feedback is None:
                raise LearningLoopError("INITIAL_FEEDBACK_REQUIRED")
            prior = connection.execute(
                "SELECT * FROM learning_loop_exposures WHERE owner_user_id=? AND workspace_id=?",
                (owner_user_id, cycle["workspace_id"]),
            ).fetchall()
            if any(self._related(row, question) for row in prior):
                raise LearningLoopError("NOT_UNSEEN")
            if not question["family_evidence_ref"]:
                raise LearningLoopError("FAMILY_UNCONFIRMED")
        event_sequence = self._event(
            connection, owner_user_id=owner_user_id, workspace_id=str(cycle["workspace_id"]),
            cycle_id=cycle_id, kind="QUESTION_ASSIGNED",
            payload={
                "question_revision_id": question["id"], "family_id": question["family_id"],
                "purpose": purpose,
            },
        )
        assignment_id = _id("assignment")
        connection.execute(
            "INSERT INTO learning_loop_assignments("
            "id,cycle_id,owner_user_id,workspace_id,question_revision_id,family_id,"
            "question_content_hash,family_evidence_ref,purpose,assigned_sequence,history_complete) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                assignment_id, cycle_id, owner_user_id, cycle["workspace_id"], question["id"],
                question["family_id"], question["content_hash"], question["family_evidence_ref"],
                purpose, event_sequence, cycle["history_complete"],
            ),
        )
        exposure_sequence = self._record_exposure_in_connection(
            connection,
            owner_user_id=owner_user_id,
            workspace_id=str(cycle["workspace_id"]),
            question=question,
            kind="STEM",
            channel="QUESTION",
            receipt=receipt,
            assignment_id=assignment_id,
            ordering="SERVER_ORDERED",
        )
        state = "TRANSFER_READY" if purpose in {"TRANSFER", "RECHECK"} else "PRACTICING"
        connection.execute(
            "UPDATE learning_loop_cycles SET state=?,revision=revision+1 WHERE id=?",
            (state, cycle_id),
        )
        return {
            "id": assignment_id,
            "cycle_id": cycle_id,
            "question_revision_id": question["id"],
            "family_id": question["family_id"],
            "purpose": purpose,
            "exposure_sequence": exposure_sequence,
        }

    def assign(
        self,
        *,
        owner_user_id: str,
        operation_id: str,
        cycle_id: str,
        question_revision_id: str,
        purpose: Literal["INITIAL", "DIAGNOSTIC", "TRANSFER", "RECHECK"] = "TRANSFER",
    ) -> dict[str, Any]:
        operation_id = self._stable_operation(operation_id)
        payload = {
            "cycle_id": cycle_id,
            "question_revision_id": question_revision_id,
            "purpose": purpose,
        }
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cycle = self._cycle(connection, owner_user_id, cycle_id)
            question = self._question(
                connection,
                owner_user_id=owner_user_id,
                workspace_id=str(cycle["workspace_id"]),
                question_revision_id=question_revision_id,
            )
            replay = self._command_replay(
                connection, owner_user_id=owner_user_id, operation_id=operation_id,
                action="ASSIGN", payload=payload,
            )
            if replay is not None:
                return replay
            result = self._assign_in_connection(
                connection,
                owner_user_id=owner_user_id,
                cycle_id=cycle_id,
                question=question,
                purpose=purpose,
                receipt=f"assignment:{operation_id}",
            )
            return self._remember(
                connection, owner_user_id=owner_user_id, operation_id=operation_id,
                action="ASSIGN", payload=payload, result=result,
            )

    def configure_diagnostic(
        self,
        *,
        owner_user_id: str,
        operation_id: str,
        cycle_id: str,
    ) -> dict[str, Any]:
        """Expose exactly three optional practice items without changing formal assessment."""

        operation_id = self._stable_operation(operation_id)
        payload = {"cycle_id": cycle_id}
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cycle = self._cycle(connection, owner_user_id, cycle_id)
            replay = self._command_replay(
                connection,
                owner_user_id=owner_user_id,
                operation_id=operation_id,
                action="DIAGNOSTIC_CONFIGURE",
                payload=payload,
            )
            if replay is not None:
                return replay
            if cycle["completed_at"] is not None:
                raise LearningLoopError("CYCLE_TERMINAL_USE_NEW_CYCLE")
            if cycle["diagnostic_status"] != "NOT_STARTED":
                raise LearningLoopError("DIAGNOSTIC_ALREADY_DECIDED")
            prior = connection.execute(
                "SELECT * FROM learning_loop_exposures WHERE owner_user_id=? "
                "AND workspace_id=? ORDER BY sequence",
                (owner_user_id, cycle["workspace_id"]),
            ).fetchall()
            rows = connection.execute(
                "SELECT question.id FROM assessment_question_revisions AS question "
                "JOIN question_engine_provenance AS provenance "
                "ON provenance.question_revision_id=question.id "
                "WHERE provenance.workspace_id=? AND question.owner_user_id=? "
                "AND provenance.node_id=? AND provenance.spec_version=? "
                "AND provenance.objective_id=? AND provenance.publication_status='READY' "
                "ORDER BY question.created_at,question.id",
                (
                    cycle["workspace_id"], owner_user_id, cycle["node_id"],
                    cycle["spec_version"], cycle["objective_id"],
                ),
            ).fetchall()
            candidates: list[dict[str, Any]] = []
            used_families: set[str] = set()
            for row in rows:
                question = self._question(
                    connection,
                    owner_user_id=owner_user_id,
                    workspace_id=str(cycle["workspace_id"]),
                    question_revision_id=str(row["id"]),
                )
                if question["family_id"] in used_families:
                    continue
                if any(self._related(exposure, question) for exposure in prior):
                    continue
                candidates.append(question)
                used_families.add(str(question["family_id"]))
                if len(candidates) == 3:
                    break
            if len(candidates) != 3:
                raise LearningLoopError("DIAGNOSTIC_WAITING_FOR_THREE_UNSEEN_FAMILIES")
            items = []
            for index, question in enumerate(candidates, start=1):
                assignment = self._assign_in_connection(
                    connection,
                    owner_user_id=owner_user_id,
                    cycle_id=cycle_id,
                    question=question,
                    purpose="DIAGNOSTIC",
                    receipt=f"diagnostic:{operation_id}:{index}",
                )
                items.append(
                    {
                        **assignment,
                        "prompt": question["prompt_text"],
                        "unsure_is_not_scored_zero": True,
                    }
                )
            connection.execute(
                "UPDATE learning_loop_cycles SET state='DIAGNOSING',diagnostic_status='AVAILABLE',"
                "diagnostic_questions_json=?,revision=revision+1 WHERE id=?",
                (_canonical(items), cycle_id),
            )
            result = {
                "cycle_id": cycle_id,
                "status": "AVAILABLE",
                "purpose": "PRACTICE_NOT_FORMAL_ASSESSMENT",
                "skippable": True,
                "items": items,
            }
            return self._remember(
                connection,
                owner_user_id=owner_user_id,
                operation_id=operation_id,
                action="DIAGNOSTIC_CONFIGURE",
                payload=payload,
                result=result,
            )

    def skip_diagnostic(
        self,
        *,
        owner_user_id: str,
        operation_id: str,
        cycle_id: str,
    ) -> dict[str, Any]:
        operation_id = self._stable_operation(operation_id)
        payload = {"cycle_id": cycle_id}
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cycle = self._cycle(connection, owner_user_id, cycle_id)
            replay = self._command_replay(
                connection,
                owner_user_id=owner_user_id,
                operation_id=operation_id,
                action="DIAGNOSTIC_SKIP",
                payload=payload,
            )
            if replay is not None:
                return replay
            if cycle["completed_at"] is not None:
                raise LearningLoopError("CYCLE_TERMINAL_USE_NEW_CYCLE")
            if cycle["diagnostic_status"] == "COMPLETED":
                raise LearningLoopError("DIAGNOSTIC_ALREADY_COMPLETED")
            connection.execute(
                "UPDATE learning_loop_cycles SET state='DIRECT_PRACTICE',"
                "diagnostic_status='SKIPPED',revision=revision+1 WHERE id=?",
                (cycle_id,),
            )
            self._event(
                connection,
                owner_user_id=owner_user_id,
                workspace_id=str(cycle["workspace_id"]),
                cycle_id=cycle_id,
                kind="DIAGNOSTIC_SKIPPED",
                payload={"formal_assessment_changed": False},
            )
            return self._remember(
                connection,
                owner_user_id=owner_user_id,
                operation_id=operation_id,
                action="DIAGNOSTIC_SKIP",
                payload=payload,
                result={"cycle_id": cycle_id, "status": "SKIPPED"},
            )

    def record_diagnostic_unsure(
        self,
        *,
        owner_user_id: str,
        operation_id: str,
        cycle_id: str,
        assignment_id: str,
    ) -> dict[str, Any]:
        """Record an explicit UNSURE response without creating a graded attempt."""

        operation_id = self._stable_operation(operation_id)
        payload = {"cycle_id": cycle_id, "assignment_id": assignment_id}
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cycle = self._cycle(connection, owner_user_id, cycle_id)
            replay = self._command_replay(
                connection,
                owner_user_id=owner_user_id,
                operation_id=operation_id,
                action="DIAGNOSTIC_UNSURE",
                payload=payload,
            )
            if replay is not None:
                return replay
            if cycle["completed_at"] is not None:
                raise LearningLoopError("CYCLE_TERMINAL_USE_NEW_CYCLE")
            assignment = connection.execute(
                "SELECT * FROM learning_loop_assignments WHERE id=? AND cycle_id=? "
                "AND owner_user_id=?",
                (assignment_id, cycle_id, owner_user_id),
            ).fetchone()
            if assignment is None:
                raise LearningLoopError("NOT_FOUND")
            if assignment["purpose"] != "DIAGNOSTIC":
                raise LearningLoopError("DIAGNOSTIC_ONLY")
            if cycle["diagnostic_status"] not in {"AVAILABLE", "COMPLETED"}:
                raise LearningLoopError("DIAGNOSTIC_NOT_AVAILABLE")
            responses = dict(json.loads(cycle["diagnostic_responses_json"]))
            question_revision_id = str(assignment["question_revision_id"])
            if question_revision_id in responses:
                result = {
                    "cycle_id": cycle_id,
                    "status": cycle["diagnostic_status"],
                    "responses": responses,
                    "formal_assessment_changed": False,
                }
                return self._remember(
                    connection,
                    owner_user_id=owner_user_id,
                    operation_id=operation_id,
                    action="DIAGNOSTIC_UNSURE",
                    payload=payload,
                    result=result,
                )
            responses[question_revision_id] = "UNSURE"
            completed = len(responses) == 3
            connection.execute(
                "UPDATE learning_loop_cycles SET diagnostic_responses_json=?,"
                "diagnostic_status=?,state=?,revision=revision+1 WHERE id=?",
                (
                    _canonical(responses),
                    "COMPLETED" if completed else "AVAILABLE",
                    "DIRECT_PRACTICE" if completed else "DIAGNOSING",
                    cycle_id,
                ),
            )
            self._event(
                connection,
                owner_user_id=owner_user_id,
                workspace_id=str(cycle["workspace_id"]),
                cycle_id=cycle_id,
                kind="DIAGNOSTIC_UNSURE",
                payload={
                    "assignment_id": assignment_id,
                    "question_revision_id": question_revision_id,
                    "not_a_grade": True,
                },
            )
            result = {
                "cycle_id": cycle_id,
                "status": "COMPLETED" if completed else "AVAILABLE",
                "responses": responses,
                "formal_assessment_changed": False,
            }
            return self._remember(
                connection,
                owner_user_id=owner_user_id,
                operation_id=operation_id,
                action="DIAGNOSTIC_UNSURE",
                payload=payload,
                result=result,
            )

    @staticmethod
    def _record_exposure_in_connection(
        connection: sqlite3.Connection,
        *,
        owner_user_id: str,
        workspace_id: str,
        question: dict[str, Any],
        kind: str,
        channel: str,
        receipt: str,
        assignment_id: str | None,
        ordering: str,
    ) -> int:
        existing = connection.execute(
            "SELECT * FROM learning_loop_exposures WHERE owner_user_id=? AND receipt=?",
            (owner_user_id, receipt),
        ).fetchone()
        if existing is not None:
            expected = (
                workspace_id, question["id"], question["family_id"], kind, channel,
                assignment_id, ordering,
            )
            actual = (
                existing["workspace_id"], existing["question_revision_id"],
                existing["family_id"], existing["kind"], existing["channel"],
                existing["assignment_id"], existing["ordering"],
            )
            if actual != expected:
                raise LearningLoopError("EXPOSURE_RECEIPT_CONFLICT")
            return int(existing["sequence"])
        cursor = connection.execute(
            "INSERT INTO learning_loop_exposures("
            "id,owner_user_id,workspace_id,question_revision_id,family_id,"
            "question_content_hash,kind,channel,assignment_id,ordering,receipt) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                _id("exposure"), owner_user_id, workspace_id, question["id"],
                question["family_id"], question["content_hash"], kind, channel,
                assignment_id, ordering, receipt,
            ),
        )
        return int(cursor.lastrowid)

    def record_exposure(
        self,
        *,
        owner_user_id: str,
        operation_id: str,
        question_revision_id: str,
        kind: ExposureKind,
        channel: ExposureChannel,
        receipt: str,
        assignment_id: str | None = None,
        ordering: Literal["SERVER_ORDERED", "LATE_UNORDERED"] = "SERVER_ORDERED",
    ) -> dict[str, Any]:
        operation_id = self._stable_operation(operation_id)
        if kind not in _KINDS or channel not in _CHANNELS:
            raise LearningLoopError("TYPED_EXPOSURE_REQUIRED")
        if ordering not in {"SERVER_ORDERED", "LATE_UNORDERED"}:
            raise LearningLoopError("INVALID_ORDERING")
        payload = {
            "question_revision_id": question_revision_id,
            "kind": kind,
            "channel": channel,
            "receipt": receipt,
            "assignment_id": assignment_id,
            "ordering": ordering,
        }
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if assignment_id:
                assignment = connection.execute(
                    "SELECT * FROM learning_loop_assignments WHERE id=? AND owner_user_id=?",
                    (assignment_id, owner_user_id),
                ).fetchone()
                if assignment is None:
                    raise LearningLoopError("NOT_FOUND")
                workspace_id = str(assignment["workspace_id"])
            else:
                provenance = connection.execute(
                    "SELECT workspace_id FROM question_engine_provenance "
                    "WHERE question_revision_id=?", (question_revision_id,),
                ).fetchone()
                if provenance is None:
                    raise LearningLoopError("QUESTION_NOT_AVAILABLE")
                workspace_id = str(provenance["workspace_id"])
            question = self._question(
                connection, owner_user_id=owner_user_id, workspace_id=workspace_id,
                question_revision_id=question_revision_id,
            )
            replay = self._command_replay(
                connection, owner_user_id=owner_user_id, operation_id=operation_id,
                action="EXPOSURE", payload=payload,
            )
            if replay is not None:
                return replay
            if assignment_id and not self._related(assignment, question):
                raise LearningLoopError("ASSIGNMENT_EXPOSURE_MISMATCH")
            sequence = self._record_exposure_in_connection(
                connection,
                owner_user_id=owner_user_id,
                workspace_id=workspace_id,
                question=question,
                kind=kind,
                channel=channel,
                receipt=receipt,
                assignment_id=assignment_id,
                ordering=ordering,
            )
            cycle_id = str(assignment["cycle_id"]) if assignment_id else None
            self._event(
                connection, owner_user_id=owner_user_id, workspace_id=workspace_id,
                cycle_id=cycle_id, kind="EXPOSURE_RECORDED",
                payload={
                    "question_revision_id": question_revision_id, "kind": kind,
                    "channel": channel, "receipt": receipt, "ordering": ordering,
                },
            )
            result = {
                "sequence": sequence,
                "question_revision_id": question_revision_id,
                "kind": kind,
                "channel": channel,
                "ordering": ordering,
            }
            return self._remember(
                connection, owner_user_id=owner_user_id, operation_id=operation_id,
                action="EXPOSURE", payload=payload, result=result,
            )

    @staticmethod
    def _assistance_snapshot(
        connection: sqlite3.Connection,
        *,
        assignment: sqlite3.Row,
        frozen_sequence: int,
    ) -> tuple[str, list[str]]:
        related = connection.execute(
            "SELECT * FROM learning_loop_exposures WHERE owner_user_id=? AND workspace_id=? "
            "AND sequence<=? AND (question_revision_id=? OR family_id=? OR question_content_hash=?) "
            "ORDER BY sequence",
            (
                assignment["owner_user_id"], assignment["workspace_id"], frozen_sequence,
                assignment["question_revision_id"], assignment["family_id"],
                assignment["question_content_hash"],
            ),
        ).fetchall()
        reasons: list[str] = []
        assistance = "NONE"
        if not assignment["history_complete"]:
            reasons.append("EXPOSURE_HISTORY_UNCERTAIN")
        for exposure in related:
            if exposure["ordering"] == "LATE_UNORDERED":
                reasons.append("EXPOSURE_ORDER_UNCERTAIN")
            if exposure["kind"] == "STEM" and exposure["assignment_id"] == assignment["id"]:
                continue
            if exposure["kind"] in {"SOLUTION", "DETAIL"}:
                assistance = "ANSWER_REVEALED"
            elif assistance == "NONE":
                assistance = "HINT"
            reasons.append("HELP_BEFORE_SUBMISSION")
        return assistance, list(dict.fromkeys(reasons))

    def record_submission(
        self,
        *,
        owner_user_id: str,
        operation_id: str,
        assignment_id: str,
        answer: str,
    ) -> dict[str, Any]:
        operation_id = self._stable_operation(operation_id)
        answer = answer.strip()
        if not 1 <= len(answer) <= 6000:
            raise LearningLoopError("PRACTICE_ANSWER_INVALID")
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            assignment = connection.execute(
                "SELECT * FROM learning_loop_assignments WHERE id=? AND owner_user_id=?",
                (assignment_id, owner_user_id),
            ).fetchone()
            if assignment is None:
                raise LearningLoopError("NOT_FOUND")
            return self.record_submission_in_transaction(
                connection,
                owner_user_id=owner_user_id,
                operation_id=operation_id,
                assignment=assignment,
                answer=answer,
            )

    def record_submission_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        owner_user_id: str,
        operation_id: str,
        assignment: sqlite3.Row,
        answer: str,
    ) -> dict[str, Any]:
        payload = {"assignment_id": assignment["id"], "answer_hash": sha256(answer.encode()).hexdigest()}
        replay = self._command_replay(
            connection, owner_user_id=owner_user_id, operation_id=operation_id,
            action="SUBMIT", payload=payload,
        )
        if replay is not None:
            return replay
        cycle = self._cycle(connection, owner_user_id, str(assignment["cycle_id"]))
        question = self._question(
            connection,
            owner_user_id=owner_user_id,
            workspace_id=str(assignment["workspace_id"]),
            question_revision_id=str(assignment["question_revision_id"]),
        )
        frozen_sequence = int(
            connection.execute(
                "SELECT COALESCE(MAX(sequence),0) FROM learning_loop_exposures "
                "WHERE owner_user_id=? AND workspace_id=?",
                (owner_user_id, assignment["workspace_id"]),
            ).fetchone()[0]
        )
        assistance, reasons = self._assistance_snapshot(
            connection, assignment=assignment, frozen_sequence=frozen_sequence
        )
        input_hash = _digest(
            {
                "question_revision_id": question["id"],
                "answer_hash": payload["answer_hash"],
                "rubric_revision": question["rubric_revision"],
                "frozen_exposure_sequence": frozen_sequence,
            }
        )
        inserted = connection.execute(
            "INSERT OR IGNORE INTO practice_interaction_operations("
            "workspace_id,operation_id,question_revision_id,owner_user_id,kind,input_hash,status) "
            "VALUES(?,?,?,?,? ,?,'CLAIMED')",
            (
                assignment["workspace_id"], operation_id, question["id"], owner_user_id,
                "ATTEMPT", input_hash,
            ),
        ).rowcount
        if inserted != 1:
            raise LearningLoopError("PRACTICE_IDEMPOTENCY_CONFLICT")
        connection.execute(
            "INSERT INTO practice_operation_metering_guards("
            "workspace_id,operation_id,guard_version) VALUES(?,?,'metered-practice.v1')",
            (assignment["workspace_id"], operation_id),
        )
        canonical_submission_id = _id("practice_submission")
        connection.execute(
            "INSERT INTO practice_submission_revisions("
            "id,workspace_id,question_revision_id,owner_user_id,operation_id,submitted_answer,"
            "answer_hash,rubric_revision,assistance,exposure_sequence,substantive) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,1)",
            (
                canonical_submission_id, assignment["workspace_id"], question["id"],
                owner_user_id, operation_id, answer, payload["answer_hash"],
                question["rubric_revision"], assistance, frozen_sequence,
            ),
        )
        connection.execute(
            "INSERT INTO practice_evaluation_jobs("
            "submission_id,workspace_id,operation_id,status) VALUES(?,?,?,'PENDING')",
            (canonical_submission_id, assignment["workspace_id"], operation_id),
        )
        saved_sequence = self._event(
            connection, owner_user_id=owner_user_id,
            workspace_id=str(assignment["workspace_id"]), cycle_id=str(cycle["id"]),
            kind="SUBMISSION_SAVED",
            payload={
                "canonical_submission_id": canonical_submission_id,
                "assignment_id": assignment["id"], "answer_revision": 1,
                "frozen_exposure_sequence": frozen_sequence,
            },
        )
        link_id = _id("submission_link")
        connection.execute(
            "INSERT INTO learning_loop_submission_links("
            "id,cycle_id,assignment_id,owner_user_id,canonical_submission_id,"
            "frozen_exposure_sequence,independent_at_submission,eligibility_reasons_json,"
            "saved_sequence) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                link_id, cycle["id"], assignment["id"], owner_user_id,
                canonical_submission_id, frozen_sequence, int(not reasons), _canonical(reasons),
                saved_sequence,
            ),
        )
        connection.execute(
            "UPDATE learning_loop_cycles SET state='SAVED_AWAITING_EVALUATION',"
            "revision=revision+1 WHERE id=? AND state!='COMPLETED'",
            (cycle["id"],),
        )
        self._record_reliability_in_connection(
            connection, owner_user_id=owner_user_id, cycle_id=str(cycle["id"]),
            operation_id=operation_id, stage="SAVE", status="SUCCEEDED",
        )
        result = {
            "id": link_id,
            "canonical_submission_id": canonical_submission_id,
            "cycle_id": cycle["id"],
            "assignment_id": assignment["id"],
            "status": "PENDING",
            "assistance": assistance,
            "independent_at_submission": not reasons,
            "eligibility_reasons": reasons,
            "frozen_exposure_sequence": frozen_sequence,
        }
        return self._remember(
            connection, owner_user_id=owner_user_id, operation_id=operation_id,
            action="SUBMIT", payload=payload, result=result,
        )

    def record_evaluation(
        self,
        *,
        owner_user_id: str,
        operation_id: str,
        canonical_submission_id: str,
        outcome: Literal["CORRECT", "PARTIAL", "INCORRECT", "NEEDS_REVIEW"],
    ) -> dict[str, Any]:
        """Offline adapter used by deterministic tests; live paths attach provider receipts."""
        if not self.test_environment:
            raise LearningLoopError("TEST_EVALUATION_DISABLED")
        operation_id = self._stable_operation(operation_id)
        payload = {
            "canonical_submission_id": canonical_submission_id,
            "outcome": outcome,
        }
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._command_replay(
                connection,
                owner_user_id=owner_user_id,
                operation_id=operation_id,
                action="EVALUATE_TEST",
                payload=payload,
            )
            if replay is not None:
                return replay
            submission = connection.execute(
                "SELECT * FROM practice_submission_revisions WHERE id=? AND owner_user_id=?",
                (canonical_submission_id, owner_user_id),
            ).fetchone()
            if submission is None:
                raise LearningLoopError("NOT_FOUND")
            attempt_id = _id("practice_attempt")
            feedback = {
                "verdict": outcome,
                "feedback": "Deterministic offline evaluation.",
                "strengths": [],
                "gaps": [],
                "next_step": "Continue the learning loop.",
                "criteria": [],
            }
            connection.execute(
                "INSERT INTO practice_question_attempts("
                "id,workspace_id,question_revision_id,owner_user_id,operation_id,input_hash,"
                "submitted_answer,assistance,status,feedback_json,provider_run_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    attempt_id, submission["workspace_id"], submission["question_revision_id"],
                    owner_user_id, submission["operation_id"],
                    connection.execute(
                        "SELECT input_hash FROM practice_interaction_operations "
                        "WHERE workspace_id=? AND operation_id=?",
                        (submission["workspace_id"], submission["operation_id"]),
                    ).fetchone()[0],
                    submission["submitted_answer"], submission["assistance"],
                    "NEEDS_REVIEW" if outcome == "NEEDS_REVIEW" else "GRADED",
                    _canonical(feedback), _canonical({"mode": "offline-contract"}),
                ),
            )
            result = {
                "id": attempt_id, "verdict": outcome,
                "status": "NEEDS_REVIEW" if outcome == "NEEDS_REVIEW" else "GRADED",
                "assistance": submission["assistance"],
                "independent": submission["assistance"] == "NONE",
            }
            connection.execute(
                "UPDATE practice_interaction_operations SET status='COMPLETED',result_json=?,"
                "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                "WHERE workspace_id=? AND operation_id=? AND status='CLAIMED'",
                (_canonical(result), submission["workspace_id"], submission["operation_id"]),
            )
            connection.execute(
                "UPDATE practice_evaluation_jobs SET status='COMPLETED',lease_owner=NULL,"
                "lease_expires_at=NULL,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                "WHERE submission_id=?", (canonical_submission_id,),
            )
            linked = self.attach_evaluation_in_transaction(
                connection,
                owner_user_id=owner_user_id,
                canonical_submission_id=canonical_submission_id,
                canonical_evaluation_id=attempt_id,
                outcome=outcome,
            )
            return self._remember(
                connection,
                owner_user_id=owner_user_id,
                operation_id=operation_id,
                action="EVALUATE_TEST",
                payload=payload,
                result=linked,
            )

    def attach_evaluation_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        owner_user_id: str,
        canonical_submission_id: str,
        canonical_evaluation_id: str,
        outcome: str,
    ) -> dict[str, Any]:
        link = connection.execute(
            "SELECT link.*,assignment.question_revision_id FROM learning_loop_submission_links AS link "
            "JOIN learning_loop_assignments AS assignment ON assignment.id=link.assignment_id "
            "WHERE link.canonical_submission_id=? AND link.owner_user_id=?",
            (canonical_submission_id, owner_user_id),
        ).fetchone()
        if link is None:
            return {"linked": False, "reason": "NO_LEARNING_LOOP_SUBMISSION"}
        attempt = connection.execute(
            "SELECT * FROM practice_question_attempts WHERE id=? AND owner_user_id=?",
            (canonical_evaluation_id, owner_user_id),
        ).fetchone()
        submission = connection.execute(
            "SELECT * FROM practice_submission_revisions WHERE id=? AND owner_user_id=?",
            (canonical_submission_id, owner_user_id),
        ).fetchone()
        if (
            attempt is None or submission is None
            or attempt["question_revision_id"] != submission["question_revision_id"]
            or attempt["operation_id"] != submission["operation_id"]
            or attempt["submitted_answer"] != submission["submitted_answer"]
        ):
            raise LearningLoopError("EVALUATION_BINDING_MISMATCH")
        existing = connection.execute(
            "SELECT * FROM learning_loop_evaluation_links WHERE canonical_evaluation_id=?",
            (canonical_evaluation_id,),
        ).fetchone()
        if existing is not None:
            return _dict(existing)
        status = "NEEDS_REVIEW" if outcome == "NEEDS_REVIEW" else "VALID"
        sequence = self._event(
            connection, owner_user_id=owner_user_id,
            workspace_id=str(submission["workspace_id"]), cycle_id=str(link["cycle_id"]),
            kind="EVALUATION_ATTACHED",
            payload={
                "canonical_submission_id": canonical_submission_id,
                "canonical_evaluation_id": canonical_evaluation_id,
                "status": status,
            },
        )
        evaluation_link_id = _id("evaluation_link")
        connection.execute(
            "INSERT INTO learning_loop_evaluation_links("
            "id,submission_link_id,canonical_evaluation_id,owner_user_id,outcome,status,"
            "evaluation_sequence) VALUES(?,?,?,?,?,?,?)",
            (
                evaluation_link_id, link["id"], canonical_evaluation_id, owner_user_id,
                outcome, status, sequence,
            ),
        )
        self._close_if_ready(connection, owner_user_id, str(link["cycle_id"]), str(link["id"]))
        self._record_reliability_in_connection(
            connection, owner_user_id=owner_user_id, cycle_id=str(link["cycle_id"]),
            operation_id=str(submission["operation_id"]), stage="GRADE", status="SUCCEEDED",
        )
        return {
            "id": evaluation_link_id,
            "canonical_evaluation_id": canonical_evaluation_id,
            "outcome": outcome,
            "status": status,
        }

    def deliver_feedback(
        self,
        *,
        owner_user_id: str,
        operation_id: str,
        cycle_id: str,
        canonical_submission_id: str,
        strategy_version: str,
        diagnosis_ref: str | None = None,
    ) -> dict[str, Any]:
        operation_id = self._stable_operation(operation_id)
        payload = {
            "cycle_id": cycle_id,
            "canonical_submission_id": canonical_submission_id,
            "strategy_version": strategy_version,
            "diagnosis_ref": diagnosis_ref,
        }
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cycle = self._cycle(connection, owner_user_id, cycle_id)
            link = connection.execute(
                "SELECT link.* FROM learning_loop_submission_links AS link "
                "WHERE link.cycle_id=? AND link.canonical_submission_id=? "
                "AND link.owner_user_id=?",
                (cycle_id, canonical_submission_id, owner_user_id),
            ).fetchone()
            if link is None:
                raise LearningLoopError("FEEDBACK_REQUIRES_SAVED_SUBSTANTIVE_ATTEMPT")
            evaluation = connection.execute(
                "SELECT * FROM learning_loop_evaluation_links WHERE submission_link_id=? "
                "ORDER BY evaluation_sequence DESC LIMIT 1", (link["id"],),
            ).fetchone()
            if evaluation is None:
                raise LearningLoopError("EVALUATION_REQUIRED")
            replay = self._command_replay(
                connection, owner_user_id=owner_user_id, operation_id=operation_id,
                action="FEEDBACK", payload=payload,
            )
            if replay is not None:
                return replay
            feedback_ref = f"practice-feedback:{evaluation['canonical_evaluation_id']}"
            sequence = self._event(
                connection, owner_user_id=owner_user_id,
                workspace_id=str(cycle["workspace_id"]), cycle_id=cycle_id,
                kind="FEEDBACK_DELIVERED",
                payload={
                    "canonical_feedback_ref": feedback_ref,
                    "canonical_submission_id": canonical_submission_id,
                    "strategy_version": strategy_version,
                },
            )
            delivery_id = _id("feedback")
            connection.execute(
                "INSERT INTO learning_loop_feedback_deliveries("
                "id,cycle_id,submission_link_id,owner_user_id,canonical_feedback_ref,"
                "strategy_version,diagnosis_ref,delivered_sequence) VALUES(?,?,?,?,?,?,?,?)",
                (
                    delivery_id, cycle_id, link["id"], owner_user_id, feedback_ref,
                    strategy_version, diagnosis_ref, sequence,
                ),
            )
            attempt = connection.execute(
                "SELECT attempt.feedback_json,submission.answer_hash,assignment.question_revision_id "
                "FROM learning_loop_evaluation_links AS evaluation "
                "JOIN practice_question_attempts AS attempt "
                "ON attempt.id=evaluation.canonical_evaluation_id "
                "JOIN practice_submission_revisions AS submission "
                "ON submission.id=? "
                "JOIN learning_loop_assignments AS assignment ON assignment.id=? "
                "WHERE evaluation.submission_link_id=?",
                (canonical_submission_id, link["assignment_id"], link["id"]),
            ).fetchone()
            diagnosis_ids: list[str] = []
            if attempt is not None:
                feedback = json.loads(attempt["feedback_json"])
                for criterion in feedback.get("criteria") or []:
                    if criterion.get("met") is not False:
                        continue
                    criterion_id = str(criterion.get("criterion_id") or "").strip()
                    rubric = connection.execute(
                        "SELECT node_id,spec_version,item_id FROM assessment_rubric_criteria "
                        "WHERE question_revision_id=? AND criterion_id=?",
                        (attempt["question_revision_id"], criterion_id),
                    ).fetchone()
                    if rubric is None:
                        continue
                    candidate_id = _id("diagnosis")
                    # The provider identified an unmet immutable rubric criterion, but
                    # did not supply a checker-bound answer substring.  Preserve the
                    # whole-answer hash and keep the candidate NEEDS_REVIEW instead of
                    # overstating a model suggestion as a verified misconception.
                    connection.execute(
                        "INSERT INTO learning_loop_diagnosis_candidates("
                        "id,cycle_id,owner_user_id,submission_link_id,answer_span_hash,"
                        "criterion_ref,source_rule_ref,alternative_refs_json,"
                        "proof_receipt_ref,status) VALUES(?,?,?,?,?,?,?,?,?,'NEEDS_REVIEW')",
                        (
                            candidate_id, cycle_id, owner_user_id, link["id"],
                            attempt["answer_hash"], criterion_id,
                            f"teaching-item:{rubric['node_id']}:{rubric['spec_version']}:"
                            f"{rubric['item_id']}",
                            _canonical(["ALTERNATIVE_REASONING", "TRANSCRIPTION_UNCERTAINTY"]),
                            f"practice-evaluation:{evaluation['canonical_evaluation_id']}",
                        ),
                    )
                    diagnosis_ids.append(candidate_id)
            intervention_id = _id("intervention")
            connection.execute(
                "INSERT INTO learning_loop_interventions("
                "id,cycle_id,owner_user_id,diagnosis_id,strategy_version,delivery_ref) "
                "VALUES(?,?,?,?,?,?)",
                (
                    intervention_id, cycle_id, owner_user_id,
                    diagnosis_ids[0] if diagnosis_ids else None,
                    strategy_version, feedback_ref,
                ),
            )
            connection.execute(
                "UPDATE learning_loop_cycles SET state='INTERVENTION_DELIVERED',"
                "revision=revision+1 WHERE id=? AND state!='COMPLETED'", (cycle_id,),
            )
            result = {
                "id": delivery_id,
                "canonical_feedback_ref": feedback_ref,
                "submission_link_id": link["id"],
                "delivered_sequence": sequence,
                "diagnosis_candidates": diagnosis_ids,
                "intervention_id": intervention_id,
            }
            return self._remember(
                connection, owner_user_id=owner_user_id, operation_id=operation_id,
                action="FEEDBACK", payload=payload, result=result,
            )

    def project_feedback_for_submission(
        self, *, owner_user_id: str, canonical_submission_id: str
    ) -> dict[str, Any] | None:
        """Record delivery immediately before returning feedback to its owner.

        The operation id is derived from the immutable submission reference, so
        polling, another pane and history restoration all converge on one
        delivery receipt instead of inflating intervention counts.
        """

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT link.cycle_id,evaluation.canonical_evaluation_id "
                "FROM learning_loop_submission_links AS link "
                "JOIN learning_loop_evaluation_links AS evaluation "
                "ON evaluation.submission_link_id=link.id "
                "WHERE link.canonical_submission_id=? AND link.owner_user_id=? "
                "ORDER BY evaluation.evaluation_sequence DESC LIMIT 1",
                (canonical_submission_id, owner_user_id),
            ).fetchone()
        if row is None:
            return None
        operation_id = "feedback-project-" + sha256(
            canonical_submission_id.encode("utf-8")
        ).hexdigest()
        return self.deliver_feedback(
            owner_user_id=owner_user_id,
            operation_id=operation_id,
            cycle_id=str(row["cycle_id"]),
            canonical_submission_id=canonical_submission_id,
            strategy_version="practice-feedback.v1",
        )

    @staticmethod
    def _correction_targets(connection: sqlite3.Connection) -> set[str]:
        result: set[str] = set()
        for row in connection.execute("SELECT target_ref,affected_refs_json FROM learning_loop_corrections"):
            result.add(str(row["target_ref"]))
            result.update(str(item) for item in json.loads(row["affected_refs_json"]))
        return result

    def _close_if_ready(
        self,
        connection: sqlite3.Connection,
        owner_user_id: str,
        cycle_id: str,
        submission_link_id: str,
    ) -> None:
        cycle = self._cycle(connection, owner_user_id, cycle_id)
        if cycle["completed_at"] is not None:
            return
        current = connection.execute(
            "SELECT link.*,assignment.purpose,evaluation.status AS evaluation_status "
            "FROM learning_loop_submission_links AS link "
            "JOIN learning_loop_assignments AS assignment ON assignment.id=link.assignment_id "
            "JOIN learning_loop_evaluation_links AS evaluation "
            "ON evaluation.submission_link_id=link.id "
            "WHERE link.id=? AND link.owner_user_id=?",
            (submission_link_id, owner_user_id),
        ).fetchone()
        if (
            current is None or current["purpose"] not in {"TRANSFER", "RECHECK"}
            or not current["independent_at_submission"]
            or current["evaluation_status"] != "VALID"
        ):
            return
        initial = connection.execute(
            "SELECT link.id AS submission_link_id,feedback.canonical_feedback_ref,"
            "feedback.delivered_sequence,assignment.assigned_sequence "
            "FROM learning_loop_submission_links AS link "
            "JOIN learning_loop_assignments AS assignment ON assignment.id=link.assignment_id "
            "JOIN learning_loop_feedback_deliveries AS feedback "
            "ON feedback.submission_link_id=link.id "
            "WHERE link.cycle_id=? AND assignment.purpose='INITIAL' "
            "AND feedback.delivered_sequence < (SELECT assigned_sequence FROM "
            "learning_loop_assignments WHERE id=?) "
            "ORDER BY feedback.delivered_sequence DESC LIMIT 1",
            (cycle_id, current["assignment_id"]),
        ).fetchone()
        if initial is None:
            return
        connection.execute(
            "UPDATE learning_loop_cycles SET state='COMPLETED',revision=revision+1,"
            "completion_submission_ref=?,closure_initial_submission_ref=?,"
            "closure_feedback_ref=?,completed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE id=? AND completed_at IS NULL",
            (
                submission_link_id, initial["submission_link_id"],
                initial["canonical_feedback_ref"], cycle_id,
            ),
        )
        self._event(
            connection, owner_user_id=owner_user_id,
            workspace_id=str(cycle["workspace_id"]), cycle_id=cycle_id,
            kind="CYCLE_COMPLETED",
            payload={"completion_submission_ref": submission_link_id, "correctness_required": False},
        )

    def withdraw(
        self,
        *,
        actor_user_id: str,
        operation_id: str,
        target_ref: str,
        reason_ref: str,
        editor_authorized: bool,
    ) -> dict[str, Any]:
        operation_id = self._stable_operation(operation_id)
        if not editor_authorized:
            raise LearningLoopError("EDITOR_REQUIRED")
        payload = {"target_ref": target_ref, "reason_ref": reason_ref}
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._command_replay(
                connection, owner_user_id=actor_user_id, operation_id=operation_id,
                action="WITHDRAW", payload=payload,
            )
            if replay is not None:
                return replay
            affected = [target_ref]
            correction_id = _id("correction")
            connection.execute(
                "INSERT INTO learning_loop_corrections("
                "id,actor_user_id,target_ref,reason_ref,affected_refs_json) VALUES(?,?,?,?,?)",
                (correction_id, actor_user_id, target_ref, reason_ref, _canonical(affected)),
            )
            result = {
                "id": correction_id,
                "target_ref": target_ref,
                "reason_ref": reason_ref,
                "affected_refs": affected,
            }
            return self._remember(
                connection, owner_user_id=actor_user_id, operation_id=operation_id,
                action="WITHDRAW", payload=payload, result=result,
            )

    def schedule_followup(
        self,
        *,
        owner_user_id: str,
        operation_id: str,
        cycle_id: str,
        explicit_opt_in: bool,
        timezone: str,
        due_at: str | None = None,
    ) -> dict[str, Any]:
        operation_id = self._stable_operation(operation_id)
        if explicit_opt_in is not True:
            raise LearningLoopError("EXPLICIT_OPT_IN_REQUIRED")
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise LearningLoopError("TIMEZONE_DATA_REQUIRED") from error
        card = self.evidence_card(owner_user_id=owner_user_id, cycle_id=cycle_id)
        if not card["currently_valid_closure"]:
            raise LearningLoopError("EVIDENCE_REQUIRES_REVIEW")
        completed = datetime.fromisoformat(str(card["completed_at"]).replace("Z", "+00:00"))
        try:
            due = (
                datetime.fromisoformat(due_at.replace("Z", "+00:00"))
                if due_at else completed + timedelta(days=7)
            )
        except (AttributeError, ValueError) as error:
            raise LearningLoopError("INVALID_DUE_AT") from error
        if due.tzinfo is None:
            raise LearningLoopError("TIMEZONE_AWARE_DUE_REQUIRED")
        due = due.astimezone(UTC)
        if due <= datetime.now(UTC):
            raise LearningLoopError("DUE_MUST_BE_FUTURE")
        payload = {
            "cycle_id": cycle_id,
            "timezone": timezone,
            "due_at": due.isoformat().replace("+00:00", "Z"),
            "explicit_opt_in": True,
        }
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cycle = self._cycle(connection, owner_user_id, cycle_id)
            replay = self._command_replay(
                connection, owner_user_id=owner_user_id, operation_id=operation_id,
                action="FOLLOWUP_SCHEDULE", payload=payload,
            )
            if replay is not None:
                return replay
            followup_id = _id("followup")
            key = "learning-loop-followup-" + sha256(
                f"{owner_user_id}\0{cycle_id}\0revision-1".encode("utf-8")
            ).hexdigest()
            connection.execute(
                "INSERT INTO learning_loop_followups("
                "id,cycle_id,owner_user_id,due_at,timezone,consent_revision,"
                "idempotency_key,status) VALUES(?,?,?,?,?,1,?,'PENDING')",
                (followup_id, cycle_id, owner_user_id, payload["due_at"], timezone, key),
            )
            result = {
                "id": followup_id, "cycle_id": cycle_id,
                "course_id": cycle["course_id"], "due_at": payload["due_at"],
                "timezone": timezone, "idempotency_key": key,
                "status": "PENDING", "task_ref": None,
            }
            return self._remember(
                connection, owner_user_id=owner_user_id, operation_id=operation_id,
                action="FOLLOWUP_SCHEDULE", payload=payload, result=result,
            )

    def claim_followup(self, *, owner_user_id: str, followup_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT followup.*,cycle.course_id FROM learning_loop_followups AS followup "
                "JOIN learning_loop_cycles AS cycle ON cycle.id=followup.cycle_id "
                "WHERE followup.id=? AND followup.owner_user_id=?",
                (followup_id, owner_user_id),
            ).fetchone()
            if row is None:
                raise LearningLoopError("NOT_FOUND")
            if row["status"] == "PENDING":
                connection.execute(
                    "UPDATE learning_loop_followups SET status='CREATING',"
                    "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                    (followup_id,),
                )
                return _dict(row) | {"status": "CREATING", "claimed": True}
            return _dict(row) | {"claimed": False}

    def finish_followup(
        self, *, owner_user_id: str, followup_id: str, task_ref: str | None,
        uncertain: bool = False,
    ) -> dict[str, Any]:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM learning_loop_followups WHERE id=? AND owner_user_id=?",
                (followup_id, owner_user_id),
            ).fetchone()
            if row is None:
                raise LearningLoopError("NOT_FOUND")
            if row["status"] == "BOUND":
                return _dict(row)
            status = "UNKNOWN" if uncertain else "BOUND"
            if not uncertain and not task_ref:
                raise LearningLoopError("TASK_REF_REQUIRED")
            connection.execute(
                "UPDATE learning_loop_followups SET status=?,task_ref=?,"
                "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (status, task_ref, followup_id),
            )
            return _dict(row) | {"status": status, "task_ref": task_ref}

    def evidence_card(self, *, owner_user_id: str, cycle_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            cycle = self._cycle(connection, owner_user_id, cycle_id)
            corrections = self._correction_targets(connection)
            rows = connection.execute(
                "SELECT link.*,assignment.question_revision_id,assignment.purpose,"
                "submission.answer_revision,submission.created_at AS submitted_at,"
                "evaluation.outcome,evaluation.status AS evaluation_status,"
                "evaluation.canonical_evaluation_id "
                "FROM learning_loop_submission_links AS link "
                "JOIN learning_loop_assignments AS assignment ON assignment.id=link.assignment_id "
                "JOIN practice_submission_revisions AS submission "
                "ON submission.id=link.canonical_submission_id "
                "LEFT JOIN learning_loop_evaluation_links AS evaluation "
                "ON evaluation.submission_link_id=link.id "
                "WHERE link.cycle_id=? AND link.owner_user_id=? ORDER BY link.saved_sequence",
                (cycle_id, owner_user_id),
            ).fetchall()
            attempts: list[dict[str, Any]] = []
            for row in rows:
                reasons = list(json.loads(row["eligibility_reasons_json"]))
                if row["question_revision_id"] in corrections:
                    reasons.append("CONTENT_WITHDRAWN")
                if row["canonical_evaluation_id"] in corrections:
                    reasons.append("EVALUATION_WITHDRAWN")
                if row["evaluation_status"] != "VALID":
                    reasons.append("NO_VALID_EVALUATION")
                reasons = list(dict.fromkeys(reasons))
                attempts.append(
                    {
                        "submission_ref": row["canonical_submission_id"],
                        "answer_revision": row["answer_revision"],
                        "question_revision": row["question_revision_id"],
                        "purpose": row["purpose"],
                        "at": row["submitted_at"],
                        "original_within_platform_unassisted": bool(
                            row["independent_at_submission"]
                        ),
                        "currently_eligible": not reasons,
                        "unseen_transfer": row["purpose"] in {"TRANSFER", "RECHECK"}
                        and not reasons,
                        "reasons": reasons,
                        "outcome": row["outcome"] or "AWAITING_EVALUATION",
                    }
                )
            current = False
            if cycle["completion_submission_ref"]:
                final = next(
                    (
                        item for item in attempts
                        if item["submission_ref"]
                        == connection.execute(
                            "SELECT canonical_submission_id FROM learning_loop_submission_links "
                            "WHERE id=?", (cycle["completion_submission_ref"],),
                        ).fetchone()[0]
                    ),
                    None,
                )
                current = bool(final and final["unseen_transfer"])
                if cycle["closure_feedback_ref"] in corrections:
                    current = False
            followups = [
                _dict(item)
                for item in connection.execute(
                    "SELECT id,due_at,timezone,status,task_ref,created_at,updated_at "
                    "FROM learning_loop_followups WHERE cycle_id=? AND owner_user_id=? "
                    "ORDER BY created_at",
                    (cycle_id, owner_user_id),
                ).fetchall()
            ]
            diagnoses = [
                {
                    "id": item["id"],
                    "criterion_ref": item["criterion_ref"],
                    "source_rule_ref": item["source_rule_ref"],
                    "status": item["status"],
                }
                for item in connection.execute(
                    "SELECT id,criterion_ref,source_rule_ref,status "
                    "FROM learning_loop_diagnosis_candidates WHERE cycle_id=? "
                    "AND owner_user_id=? ORDER BY created_at,id",
                    (cycle_id, owner_user_id),
                ).fetchall()
            ]
            intervention_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM learning_loop_interventions "
                    "WHERE cycle_id=? AND owner_user_id=?",
                    (cycle_id, owner_user_id),
                ).fetchone()[0]
            )
            diagnostic_items = list(json.loads(cycle["diagnostic_questions_json"]))
            diagnostic_responses = dict(json.loads(cycle["diagnostic_responses_json"]))
            return {
                "cycle_id": cycle_id,
                "course_id": cycle["course_id"],
                "node_id": cycle["node_id"],
                "spec_version": cycle["spec_version"],
                "objective_id": cycle["objective_id"],
                "pack_revision_id": cycle["pack_revision_id"],
                "state": cycle["state"],
                "completed_at": cycle["completed_at"],
                "historical_closure_exists": cycle["completed_at"] is not None,
                "currently_valid_closure": current,
                "attempts": attempts,
                "followups": followups,
                "diagnosis_candidates": diagnoses,
                "intervention_count": intervention_count,
                "diagnostic": {
                    "status": cycle["diagnostic_status"],
                    "purpose": "PRACTICE_NOT_FORMAL_ASSESSMENT",
                    "skippable": cycle["diagnostic_status"] in {"NOT_STARTED", "AVAILABLE"},
                    "items": [
                        item | {
                            "response": diagnostic_responses.get(item["question_revision_id"])
                        }
                        for item in diagnostic_items
                    ],
                },
                "within_platform_only": True,
                "not_proctored": True,
                "label_zh": "平台内未观察到帮助；不证明平台外未使用帮助",
                "mastery_probability": None,
                "formal_grade_written_by_this_module": False,
            }

    def dependency_scan(self, *, target_ref: str) -> dict[str, Any]:
        """Read-only correction preview; it never withdraws the target."""

        with self.database.connect() as connection:
            question = connection.execute(
                "SELECT question.id,question.course_id,question.family_id,"
                "question.source_document_version_id,provenance.node_id,"
                "provenance.spec_version,provenance.objective_id,"
                "provenance.publication_status FROM assessment_question_revisions AS question "
                "LEFT JOIN question_engine_provenance AS provenance "
                "ON provenance.question_revision_id=question.id WHERE question.id=?",
                (target_ref,),
            ).fetchone()
            evaluation = connection.execute(
                "SELECT evaluation.canonical_evaluation_id,link.canonical_submission_id,"
                "link.cycle_id,evaluation.status FROM learning_loop_evaluation_links AS evaluation "
                "JOIN learning_loop_submission_links AS link "
                "ON link.id=evaluation.submission_link_id "
                "WHERE evaluation.canonical_evaluation_id=?",
                (target_ref,),
            ).fetchone()
            if question is not None:
                counts = connection.execute(
                    "SELECT "
                    "(SELECT COUNT(*) FROM assessment_rubric_criteria WHERE question_revision_id=?) rubric_count,"
                    "(SELECT COUNT(*) FROM learning_loop_assignments WHERE question_revision_id=?) assignment_count,"
                    "(SELECT COUNT(*) FROM learning_loop_submission_links AS link "
                    "JOIN learning_loop_assignments AS assignment ON assignment.id=link.assignment_id "
                    "WHERE assignment.question_revision_id=?) submission_count",
                    (target_ref, target_ref, target_ref),
                ).fetchone()
            else:
                counts = None
        return {
            "target_ref": target_ref,
            "target_kind": "QUESTION" if question is not None else "EVALUATION" if evaluation is not None else "UNKNOWN",
            "question": _dict(question) if question is not None else None,
            "evaluation": _dict(evaluation) if evaluation is not None else None,
            "dependent_counts": _dict(counts) if counts is not None else {},
            "action_taken": False,
            "requires_authorized_editor_confirmation": True,
        }
