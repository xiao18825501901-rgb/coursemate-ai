import hashlib
import json
import math
import re
import sqlite3
from collections import defaultdict
from typing import Any, cast
from uuid import uuid4

from app.db import Database
from app.errors import ApiError
from app.learning.models import (
    AssessmentAnswer,
    AssessmentGradeProposal,
    AssessmentPreparationOutput,
    AssessmentReferenceSolutionOutput,
    AssessmentSolutionStep,
    GradePolicyDraftInput,
)
from app.learning.workspaces import workspace_for

MARK_SCHEME = (10, 15, 20, 25, 30)
SOURCE_ORDER = (
    "OFFICIAL",
    "WORKSPACE_PRIVATE",
    "MODEL_GENERATED",
    "EXTERNAL_INSPIRED",
)
DETERMINISTIC_TYPES = {"MCQ_SINGLE", "NUMERIC"}


def encode(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def identifier() -> str:
    return uuid4().hex


def digest(value: object) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


class AssessmentService:
    """Owns frozen assessment facts and emits only learner-safe projections."""

    def __init__(self, database: Database) -> None:
        self.db = database

    @staticmethod
    def _atomic_node(
        connection: sqlite3.Connection,
        workspace: sqlite3.Row,
        node_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT node.*,metadata.version AS spec_version "
            "FROM knowledge_nodes AS node "
            "JOIN teaching_spec_metadata AS metadata ON metadata.node_id=node.id "
            "WHERE node.id=? AND node.course_id=? AND node.kind='ATOMIC' AND ("
            "(node.owner_user_id=? AND node.status='PRIVATE' "
            " AND metadata.status='PRIVATE_ACTIVE') OR "
            "(node.owner_user_id IS NULL AND node.status='PUBLISHED' "
            " AND metadata.status='PUBLISHED')) "
            "ORDER BY metadata.version DESC LIMIT 1",
            (node_id, workspace["course_id"], workspace["owner_user_id"]),
        ).fetchone()
        if row is None:
            raise ApiError(
                404,
                "ASSESSABLE_NODE_NOT_FOUND",
                "An accessible atomic node with an active Teaching Spec is required.",
            )
        return cast(sqlite3.Row, row)

    @staticmethod
    def _rubric(
        connection: sqlite3.Connection,
        question_revision_id: str,
        node_id: str,
        spec_version: int,
    ) -> list[sqlite3.Row]:
        rows = connection.execute(
            "SELECT * FROM assessment_rubric_criteria "
            "WHERE question_revision_id=? AND node_id=? AND spec_version=? "
            "ORDER BY criterion_id",
            (question_revision_id, node_id, spec_version),
        ).fetchall()
        if not rows or sum(int(row["max_fraction"]) for row in rows) != 100:
            return []
        return list(rows)

    @staticmethod
    def _is_deterministic(question: dict[str, Any]) -> bool:
        """A question grades deterministically only when its frozen answer key is a
        finite standard: MCQ/NUMERIC always, and SHORT_TEXT only for an explicit
        enumeration (``accepted`` list). Concept/definition short answers without a
        provable enumeration fall through to the semantic rubric grader."""
        question_type = question["question_type"]
        if question_type in {"MCQ_SINGLE", "NUMERIC"}:
            return True
        if question_type == "SHORT_TEXT":
            answer = question.get("answer_key") or question.get("answer") or {}
            accepted = answer.get("accepted")
            return isinstance(accepted, list) and bool(accepted)
        return False

    def distinct_families(
        self,
        connection: sqlite3.Connection,
        workspace: sqlite3.Row,
        node: sqlite3.Row,
    ) -> set[str]:
        return {str(row["family_id"]) for row in self._eligible_pool(connection, workspace, node)}

    def select(
        self,
        connection: sqlite3.Connection,
        workspace: sqlite3.Row,
        node: sqlite3.Row,
    ) -> list[sqlite3.Row]:
        return self._select_questions(self._eligible_pool(connection, workspace, node))

    def _eligible_pool(
        self,
        connection: sqlite3.Connection,
        workspace: sqlite3.Row,
        node: sqlite3.Row,
    ) -> list[sqlite3.Row]:
        candidates = connection.execute(
            "SELECT question.*,COALESCE(("
            " SELECT COUNT(*) FROM assessment_blueprint_items AS previous_item "
            " JOIN assessment_blueprint_versions AS previous_blueprint "
            " ON previous_blueprint.id=previous_item.blueprint_id "
            " WHERE previous_blueprint.workspace_id=? "
            " AND previous_item.family_id=question.family_id"
            "),0) AS prior_exposures "
            "FROM assessment_question_revisions AS question "
            "WHERE question.course_id=? "
            "AND (question.owner_user_id IS NULL OR question.owner_user_id=?) "
            "AND question.validation_status='VALIDATED' "
            "AND question.verification_method!='MODEL_ONLY' "
            "AND NOT EXISTS("
            " SELECT 1 FROM assessment_exposure_events AS exposure "
            " WHERE exposure.workspace_id=? "
            " AND exposure.family_id=question.family_id"
            ") "
            "AND NOT EXISTS("
            " SELECT 1 FROM assessment_question_revisions AS exposed_question "
            " JOIN problem_attempts AS problem_attempt "
            " ON problem_attempt.problem_revision_id="
            "exposed_question.source_problem_revision_id "
            " WHERE problem_attempt.workspace_id=? "
            " AND problem_attempt.assistance='ANSWER_EXPOSED' "
            " AND exposed_question.course_id=question.course_id "
            " AND exposed_question.family_id=question.family_id "
            " AND (exposed_question.owner_user_id IS NULL "
            " OR exposed_question.owner_user_id=?)"
            ") "
            "ORDER BY prior_exposures,question.difficulty,question.family_id,question.id",
            (
                workspace["id"],
                workspace["course_id"],
                workspace["owner_user_id"],
                workspace["id"],
                workspace["id"],
                workspace["owner_user_id"],
            ),
        ).fetchall()
        return [
            row
            for row in candidates
            if self._rubric(
                connection,
                row["id"],
                node["id"],
                int(node["spec_version"]),
            )
        ]

    @staticmethod
    def _select_questions(candidates: list[sqlite3.Row]) -> list[sqlite3.Row]:
        by_source: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for candidate in candidates:
            by_source[str(candidate["source_kind"])].append(candidate)
        selected: list[sqlite3.Row] = []
        families: set[str] = set()
        for source in SOURCE_ORDER:
            selected_candidate: sqlite3.Row | None = next(
                (
                    row
                    for row in by_source[source]
                    if str(row["family_id"]) not in families
                ),
                None,
            )
            if selected_candidate is not None:
                selected.append(selected_candidate)
                families.add(str(selected_candidate["family_id"]))
        for candidate in candidates:
            if len(selected) == 5:
                break
            if str(candidate["family_id"]) not in families:
                selected.append(candidate)
                families.add(str(candidate["family_id"]))
        if len(selected) != 5:
            raise ApiError(
                409,
                "ASSESSMENT_POOL_INSUFFICIENT",
                "Five validated, non-duplicate questions are required for this node.",
            )
        return sorted(
            selected,
            key=lambda row: (int(row["difficulty"]), str(row["family_id"])),
        )

    @staticmethod
    def _grade_policy(
        connection: sqlite3.Connection,
        course_id: str,
        node_id: str,
    ) -> tuple[sqlite3.Row, str]:
        policy = connection.execute(
            "SELECT * FROM grade_policy_versions WHERE status='PUBLISHED' AND ("
            "(scope_type='NODE' AND scope_id=?) OR "
            "(scope_type='COURSE' AND scope_id=?) OR "
            "(scope_type='PLATFORM' AND scope_id='platform')) "
            "ORDER BY CASE scope_type WHEN 'NODE' THEN 1 WHEN 'COURSE' THEN 2 ELSE 3 END "
            "LIMIT 1",
            (node_id, course_id),
        ).fetchone()
        if policy is not None:
            return cast(sqlite3.Row, policy), "CONFIGURED"
        seed = connection.execute(
            "SELECT * FROM grade_policy_versions "
            "WHERE id='gp_requirements_draft_v1'"
        ).fetchone()
        if seed is None:
            raise RuntimeError("The unconfigured GradePolicy seed is missing")
        return cast(sqlite3.Row, seed), "UNCONFIGURED"

    def start(
        self,
        connection: sqlite3.Connection,
        workspace: sqlite3.Row,
        node_id: str,
    ) -> dict[str, Any]:
        node = self._atomic_node(connection, workspace, node_id)
        if connection.execute(
            "SELECT 1 FROM assessment_sessions WHERE workspace_id=? AND node_id=? "
            "AND status='IN_PROGRESS'",
            (workspace["id"], node_id),
        ).fetchone():
            raise ApiError(
                409,
                "ASSESSMENT_ALREADY_ACTIVE",
                "Resume or abandon the active Assessment before starting another.",
            )
        selected = self.select(connection, workspace, node)
        policy, mapping_status = self._grade_policy(
            connection,
            str(workspace["course_id"]),
            node_id,
        )
        version = int(
            connection.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM assessment_blueprint_versions "
                "WHERE workspace_id=? AND node_id=?",
                (workspace["id"], node_id),
            ).fetchone()[0]
        )
        blueprint_id = identifier()
        selection_policy = {
            "algorithm": "HYBRID_UNSEEN_FAMILY_V1",
            "question_count": 5,
            "marks": list(MARK_SCHEME),
            "source_order": list(SOURCE_ORDER),
            "excludes_answer_exposed_problem_revisions": True,
            "excludes_answer_exposed_problem_families": True,
            "excludes_assisted_assessment_families": True,
        }
        frozen_items = [
            {
                "ordinal": ordinal,
                "question_revision_id": question["id"],
                "family_id": question["family_id"],
                "marks": MARK_SCHEME[ordinal - 1],
                "source_kind": question["source_kind"],
                "verification_method": question["verification_method"],
            }
            for ordinal, question in enumerate(selected, start=1)
        ]
        blueprint_hash = digest(
            {
                "workspace_id": workspace["id"],
                "node_id": node_id,
                "spec_version": node["spec_version"],
                "version": version,
                "selection_policy": selection_policy,
                "items": frozen_items,
                "grade_policy_version_id": policy["id"],
            }
        )
        connection.execute(
            "INSERT INTO assessment_blueprint_versions("
            "id,workspace_id,owner_user_id,course_id,node_id,spec_version,version,"
            "selection_policy_json,content_hash) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                blueprint_id,
                workspace["id"],
                workspace["owner_user_id"],
                workspace["course_id"],
                node_id,
                node["spec_version"],
                version,
                encode(selection_policy),
                blueprint_hash,
            ),
        )
        for frozen in frozen_items:
            connection.execute(
                "INSERT INTO assessment_blueprint_items("
                "id,blueprint_id,ordinal,question_revision_id,family_id,marks,"
                "source_kind,verification_method) VALUES(?,?,?,?,?,?,?,?)",
                (
                    identifier(),
                    blueprint_id,
                    frozen["ordinal"],
                    frozen["question_revision_id"],
                    frozen["family_id"],
                    frozen["marks"],
                    frozen["source_kind"],
                    frozen["verification_method"],
                ),
            )
        connection.execute(
            "INSERT INTO assessment_blueprint_grade_policies VALUES(?,?,?)",
            (blueprint_id, policy["id"], mapping_status),
        )
        connection.execute(
            "UPDATE assessment_blueprint_versions SET status='FROZEN' WHERE id=?",
            (blueprint_id,),
        )
        session_id = identifier()
        connection.execute(
            "INSERT INTO assessment_sessions("
            "id,workspace_id,owner_user_id,course_id,node_id,blueprint_id) "
            "VALUES(?,?,?,?,?,?)",
            (
                session_id,
                workspace["id"],
                workspace["owner_user_id"],
                workspace["course_id"],
                node_id,
                blueprint_id,
            ),
        )
        for row in connection.execute(
            "SELECT id FROM assessment_blueprint_items WHERE blueprint_id=?",
            (blueprint_id,),
        ):
            connection.execute(
                "INSERT INTO assessment_question_attempts("
                "id,session_id,blueprint_item_id) VALUES(?,?,?)",
                (identifier(), session_id, row["id"]),
            )
        return self._session_view(connection, workspace, session_id)

    @staticmethod
    def _grade_projection(
        mapping_status: str,
        snapshot: sqlite3.Row | None,
    ) -> dict[str, Any]:
        if snapshot is None:
            return {
                "mapping_status": mapping_status,
                "label": None,
                "numeric_value": None,
                "message": (
                    "评分映射待配置"
                    if mapping_status == "UNCONFIGURED"
                    else "提交后显示成绩映射"
                ),
            }
        return {
            "mapping_status": snapshot["mapping_status"],
            "label": snapshot["grade_label"],
            "numeric_value": snapshot["numeric_value"],
            "message": (
                "评分映射待配置"
                if snapshot["mapping_status"] == "UNCONFIGURED"
                else "已按冻结的 GradePolicy 映射"
            ),
        }

    def _session_view(
        self,
        connection: sqlite3.Connection,
        workspace: sqlite3.Row,
        session_id: str,
    ) -> dict[str, Any]:
        session = connection.execute(
            "SELECT session.*,blueprint.spec_version,blueprint.version AS blueprint_version,"
            "blueprint.content_hash AS blueprint_hash,binding.mapping_status,"
            "binding.grade_policy_version_id "
            "FROM assessment_sessions AS session "
            "JOIN assessment_blueprint_versions AS blueprint "
            "ON blueprint.id=session.blueprint_id "
            "JOIN assessment_blueprint_grade_policies AS binding "
            "ON binding.blueprint_id=blueprint.id "
            "WHERE session.id=? AND session.workspace_id=? AND session.owner_user_id=?",
            (session_id, workspace["id"], workspace["owner_user_id"]),
        ).fetchone()
        if session is None:
            raise ApiError(404, "ASSESSMENT_NOT_FOUND", "The Assessment was not found.")
        policy = connection.execute(
            "SELECT * FROM grade_policy_versions WHERE id=?",
            (session["grade_policy_version_id"],),
        ).fetchone()
        if policy is None:
            raise RuntimeError("The frozen GradePolicy binding is missing")
        snapshot = connection.execute(
            "SELECT * FROM grade_snapshots WHERE assessment_session_id=? "
            "ORDER BY revision DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        question_rows = connection.execute(
            "SELECT item.*,question.question_type,question.difficulty,"
            "question.prompt_text,question.options_json,"
            "attempt.status AS attempt_status,attempt.answer_json AS submitted_answer_json,"
            "attempt.assistance,attempt.awarded_marks,attempt.feedback "
            "FROM assessment_blueprint_items AS item "
            "JOIN assessment_question_revisions AS question "
            "ON question.id=item.question_revision_id "
            "JOIN assessment_question_attempts AS attempt "
            "ON attempt.blueprint_item_id=item.id AND attempt.session_id=? "
            "WHERE item.blueprint_id=? ORDER BY item.ordinal",
            (session_id, session["blueprint_id"]),
        ).fetchall()
        questions: list[dict[str, Any]] = []
        for row in question_rows:
            question: dict[str, Any] = {
                "id": row["id"],
                "question_revision_id": row["question_revision_id"],
                "ordinal": row["ordinal"],
                "family_id": row["family_id"],
                "marks": row["marks"],
                "source_kind": row["source_kind"],
                "verification_method": row["verification_method"],
                "question_type": row["question_type"],
                "difficulty": row["difficulty"],
                "prompt": row["prompt_text"],
                "options": json.loads(row["options_json"]),
                "attempt_status": row["attempt_status"],
                "assistance": row["assistance"],
            }
            answer_is_available = session["status"] in {"SUBMITTED", "GRADED"}
            answer_is_available = answer_is_available or row["assistance"] == "ANSWER_REVEALED"
            if answer_is_available:
                answer = connection.execute(
                    "SELECT answer_json FROM assessment_question_revisions WHERE id=?",
                    (row["question_revision_id"],),
                ).fetchone()
                if answer is None:
                    raise RuntimeError("The frozen Assessment answer is missing")
                rubric = self._rubric(
                    connection,
                    str(row["question_revision_id"]),
                    str(session["node_id"]),
                    int(session["spec_version"]),
                )
                reference = self.reference_solution(connection, str(row["question_revision_id"]))
                question["review"] = {
                    "submitted_answer": (
                        json.loads(row["submitted_answer_json"])["answer"]
                        if row["submitted_answer_json"] is not None
                        else None
                    ),
                    "answer": json.loads(answer["answer_json"]),
                    "awarded_marks": row["awarded_marks"],
                    "feedback": row["feedback"],
                    "rubric": [
                        {
                            "criterion_id": criterion["criterion_id"],
                            "dimension": criterion["dimension"],
                            "max_fraction": criterion["max_fraction"],
                            "description": criterion["description"],
                        }
                        for criterion in rubric
                    ],
                    "reference_solution": (
                        {
                            "solution_revision": reference["solution_revision"],
                            "answer": json.loads(reference["answer_json"]),
                            "steps": json.loads(reference["steps_json"]),
                            "source_refs": json.loads(reference["source_refs_json"]),
                        }
                        if reference is not None
                        else None
                    ),
                }
            questions.append(question)
        evidence = [
            {
                "id": row["id"],
                "question_attempt_id": row["question_attempt_id"],
                "criterion_id": row["criterion_id"],
                "node_id": row["node_id"],
                "spec_version": row["spec_version"],
                "item_id": row["item_id"],
                "dimension": row["dimension"],
                "awarded_marks": row["awarded_marks"],
                "max_marks": row["max_marks"],
                "confidence": row["confidence"],
                "independent_eligible": bool(row["independent_eligible"]),
                "performance_band": row["performance_band"],
            }
            for row in connection.execute(
                "SELECT * FROM performance_evidence "
                "WHERE assessment_session_id=? ORDER BY question_attempt_id,criterion_id",
                (session_id,),
            )
        ]
        return {
            "id": session["id"],
            "workspace_id": session["workspace_id"],
            "node_id": session["node_id"],
            "blueprint_id": session["blueprint_id"],
            "blueprint_version": session["blueprint_version"],
            "blueprint_hash": session["blueprint_hash"],
            "spec_version": session["spec_version"],
            "status": session["status"],
            "mode": session["mode"],
            "assistance_status": session["assistance_status"],
            "raw_score": snapshot["raw_score"] if snapshot is not None else None,
            "independent_eligible": (
                bool(snapshot["independent_eligible"])
                if snapshot is not None
                else session["mode"] == "INDEPENDENT"
            ),
            "grade": self._grade_projection(
                str(session["mapping_status"]),
                snapshot,
            ),
            "grade_policy": {
                "id": policy["id"],
                "name": policy["display_name"],
                "provenance": policy["provenance_label"],
            },
            "questions": questions,
            "performance_evidence": evidence,
            "started_at": session["started_at"],
            "submitted_at": session["submitted_at"],
            "graded_at": session["graded_at"],
        }

    def view(self, workspace_id: str, owner: str, session_id: str) -> dict[str, Any]:
        workspace = workspace_for(self.db, workspace_id, owner)
        with self.db.connect() as connection:
            return self._session_view(connection, workspace, session_id)

    @staticmethod
    def pending_replan(
        connection: sqlite3.Connection,
        workspace: sqlite3.Row,
        node_id: str,
    ) -> list[dict[str, Any]]:
        triggers: list[dict[str, Any]] = []
        rows = connection.execute(
            "SELECT * FROM learning_replan_triggers WHERE workspace_id=? AND node_id=? "
            "AND status='PENDING' ORDER BY created_at,id",
            (workspace["id"], node_id),
        ).fetchall()
        for row in rows:
            evidence_ids = json.loads(row["performance_evidence_ids_json"])
            placeholders = ",".join("?" for _ in evidence_ids)
            evidence = connection.execute(
                "SELECT id,item_id,dimension,performance_band,awarded_marks,max_marks,"
                "confidence,independent_eligible FROM performance_evidence WHERE id IN ("
                + placeholders
                + ") AND workspace_id=? AND node_id=? ORDER BY item_id,dimension,id",
                (*evidence_ids, workspace["id"], node_id),
            ).fetchall()
            if len(evidence) != len(evidence_ids):
                raise ApiError(
                    409,
                    "REPLAN_EVIDENCE_UNAVAILABLE",
                    "A pending learning replan trigger has incomplete evidence.",
                )
            triggers.append(
                {
                    "id": row["id"],
                    "kind": row["trigger_kind"],
                    "source_assessment_session_id": row[
                        "source_assessment_session_id"
                    ],
                    "reason_summary": row["reason_summary"],
                    "item_ids": sorted({str(item["item_id"]) for item in evidence}),
                    "evidence": [dict(item) for item in evidence],
                }
            )
        return triggers

    def _submission_context(
        self,
        connection: sqlite3.Connection,
        workspace: sqlite3.Row,
        session_id: str,
        answers: list[AssessmentAnswer],
    ) -> dict[str, Any]:
        session = connection.execute(
            "SELECT session.*,blueprint.spec_version FROM assessment_sessions AS session "
            "JOIN assessment_blueprint_versions AS blueprint "
            "ON blueprint.id=session.blueprint_id "
            "WHERE session.id=? AND session.workspace_id=? AND session.owner_user_id=?",
            (session_id, workspace["id"], workspace["owner_user_id"]),
        ).fetchone()
        if session is None:
            raise ApiError(404, "ASSESSMENT_NOT_FOUND", "The Assessment was not found.")
        if session["status"] != "IN_PROGRESS":
            raise ApiError(
                409,
                "ASSESSMENT_NOT_ACTIVE",
                "Only an in-progress Assessment can be submitted.",
            )
        answer_map = {answer.blueprint_item_id: answer.answer for answer in answers}
        rows = connection.execute(
            "SELECT item.*,question.question_type,question.prompt_text,"
            "question.options_json,question.answer_json "
            "FROM assessment_blueprint_items AS item "
            "JOIN assessment_question_revisions AS question "
            "ON question.id=item.question_revision_id "
            "WHERE item.blueprint_id=? ORDER BY item.ordinal",
            (session["blueprint_id"],),
        ).fetchall()
        if set(answer_map) != {str(row["id"]) for row in rows}:
            raise ApiError(
                422,
                "ASSESSMENT_ANSWERS_INCOMPLETE",
                "Submit exactly one answer for each frozen question.",
            )
        questions: list[dict[str, Any]] = []
        for row in rows:
            rubric = self._rubric(
                connection,
                str(row["question_revision_id"]),
                str(session["node_id"]),
                int(session["spec_version"]),
            )
            if not rubric:
                raise ApiError(
                    409,
                    "ASSESSMENT_RUBRIC_INVALID",
                    "The frozen Assessment rubric is incomplete.",
                )
            questions.append(
                {
                    **dict(row),
                    "options": json.loads(row["options_json"]),
                    "answer_key": json.loads(row["answer_json"]),
                    "student_answer": answer_map[str(row["id"])],
                    "rubric": [dict(criterion) for criterion in rubric],
                }
            )
        return {"session": dict(session), "questions": questions}

    # ------------------------------------------------------------------ drafts
    def save_draft(
        self,
        connection: sqlite3.Connection,
        workspace: sqlite3.Row,
        session_id: str,
        unified_answer: str | None,
        attachments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        session = connection.execute(
            "SELECT * FROM assessment_sessions WHERE id=? AND workspace_id=? "
            "AND owner_user_id=? AND status='IN_PROGRESS'",
            (session_id, workspace["id"], workspace["owner_user_id"]),
        ).fetchone()
        if session is None:
            raise ApiError(409, "ASSESSMENT_NOT_ACTIVE", "Only an in-progress Assessment has a draft.")
        payload = encode({"unified_answer": unified_answer or "", "attachments": attachments})
        connection.execute(
            "INSERT INTO assessment_answer_drafts(id,session_id,owner_user_id,unified_answer_json) "
            "VALUES(?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET "
            "unified_answer_json=excluded.unified_answer_json,updated_at="
            "strftime('%Y-%m-%dT%H:%M:%fZ','now')",
            (identifier(), session_id, workspace["owner_user_id"], payload),
        )
        return {"session_id": session_id, "saved": True, "unified_answer": unified_answer or ""}

    def load_draft(
        self,
        connection: sqlite3.Connection,
        workspace: sqlite3.Row,
        session_id: str,
    ) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT unified_answer_json FROM assessment_answer_drafts "
            "WHERE session_id=? AND owner_user_id=?",
            (session_id, workspace["owner_user_id"]),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["unified_answer_json"])

    # ----------------------------------------------------- unified answer mapping
    @staticmethod
    def _parse_unified_markers(text: str) -> dict[int, str]:
        pattern = re.compile(
            r"(?:^|\n)\s*(?:第\s*([1-5])\s*[题问]|([1-5])\s*[.)、:：]|[Qq]\s*([1-5])\s*[:：.])"
        )
        matches = list(pattern.finditer(text))
        result: dict[int, str] = {}
        for index, match in enumerate(matches):
            ordinal = int(next(group for group in match.groups() if group is not None))
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            answer = text[start:end].strip()
            if answer:
                result.setdefault(ordinal, answer)
        return result

    def map_unified_answers(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        unified_answer: str | None,
        confirm_unanswered: list[str],
    ) -> list[AssessmentAnswer]:
        """Map ONE unified answer payload to the 5 stable blueprint ids.

        Deterministic 1-5 markers are parsed first; explicitly confirmed-unanswered
        items become blank answers; anything still unmapped raises for confirmation
        rather than silently guessing.
        """
        rows = connection.execute(
            "SELECT item.*,question.question_type FROM assessment_blueprint_items AS item "
            "JOIN assessment_question_revisions AS question "
            "ON question.id=item.question_revision_id "
            "JOIN assessment_sessions AS session ON session.blueprint_id=item.blueprint_id "
            "WHERE session.id=? ORDER BY item.ordinal",
            (session_id,),
        ).fetchall()
        by_ordinal = {int(row["ordinal"]): row for row in rows}
        markers = self._parse_unified_markers(unified_answer or "")
        confirmed = set(confirm_unanswered or [])
        mapped: dict[int, str] = {}
        for ordinal, answer in markers.items():
            if ordinal in by_ordinal:
                mapped[ordinal] = answer
        unanswered: list[int] = []
        for ordinal in range(1, 6):
            if ordinal in mapped:
                continue
            row = by_ordinal[ordinal]
            if str(row["id"]) in confirmed:
                mapped[ordinal] = ""
            else:
                unanswered.append(ordinal)
        if unanswered:
            raise ApiError(
                422,
                "ASSESSMENT_ANSWERS_NEED_CONFIRMATION",
                "Unmapped answers need explicit confirmation before submission; "
                "the server never guesses a question mapping.",
            )
        return [
            AssessmentAnswer(blueprint_item_id=str(by_ordinal[ordinal]["id"]), answer=mapped[ordinal])
            for ordinal in range(1, 6)
        ]

    # ---------------------------------------------------- submission revisions
    @staticmethod
    def _record_submission_revision(
        connection: sqlite3.Connection,
        session_id: str,
        answers: list[AssessmentAnswer],
    ) -> int:
        revision = int(
            connection.execute(
                "SELECT COALESCE(MAX(submission_revision),0)+1 "
                "FROM assessment_submission_revisions WHERE session_id=?",
                (session_id,),
            ).fetchone()[0]
        )
        mapped = [
            {"blueprint_item_id": answer.blueprint_item_id, "answer": answer.answer}
            for answer in answers
        ]
        connection.execute(
            "INSERT INTO assessment_submission_revisions("
            "id,session_id,submission_revision,content_hash,mapped_answers_json) "
            "VALUES(?,?,?,?,?)",
            (
                identifier(),
                session_id,
                revision,
                digest({"session_id": session_id, "answers": mapped}),
                encode(mapped),
            ),
        )
        return revision

    def save_submission_review_needed(
        self,
        connection: sqlite3.Connection,
        workspace: sqlite3.Row,
        session_id: str,
        answers: list[AssessmentAnswer],
    ) -> dict[str, Any]:
        """Grading failed: keep the previous valid result and mark NEEDS_REVIEW.

        No performance evidence or grade snapshot is written, so a failed grader can
        never turn a learner's answer into 0 marks or overwrite a previous result.
        """
        prepared = self._submission_context(connection, workspace, session_id, answers)
        revision = self._record_submission_revision(connection, session_id, answers)
        grader_input = self.grader_context(prepared)
        grader_input_hash = digest(grader_input) if grader_input is not None else None
        if grader_input_hash is not None:
            connection.execute(
                "INSERT OR IGNORE INTO assessment_grading_receipts("
                "id,session_id,submission_revision,grader_input_hash,grade_proposal_json) "
                "VALUES(?,?,?,?,NULL)",
                (identifier(), session_id, revision, grader_input_hash),
            )
        connection.execute(
            "UPDATE assessment_sessions SET status='SUBMITTED',submitted_at="
            "strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND status='IN_PROGRESS'",
            (session_id,),
        )
        result = self._session_view(connection, workspace, session_id)
        result["needs_review"] = True
        return result

    # -------------------------------------------------------- pool preparation
    def preparation_job(
        self,
        connection: sqlite3.Connection,
        workspace: sqlite3.Row,
        node_id: str,
        spec_version: int,
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM assessment_preparation_jobs "
            "WHERE workspace_id=? AND node_id=? AND spec_version=?",
            (workspace["id"], node_id, spec_version),
        ).fetchone()

    def ensure_preparation_job(
        self,
        connection: sqlite3.Connection,
        workspace: sqlite3.Row,
        node: sqlite3.Row,
    ) -> sqlite3.Row:
        spec_version = int(node["spec_version"])
        existing = self.preparation_job(connection, workspace, node["id"], spec_version)
        if existing is not None:
            return existing
        connection.execute(
            "INSERT OR IGNORE INTO assessment_preparation_jobs("
            "id,workspace_id,owner_user_id,course_id,node_id,spec_version,status,channel) "
            "VALUES(?,?,?,?,?,?,'PREPARING','VALIDATED')",
            (
                identifier(),
                workspace["id"],
                workspace["owner_user_id"],
                workspace["course_id"],
                node["id"],
                spec_version,
            ),
        )
        row = connection.execute(
            "SELECT * FROM assessment_preparation_jobs "
            "WHERE workspace_id=? AND node_id=? AND spec_version=?",
            (workspace["id"], node["id"], spec_version),
        ).fetchone()
        return cast(sqlite3.Row, row)

    @staticmethod
    def mark_preparation_job(
        connection: sqlite3.Connection,
        job_id: str,
        status: str,
        *,
        channel: str = "VALIDATED",
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        connection.execute(
            "UPDATE assessment_preparation_jobs SET status=?,channel=?,error_code=?,"
            "error_message=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),"
            "completed_at=CASE WHEN ? IN ('READY','BLOCKED') THEN "
            "strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE completed_at END WHERE id=?",
            (status, channel, error_code, error_message, status, job_id),
        )

    def cancel_preparation_job(
        self,
        connection: sqlite3.Connection,
        workspace: sqlite3.Row,
        job_id: str,
    ) -> dict[str, Any]:
        updated = connection.execute(
            "UPDATE assessment_preparation_jobs SET status='CANCELLED',"
            "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE id=? AND workspace_id=? AND status='PREPARING'",
            (job_id, workspace["id"]),
        )
        if updated.rowcount != 1:
            row = connection.execute(
                "SELECT * FROM assessment_preparation_jobs WHERE id=? AND workspace_id=?",
                (job_id, workspace["id"]),
            ).fetchone()
            if row is None:
                raise ApiError(404, "PREPARATION_JOB_NOT_FOUND", "The preparation job was not found.")
            raise ApiError(
                409,
                "PREPARATION_JOB_NOT_CANCELLABLE",
                "Only a PREPARING job can be cancelled.",
            )
        row = connection.execute("SELECT * FROM assessment_preparation_jobs WHERE id=?", (job_id,)).fetchone()
        return dict(cast(sqlite3.Row, row))

    @staticmethod
    def _verify_candidate(question: Any) -> str:
        """Deterministic verification level for a prepared candidate.

        MCQ/NUMERIC with a structurally valid answer, and SHORT_TEXT with a finite
        accepted enumeration, enter the VALIDATED channel as DETERMINISTIC.
        Concept/open questions with no provable external standard are marked
        AI_REVIEWED (diagnostic) — never VALIDATED.
        """
        if question.question_type == "MCQ_SINGLE":
            correct = question.answer.get("correct_option")
            if correct is not None and question.options:
                return "DETERMINISTIC"
        if question.question_type == "NUMERIC":
            value = question.answer.get("value")
            if isinstance(value, (int, float)):
                return "DETERMINISTIC"
        if question.question_type == "SHORT_TEXT":
            accepted = question.answer.get("accepted")
            if isinstance(accepted, list) and accepted:
                return "DETERMINISTIC"
        return "AI_REVIEWED"

    @staticmethod
    def _first_required_item(connection: sqlite3.Connection, node: sqlite3.Row) -> str:
        row = connection.execute(
            "SELECT item_id FROM teaching_items WHERE node_id=? AND spec_version=? "
            "AND requirement='REQUIRED' ORDER BY item_id LIMIT 1",
            (node["id"], int(node["spec_version"])),
        ).fetchone()
        if row is None:
            raise ApiError(
                409,
                "ASSESSMENT_SPEC_NO_ITEMS",
                "The node has no REQUIRED Teaching Item to bind a rubric.",
            )
        return str(row["item_id"])

    def store_candidates(
        self,
        connection: sqlite3.Connection,
        workspace: sqlite3.Row,
        node: sqlite3.Row,
        output: AssessmentPreparationOutput,
        evidence_ids: list[str],
    ) -> list[dict[str, str]]:
        existing_families = {
            str(row["family_id"])
            for row in connection.execute(
                "SELECT family_id FROM assessment_question_revisions "
                "WHERE course_id=? AND (owner_user_id IS NULL OR owner_user_id=?)",
                (workspace["course_id"], workspace["owner_user_id"]),
            )
        }
        item_id = self._first_required_item(connection, node)
        stored: list[dict[str, str]] = []
        for question in output.questions:
            if question.family_id in existing_families:
                raise ValueError("Duplicate candidate question family")
            if any(
                ref not in evidence_ids
                for step in question.reference_steps
                for ref in step.source_refs
            ):
                raise ValueError("Candidate reference source is outside authorized evidence")
            verification_method = self._verify_candidate(question)
            question_id = identifier()
            content = {
                "prompt": question.prompt,
                "options": question.options,
                "answer": question.answer,
            }
            connection.execute(
                "INSERT INTO assessment_question_revisions("
                "id,course_id,owner_user_id,family_id,revision,source_kind,question_type,"
                "difficulty,prompt_text,options_json,answer_json,validation_status,"
                "verification_method,content_hash,created_by_user_id) "
                "VALUES(?,?,?,?,1,'MODEL_GENERATED',?,?,?,?,?,'VALIDATED',?,?,?)",
                (
                    question_id,
                    workspace["course_id"],
                    workspace["owner_user_id"],
                    question.family_id,
                    question.question_type,
                    question.difficulty,
                    question.prompt,
                    encode(question.options),
                    encode(question.answer),
                    verification_method,
                    digest(content),
                    workspace["owner_user_id"],
                ),
            )
            for criterion in question.criteria:
                connection.execute(
                    "INSERT INTO assessment_rubric_criteria("
                    "question_revision_id,criterion_id,node_id,spec_version,item_id,"
                    "dimension,max_fraction,description,deterministic_rule_json) "
                    "VALUES(?,?,?,?,?,?,?,?,'{}')",
                    (
                        question_id,
                        criterion.criterion_id,
                        node["id"],
                        int(node["spec_version"]),
                        item_id,
                        criterion.dimension,
                        criterion.max_fraction,
                        criterion.description,
                    ),
                )
            self._store_reference_solution(
                connection,
                question_id,
                None,
                question.reference_answer or "",
                question.reference_steps,
            )
            stored.append({"question_revision_id": question_id, "family_id": question.family_id,
                           "verification_method": verification_method})
        return stored

    # -------------------------------------------------------- reference solutions
    @staticmethod
    def has_reference_solution(
        connection: sqlite3.Connection,
        question_revision_id: str,
    ) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM assessment_reference_solutions WHERE question_revision_id=?",
                (question_revision_id,),
            ).fetchone()
            is not None
        )

    @staticmethod
    def synthesize_deterministic_reference(
        question: dict[str, Any],
    ) -> AssessmentReferenceSolutionOutput:
        """A deterministic question's reference is derived from its frozen answer
        key with no model call, so it can never drift from the stored standard."""
        answer_key = question.get("answer_key") or {}
        if question["question_type"] == "MCQ_SINGLE":
            answer = f"The correct option is {answer_key.get('correct_option')}."
        elif question["question_type"] == "NUMERIC":
            answer = f"The result is {answer_key.get('value')}."
        else:
            accepted = answer_key.get("accepted") or []
            answer = "One accepted answer is " + (str(accepted[0]) if accepted else "—") + "."
        step = AssessmentSolutionStep(
            step_id="step_1",
            ordinal=1,
            operation="Identify the correct result",
            result=answer,
            explanation=answer,
            source_refs=[],
        )
        return AssessmentReferenceSolutionOutput(schema_version="v3.2", answer=answer, steps=[step])

    def _store_reference_solution(
        self,
        connection: sqlite3.Connection,
        question_revision_id: str,
        blueprint_item_id: str | None,
        answer: str,
        steps: list[Any],
    ) -> None:
        steps_json = [step.model_dump() for step in steps]
        source_refs = sorted({ref for step in steps for ref in step.source_refs})
        content = {"answer": answer, "steps": steps_json, "source_refs": source_refs}
        connection.execute(
            "INSERT OR IGNORE INTO assessment_reference_solutions("
            "id,question_revision_id,blueprint_item_id,solution_revision,steps_json,"
            "answer_json,source_refs_json,prompt_version,content_hash) "
            "VALUES(?,?,?,1,?,?,?,?,?)",
            (
                identifier(),
                question_revision_id,
                blueprint_item_id,
                encode(steps_json),
                encode(answer),
                encode(source_refs),
                "problem-v3.2",
                digest(content),
            ),
        )

    def store_reference_solutions(
        self,
        connection: sqlite3.Connection,
        solutions: dict[str, Any],
    ) -> None:
        for question_revision_id, solution in solutions.items():
            if not self.has_reference_solution(connection, question_revision_id):
                self._store_reference_solution(
                    connection,
                    question_revision_id,
                    None,
                    solution.answer,
                    solution.steps,
                )

    def reference_solution(
        self,
        connection: sqlite3.Connection,
        question_revision_id: str,
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM assessment_reference_solutions WHERE question_revision_id=? "
            "ORDER BY solution_revision DESC LIMIT 1",
            (question_revision_id,),
        ).fetchone()

    def explanation_context(
        self,
        connection: sqlite3.Connection,
        workspace: sqlite3.Row,
        session_id: str,
        blueprint_item_id: str,
        step_id: str,
    ) -> dict[str, Any]:
        """Resolve the 详解 context by assessment_id + blueprint_item_id +
        solution_revision + step_id. Never fakes a cmui_exercises id and never
        reveals a reference step before grading."""
        session = connection.execute(
            "SELECT * FROM assessment_sessions WHERE id=? AND workspace_id=? AND owner_user_id=?",
            (session_id, workspace["id"], workspace["owner_user_id"]),
        ).fetchone()
        if session is None:
            raise ApiError(404, "ASSESSMENT_NOT_FOUND", "The Assessment was not found.")
        if session["status"] not in {"SUBMITTED", "GRADED"}:
            raise ApiError(
                409,
                "ASSESSMENT_NOT_GRADED",
                "Reference step explanations are available only after grading.",
            )
        item = connection.execute(
            "SELECT question_revision_id FROM assessment_blueprint_items WHERE id=?",
            (blueprint_item_id,),
        ).fetchone()
        if item is None:
            raise ApiError(404, "ASSESSMENT_ITEM_NOT_FOUND", "The frozen Assessment question was not found.")
        reference = self.reference_solution(connection, str(item["question_revision_id"]))
        if reference is None:
            raise ApiError(404, "REFERENCE_SOLUTION_NOT_FOUND", "No frozen reference solution exists.")
        steps = json.loads(reference["steps_json"])
        if not any(str(step.get("step_id")) == step_id for step in steps):
            raise ApiError(404, "REFERENCE_STEP_NOT_FOUND", "The reference step was not found.")
        solution_revision = int(reference["solution_revision"])
        existing = connection.execute(
            "SELECT * FROM assessment_explanation_contexts WHERE assessment_session_id=? "
            "AND blueprint_item_id=? AND solution_revision=? AND step_id=?",
            (session_id, blueprint_item_id, solution_revision, step_id),
        ).fetchone()
        if existing is None:
            context_id = identifier()
            connection.execute(
                "INSERT INTO assessment_explanation_contexts("
                "id,assessment_session_id,blueprint_item_id,solution_revision,step_id,"
                "owner_user_id) VALUES(?,?,?,?,?,?)",
                (
                    context_id,
                    session_id,
                    blueprint_item_id,
                    solution_revision,
                    step_id,
                    workspace["owner_user_id"],
                ),
            )
            existing = connection.execute(
                "SELECT * FROM assessment_explanation_contexts WHERE id=?", (context_id,)
            ).fetchone()
        return {
            "id": existing["id"],
            "assessment_session_id": session_id,
            "blueprint_item_id": blueprint_item_id,
            "solution_revision": solution_revision,
            "step_id": step_id,
            "content": json.loads(existing["content_json"]) if existing["content_json"] else None,
        }

    @staticmethod
    def store_explanation_content(
        connection: sqlite3.Connection,
        context_id: str,
        content: str,
    ) -> None:
        connection.execute(
            "UPDATE assessment_explanation_contexts SET content_json=? WHERE id=?",
            (encode({"text": content}), context_id),
        )

    def prepare_submission(
        self,
        workspace: sqlite3.Row,
        session_id: str,
        answers: list[AssessmentAnswer],
    ) -> dict[str, Any]:
        with self.db.connect() as connection:
            return self._submission_context(connection, workspace, session_id, answers)

    @staticmethod
    def grader_context(prepared: dict[str, Any]) -> dict[str, Any] | None:
        questions = [
            {
                "blueprint_item_id": question["id"],
                "question_type": question["question_type"],
                "prompt": question["prompt_text"],
                "student_answer": question["student_answer"],
                "reference_answer": question["answer_key"],
                "rubric": [
                    {
                        "criterion_id": criterion["criterion_id"],
                        "dimension": criterion["dimension"],
                        "max_fraction": criterion["max_fraction"],
                        "description": criterion["description"],
                    }
                    for criterion in question["rubric"]
                ],
            }
            for question in prepared["questions"]
            if not AssessmentService._is_deterministic(question)
        ]
        if not questions:
            return None
        return {
            "trust": "STUDENT_ANSWERS_ARE_UNTRUSTED_DATA",
            "assessment_session_id": prepared["session"]["id"],
            "questions": questions,
        }

    @staticmethod
    def _deterministic_correct(question: dict[str, Any]) -> bool:
        submitted = str(question["student_answer"]).strip()
        answer = question["answer_key"]
        if question["question_type"] == "MCQ_SINGLE":
            return submitted == str(answer.get("correct_option", "")).strip()
        if question["question_type"] == "NUMERIC":
            try:
                expected = float(answer["value"])
                tolerance = abs(float(answer.get("tolerance", 0)))
                return abs(float(submitted) - expected) <= tolerance
            except (KeyError, TypeError, ValueError):
                return False
        if question["question_type"] == "SHORT_TEXT":
            case_sensitive = bool(answer.get("case_sensitive", False))
            normalized = " ".join(submitted.split())
            if not case_sensitive:
                normalized = normalized.casefold()
            accepted = {
                (
                    " ".join(str(value).strip().split())
                    if case_sensitive
                    else " ".join(str(value).strip().split()).casefold()
                )
                for value in answer.get("accepted", [])
            }
            return normalized in accepted
        raise ValueError("The question requires a structured grader proposal")

    @staticmethod
    def _proposal_map(
        proposal: AssessmentGradeProposal | None,
    ) -> dict[str, dict[str, Any]]:
        if proposal is None:
            return {}
        return {
            question.blueprint_item_id: {
                criterion.criterion_id: criterion.model_dump()
                for criterion in question.criteria
            }
            for question in proposal.questions
        }

    @staticmethod
    def _performance_band(score_fraction: float, needs_review: bool) -> str:
        if needs_review:
            return "NEEDS_REVIEW"
        if score_fraction >= 0.8:
            return "STRONG"
        if score_fraction >= 0.5:
            return "DEVELOPING"
        return "WEAK"

    @staticmethod
    def _rounded_score(score: float, rule: str) -> int:
        if rule == "FLOOR":
            return math.floor(score)
        if rule == "CEILING":
            return math.ceil(score)
        return math.floor(score + 0.5)

    @classmethod
    def _mapped_grade(
        cls,
        raw_score: float,
        policy: sqlite3.Row,
        mapping_status: str,
    ) -> tuple[str | None, float | None]:
        if mapping_status == "UNCONFIGURED":
            return None, None
        rounded = cls._rounded_score(raw_score, str(policy["rounding_rule"]))
        bands = json.loads(policy["raw_score_bands_json"])
        band = next(
            (
                item
                for item in bands
                if int(item["minimum"]) <= rounded <= int(item["maximum"])
            ),
            None,
        )
        if band is None:
            raise ValueError("Published GradePolicy does not cover the raw score")
        scale = {
            item["letter"]: item["numeric_value"]
            for item in json.loads(policy["numeric_scale_json"])
        }
        numeric = scale.get(band["letter"])
        if numeric is None:
            raise ValueError("Published GradePolicy has an unmapped letter")
        return str(band["letter"]), float(numeric)

    def save_submission(
        self,
        connection: sqlite3.Connection,
        workspace: sqlite3.Row,
        session_id: str,
        answers: list[AssessmentAnswer],
        proposal: AssessmentGradeProposal | None,
    ) -> dict[str, Any]:
        prepared = self._submission_context(connection, workspace, session_id, answers)
        session = prepared["session"]
        proposals = self._proposal_map(proposal)
        open_item_ids = {
            str(question["id"])
            for question in prepared["questions"]
            if not self._is_deterministic(question)
        }
        if set(proposals) != open_item_ids:
            raise ValueError("The grader proposal does not match the open-response questions")
        submission_revision = self._record_submission_revision(
            connection, session_id, answers
        )
        grader_input = self.grader_context(prepared)
        grader_input_hash = digest(grader_input) if grader_input is not None else None
        if grader_input_hash is not None:
            connection.execute(
                "INSERT OR IGNORE INTO assessment_grading_receipts("
                "id,session_id,submission_revision,grader_input_hash,grade_proposal_json) "
                "VALUES(?,?,?,?,?)",
                (
                    identifier(),
                    session_id,
                    submission_revision,
                    grader_input_hash,
                    encode(proposal.model_dump()) if proposal is not None else None,
                ),
            )
        independent = session["mode"] == "INDEPENDENT"
        total = 0.0
        any_needs_review = False
        weak_evidence_ids: list[str] = []
        for question in prepared["questions"]:
            attempt = connection.execute(
                "SELECT * FROM assessment_question_attempts "
                "WHERE session_id=? AND blueprint_item_id=?",
                (session_id, question["id"]),
            ).fetchone()
            if attempt is None:
                raise ValueError("A frozen Assessment attempt is missing")
            criterion_proposals = proposals.get(str(question["id"]), {})
            expected_criteria = {
                str(criterion["criterion_id"]) for criterion in question["rubric"]
            }
            if criterion_proposals and set(criterion_proposals) != expected_criteria:
                raise ValueError("The grader proposal does not match the frozen rubric")
            correct = (
                self._deterministic_correct(question)
                if self._is_deterministic(question)
                else False
            )
            question_total = 0.0
            feedback_parts: list[str] = []
            question_needs_review = False
            for criterion in question["rubric"]:
                if self._is_deterministic(question):
                    fraction = 1.0 if correct else 0.0
                    needs_review = False
                    confidence = 1.0
                    answer_evidence = "submitted_answer"
                    feedback = (
                        "Deterministic check matched the frozen answer."
                        if correct
                        else "Deterministic check did not match the frozen answer."
                    )
                else:
                    proposed = criterion_proposals[str(criterion["criterion_id"])]
                    fraction = float(proposed["score_fraction"])
                    needs_review = bool(proposed["needs_review"])
                    confidence = float(proposed["confidence"])
                    answer_evidence = str(proposed["answer_evidence"])
                    feedback = str(proposed["feedback"])
                maximum = (
                    float(question["marks"]) * float(criterion["max_fraction"]) / 100
                )
                awarded = round(maximum * fraction, 4)
                question_total += awarded
                band = self._performance_band(fraction, needs_review)
                evidence_id = identifier()
                connection.execute(
                    "INSERT INTO performance_evidence("
                    "id,workspace_id,assessment_session_id,question_attempt_id,"
                    "question_revision_id,criterion_id,node_id,spec_version,item_id,"
                    "dimension,awarded_marks,max_marks,confidence,independent_eligible,"
                    "performance_band,evidence_locator,source_kind,content_hash) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        evidence_id,
                        workspace["id"],
                        session_id,
                        attempt["id"],
                        question["question_revision_id"],
                        criterion["criterion_id"],
                        criterion["node_id"],
                        criterion["spec_version"],
                        criterion["item_id"],
                        criterion["dimension"],
                        awarded,
                        maximum,
                        confidence,
                        int(independent),
                        band,
                        answer_evidence or "submitted_answer",
                        question["source_kind"],
                        digest(
                            {
                                "attempt_id": attempt["id"],
                                "criterion_id": criterion["criterion_id"],
                                "answer": question["student_answer"],
                                "awarded": awarded,
                                "maximum": maximum,
                                "confidence": confidence,
                                "independent": independent,
                                "band": band,
                            }
                        ),
                    ),
                )
                if band == "WEAK":
                    weak_evidence_ids.append(evidence_id)
                question_needs_review = question_needs_review or needs_review
                feedback_parts.append(feedback)
            total += question_total
            any_needs_review = any_needs_review or question_needs_review
            connection.execute(
                "UPDATE assessment_question_attempts SET status=?,answer_json=?,"
                "awarded_marks=?,feedback=?,grading_version=1,answered_at="
                "strftime('%Y-%m-%dT%H:%M:%fZ','now'),graded_at="
                "strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (
                    "NEEDS_REVIEW" if question_needs_review else "GRADED",
                    encode({"answer": question["student_answer"]}),
                    round(question_total, 4),
                    " ".join(dict.fromkeys(feedback_parts)),
                    attempt["id"],
                ),
            )
        total = round(total, 4)
        if any_needs_review:
            connection.execute(
                "UPDATE assessment_sessions SET status='SUBMITTED',submitted_at="
                "strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (session_id,),
            )
        else:
            policy = connection.execute(
                "SELECT policy.*,binding.mapping_status "
                "FROM assessment_blueprint_grade_policies AS binding "
                "JOIN grade_policy_versions AS policy "
                "ON policy.id=binding.grade_policy_version_id "
                "WHERE binding.blueprint_id=?",
                (session["blueprint_id"],),
            ).fetchone()
            if policy is None:
                raise ValueError("The frozen GradePolicy binding is missing")
            grade_label, numeric_value = self._mapped_grade(
                total,
                policy,
                str(policy["mapping_status"]),
            )
            summary = {
                "weak_evidence_ids": weak_evidence_ids,
                "evidence_count": connection.execute(
                    "SELECT COUNT(*) FROM performance_evidence "
                    "WHERE assessment_session_id=?",
                    (session_id,),
                ).fetchone()[0],
            }
            connection.execute(
                "INSERT INTO grade_snapshots("
                "id,assessment_session_id,revision,grade_policy_version_id,"
                "mapping_status,raw_score,grade_label,numeric_value,"
                "independent_eligible,criterion_summary_json,content_hash) "
                "VALUES(?,?,1,?,?,?,?,?,?,?,?)",
                (
                    identifier(),
                    session_id,
                    policy["id"],
                    policy["mapping_status"],
                    total,
                    grade_label,
                    numeric_value,
                    int(independent),
                    encode(summary),
                    digest(
                        {
                            "session_id": session_id,
                            "raw_score": total,
                            "grade_label": grade_label,
                            "numeric_value": numeric_value,
                            "policy_id": policy["id"],
                            "independent": independent,
                            "summary": summary,
                        }
                    ),
                ),
            )
            connection.execute(
                "UPDATE assessment_sessions SET status='GRADED',submitted_at="
                "strftime('%Y-%m-%dT%H:%M:%fZ','now'),graded_at="
                "strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (session_id,),
            )
            if weak_evidence_ids:
                connection.execute(
                    "INSERT INTO learning_replan_triggers("
                    "id,workspace_id,node_id,trigger_kind,source_assessment_session_id,"
                    "performance_evidence_ids_json,reason_summary) "
                    "VALUES(?,?,?,'ASSESSMENT_WEAKNESS',?,?,?)",
                    (
                        identifier(),
                        workspace["id"],
                        session["node_id"],
                        session_id,
                        encode(weak_evidence_ids),
                        "Assessment evidence marked one or more rubric criteria WEAK.",
                    ),
                )
        return self._session_view(connection, workspace, session_id)

    def assist(
        self,
        connection: sqlite3.Connection,
        workspace: sqlite3.Row,
        session_id: str,
        blueprint_item_id: str,
        action: str,
    ) -> dict[str, Any]:
        session = connection.execute(
            "SELECT * FROM assessment_sessions WHERE id=? AND workspace_id=? "
            "AND owner_user_id=?",
            (session_id, workspace["id"], workspace["owner_user_id"]),
        ).fetchone()
        if session is None:
            raise ApiError(404, "ASSESSMENT_NOT_FOUND", "The Assessment was not found.")
        if session["status"] != "IN_PROGRESS":
            raise ApiError(
                409,
                "ASSESSMENT_NOT_ACTIVE",
                "Assistance can only be recorded during an in-progress Assessment.",
            )
        attempt = connection.execute(
            "SELECT attempt.*,item.question_revision_id,item.family_id "
            "FROM assessment_question_attempts AS attempt "
            "JOIN assessment_blueprint_items AS item ON item.id=attempt.blueprint_item_id "
            "WHERE attempt.session_id=? AND attempt.blueprint_item_id=?",
            (session_id, blueprint_item_id),
        ).fetchone()
        if attempt is None:
            raise ApiError(
                404,
                "ASSESSMENT_ITEM_NOT_FOUND",
                "The frozen Assessment question was not found.",
            )
        assistance = "ANSWER_REVEALED" if action == "ANSWER_REVEALED" else action
        session_assistance = (
            "ANSWER_EXPOSED" if action == "ANSWER_REVEALED" else "ASSISTED"
        )
        connection.execute(
            "UPDATE assessment_sessions SET mode='PRACTICE',assistance_status=? WHERE id=?",
            (session_assistance, session_id),
        )
        connection.execute(
            "UPDATE assessment_question_attempts SET assistance=? WHERE id=?",
            (assistance, attempt["id"]),
        )
        exposure_kind = (
            "ANSWER_REVEALED" if action == "ANSWER_REVEALED" else "TEACHING_HELP"
        )
        connection.execute(
            "INSERT OR IGNORE INTO assessment_exposure_events("
            "id,workspace_id,session_id,question_revision_id,family_id,exposure_kind) "
            "VALUES(?,?,?,?,?,?)",
            (
                identifier(),
                workspace["id"],
                session_id,
                attempt["question_revision_id"],
                attempt["family_id"],
                exposure_kind,
            ),
        )
        result = self._session_view(connection, workspace, session_id)
        result["assistance_message"] = (
            "答案已展示；本次测评已转为练习，不计为独立测评。"
            if action == "ANSWER_REVEALED"
            else "已记录辅助；本次测评已转为练习，不计为独立测评。"
        )
        return result

    def abandon(
        self,
        connection: sqlite3.Connection,
        workspace: sqlite3.Row,
        session_id: str,
    ) -> dict[str, Any]:
        updated = connection.execute(
            "UPDATE assessment_sessions SET status='ABANDONED' "
            "WHERE id=? AND workspace_id=? AND owner_user_id=? AND status='IN_PROGRESS'",
            (session_id, workspace["id"], workspace["owner_user_id"]),
        )
        if updated.rowcount != 1:
            exists = connection.execute(
                "SELECT 1 FROM assessment_sessions WHERE id=? AND workspace_id=? "
                "AND owner_user_id=?",
                (session_id, workspace["id"], workspace["owner_user_id"]),
            ).fetchone()
            if exists is None:
                raise ApiError(
                    404,
                    "ASSESSMENT_NOT_FOUND",
                    "The Assessment was not found.",
                )
            raise ApiError(
                409,
                "ASSESSMENT_NOT_ACTIVE",
                "Only an in-progress Assessment can be abandoned.",
            )
        return self._session_view(connection, workspace, session_id)

    @staticmethod
    def _policy_is_complete(payload: GradePolicyDraftInput) -> bool:
        scale = {item.letter: item.numeric_value for item in payload.numeric_scale}
        coverage: list[int] = []
        for band in payload.raw_score_bands:
            if band.letter not in scale or scale[band.letter] is None:
                return False
            coverage.extend(range(band.minimum, band.maximum + 1))
        return (
            payload.rounding_rule is not None
            and sorted(coverage) == list(range(101))
            and len(coverage) == len(set(coverage))
        )

    @staticmethod
    def _policy_view(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "scope_type": row["scope_type"],
            "scope_id": row["scope_id"],
            "version": row["version"],
            "status": row["status"],
            "display_name": row["display_name"],
            "provenance_label": row["provenance_label"],
            "numeric_scale": json.loads(row["numeric_scale_json"]),
            "raw_score_bands": json.loads(row["raw_score_bands_json"]),
            "rounding_rule": row["rounding_rule"],
            "pass_rule": row["pass_rule"],
            "retake_rule": row["retake_rule"],
            "content_hash": row["content_hash"],
            "published_at": row["published_at"],
        }

    def create_grade_policy(
        self,
        owner: str,
        payload: GradePolicyDraftInput,
    ) -> dict[str, Any]:
        provenance = payload.provenance_label.casefold()
        if "cityu" in provenance and "official" in provenance:
            raise ApiError(
                422,
                "GRADE_POLICY_PROVENANCE_UNVERIFIED",
                "Do not label an unverified mapping as an official CityU policy.",
            )
        with self.db.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if payload.scope_type == "PLATFORM" and payload.scope_id != "platform":
                raise ApiError(
                    422,
                    "GRADE_POLICY_SCOPE_INVALID",
                    "The platform GradePolicy scope ID must be 'platform'.",
                )
            if payload.scope_type == "COURSE" and connection.execute(
                "SELECT 1 FROM courses WHERE id=?", (payload.scope_id,)
            ).fetchone() is None:
                raise ApiError(404, "COURSE_NOT_FOUND", "The course was not found.")
            if payload.scope_type == "NODE" and connection.execute(
                "SELECT 1 FROM knowledge_nodes WHERE id=?", (payload.scope_id,)
            ).fetchone() is None:
                raise ApiError(404, "NODE_NOT_FOUND", "The knowledge node was not found.")
            previous = connection.execute(
                "SELECT * FROM grade_policy_versions WHERE scope_type=? AND scope_id=? "
                "ORDER BY version DESC LIMIT 1",
                (payload.scope_type, payload.scope_id),
            ).fetchone()
            version = int(previous["version"] if previous is not None else 0) + 1
            content = {
                "scope_type": payload.scope_type,
                "scope_id": payload.scope_id,
                "version": version,
                "display_name": payload.display_name,
                "provenance_label": payload.provenance_label,
                "numeric_scale": [item.model_dump() for item in payload.numeric_scale],
                "raw_score_bands": [item.model_dump() for item in payload.raw_score_bands],
                "rounding_rule": payload.rounding_rule,
                "pass_rule": payload.pass_rule,
                "retake_rule": payload.retake_rule,
            }
            policy_id = identifier()
            status = (
                "DRAFT_VALID" if self._policy_is_complete(payload) else "DRAFT_UNCONFIGURED"
            )
            connection.execute(
                "INSERT INTO grade_policy_versions("
                "id,scope_type,scope_id,version,status,display_name,provenance_label,"
                "numeric_scale_json,raw_score_bands_json,rounding_rule,pass_rule,"
                "retake_rule,content_hash,created_by_user_id,supersedes_policy_id) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    policy_id,
                    payload.scope_type,
                    payload.scope_id,
                    version,
                    status,
                    payload.display_name,
                    payload.provenance_label,
                    encode(content["numeric_scale"]),
                    encode(content["raw_score_bands"]),
                    payload.rounding_rule,
                    payload.pass_rule,
                    payload.retake_rule,
                    digest(content),
                    owner,
                    previous["id"] if previous is not None else None,
                ),
            )
            row = connection.execute(
                "SELECT * FROM grade_policy_versions WHERE id=?", (policy_id,)
            ).fetchone()
        return self._policy_view(cast(sqlite3.Row, row))

    def publish_grade_policy(self, owner: str, policy_id: str) -> dict[str, Any]:
        with self.db.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM grade_policy_versions WHERE id=?", (policy_id,)
            ).fetchone()
            if row is None:
                raise ApiError(
                    404,
                    "GRADE_POLICY_NOT_FOUND",
                    "The GradePolicy version was not found.",
                )
            if row["status"] != "DRAFT_VALID":
                raise ApiError(
                    409,
                    "GRADE_POLICY_UNCONFIGURED",
                    "Only a complete, validated GradePolicy draft can be published.",
                )
            connection.execute(
                "UPDATE grade_policy_versions SET status='RETIRED',"
                "published_by_user_id=NULL,published_at=NULL "
                "WHERE scope_type=? AND scope_id=? AND status='PUBLISHED'",
                (row["scope_type"], row["scope_id"]),
            )
            connection.execute(
                "UPDATE grade_policy_versions SET status='PUBLISHED',"
                "published_by_user_id=?,"
                "published_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (owner, policy_id),
            )
            published = connection.execute(
                "SELECT * FROM grade_policy_versions WHERE id=?", (policy_id,)
            ).fetchone()
        return self._policy_view(cast(sqlite3.Row, published))

    def grade_policies(self) -> list[dict[str, Any]]:
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM grade_policy_versions "
                "ORDER BY scope_type,scope_id,version DESC"
            ).fetchall()
        return [self._policy_view(row) for row in rows]

    def preview_grade_policy(self, policy_id: str, raw_score: float) -> dict[str, Any]:
        with self.db.connect() as connection:
            policy = connection.execute(
                "SELECT * FROM grade_policy_versions WHERE id=?", (policy_id,)
            ).fetchone()
        if policy is None:
            raise ApiError(
                404,
                "GRADE_POLICY_NOT_FOUND",
                "The GradePolicy version was not found.",
            )
        mapping_status = (
            "CONFIGURED"
            if policy["status"] in {"DRAFT_VALID", "PUBLISHED"}
            else "UNCONFIGURED"
        )
        label, numeric = self._mapped_grade(raw_score, policy, mapping_status)
        return {
            "raw_score": raw_score,
            "mapping_status": mapping_status,
            "label": label,
            "numeric_value": numeric,
            "message": (
                "评分映射待配置"
                if mapping_status == "UNCONFIGURED"
                else "Preview only; no learner grade was written."
            ),
            "policy": self._policy_view(policy),
        }
