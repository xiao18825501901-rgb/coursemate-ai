"""Run the existing Question Engine stages for one practice exercise.

This module is the application boundary between the refreshed ``做一题`` action
and the Stage 1--7 contracts.  It does not create a second question store: a
successful result is an immutable Assessment question revision plus its existing
rubric/reference solution and Question Engine provenance row.

The returned object deliberately separates ``public`` from ``private``.  Only
the mounted UI's server-side run worker receives the private projection, stores
it in the already-private exercise row, and reveals it through the existing
explicit reveal endpoint.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Literal
from uuid import uuid4

from pydantic import Field

from app.db import Database
from app.errors import ApiError
from app.jev import callsites
from app.jev.service import SemanticDecisionService
from app.learning.blind_solve import BlindSolveError, run_blind_solve
from app.learning.models import Contract, Identifier, Text
from app.learning.practice_feedback import (
    PracticeInteractionError,
    generate_practice_feedback,
    generate_practice_hint,
)
from app.learning.question_author import (
    QUESTION_AUTHOR_PROMPT_VERSION,
    AuthorGenerationError,
    author_question,
)
from app.learning.question_blueprint import (
    Hex64,
    ObjectiveResolutionError,
    QuestionBlueprint,
    TeachingObjective,
    resolve_objective,
)
from app.learning.question_evidence import (
    EvidencePackAccess,
    EvidencePackError,
    QuestionEvidencePack,
    build_evidence_pack,
)
from app.learning.question_persistence import (
    QuestionPersistenceError,
    persist_question_candidate,
)
from app.learning.question_validator import (
    collect_question_semantic_signals,
    validate_question_candidate,
)
from app.learning.workspaces import workspace_for

GENERATION_VERSION: Final = "exercise.v2+question-engine.v1"
GENERATION_POLICY_VERSION: Final = "question-generation-policy-v1"


class QuestionEngineRuntimeError(RuntimeError):
    """Stable runtime refusal that never includes provider bodies or private answers."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ExerciseReference(Contract):
    id: Identifier
    document_id: Identifier
    document_version_id: Identifier
    filename: str
    source_scope: Literal["OFFICIAL", "OWNER_COURSE", "WORKSPACE_PRIVATE"]
    locator_type: str
    locator_value: str
    section: str | None = None


class ExerciseAnswerStep(Contract):
    step_id: Identifier
    ordinal: int
    title: Text
    text: Text
    source_refs: list[Identifier] = Field(min_length=1, max_length=20)


class PrivateExerciseProjection(Contract):
    answer: Text
    steps: list[ExerciseAnswerStep] = Field(min_length=1, max_length=12)


class PublicExerciseProjection(Contract):
    schema_version: Literal["exercise.v2"]
    blueprint_id: Identifier
    question_revision: Hex64
    question_type: Literal["MCQ_SINGLE", "NUMERIC", "SHORT_TEXT", "EXPLANATION", "CODE"]
    marks: int = Field(ge=1, le=100)
    question_text: Text
    options: list[str] = Field(max_length=10)
    source_refs: list[Identifier] = Field(min_length=1, max_length=20)
    answer_policy: Literal["HIDDEN_UNTIL_REVEAL", "SOLUTION_ONLY"]


class GeneratedExercise(Contract):
    question_revision_id: Identifier
    blueprint_id: Identifier
    status: Literal["READY"]
    verification_status: Literal["AI_REVIEWED"]
    generation_version: Literal["exercise.v2+question-engine.v1"]
    prototype_id: Literal["worked_application", "concept_short_answer"]
    public: PublicExerciseProjection
    private: PrivateExerciseProjection
    references: list[ExerciseReference] = Field(min_length=1, max_length=20)
    usage: list[dict[str, Any]] = Field(min_length=3, max_length=3)


@dataclass(frozen=True)
class _Prototype:
    prototype_id: Literal["worked_application", "concept_short_answer"]
    bloom_target: Literal["UNDERSTAND", "APPLY"]
    target_difficulty: int
    difficulty_features: tuple[Literal["STEPS", "CONCEPTS"], ...]
    question_type: Literal["SHORT_TEXT", "EXPLANATION"]
    expected_answer_form: Literal["SHORT_ANSWER", "WORKED_STEPS"]


_PROTOTYPES: Final[dict[str, _Prototype]] = {
    "worked_application": _Prototype(
        prototype_id="worked_application",
        bloom_target="APPLY",
        target_difficulty=3,
        difficulty_features=("STEPS", "CONCEPTS"),
        question_type="EXPLANATION",
        expected_answer_form="WORKED_STEPS",
    ),
    "concept_short_answer": _Prototype(
        prototype_id="concept_short_answer",
        bloom_target="UNDERSTAND",
        target_difficulty=2,
        difficulty_features=("CONCEPTS",),
        question_type="SHORT_TEXT",
        expected_answer_form="SHORT_ANSWER",
    ),
}


def _hash(*parts: object) -> str:
    payload = json.dumps(parts, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _public_run(run: object) -> dict[str, Any]:
    """Keep cost/provenance metadata while excluding any model output."""

    if hasattr(run, "model_dump"):
        value = run.model_dump(mode="json")
    elif isinstance(run, dict):
        value = dict(run)
    else:
        return {}
    allowed = {
        "model",
        "provider",
        "protocol",
        "region",
        "role",
        "template_version",
        "schema_version",
        "input_hash",
        "started_at",
        "finished_at",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "provider_response_id",
        "status",
        "error_class",
    }
    return {key: value[key] for key in allowed if key in value}


class QuestionEngineRuntime:
    """Orchestrate one owner/workspace-scoped practice question."""

    def __init__(
        self,
        *,
        database: Database,
        provider: Any,
        semantic_decisions: SemanticDecisionService | None,
    ) -> None:
        self.database = database
        self.provider = provider
        self.semantic_decisions = semantic_decisions

    def _recent_exposures(self, workspace_id: str, node_id: str) -> list[str]:
        with self.database.connect() as connection:
            return [
                str(row["family_id"])
                for row in connection.execute(
                    "SELECT question.family_id FROM question_engine_provenance AS provenance "
                    "JOIN assessment_question_revisions AS question "
                    "ON question.id=provenance.question_revision_id "
                    "WHERE provenance.workspace_id=? AND provenance.node_id=? "
                    "ORDER BY question.rowid DESC LIMIT 10",
                    (workspace_id, node_id),
                ).fetchall()
            ]

    def _practice_context(
        self,
        *,
        owner_user_id: str,
        workspace_id: str,
        question_revision_id: str,
    ) -> dict[str, Any]:
        """Load one READY revision through its exact owner/workspace boundary."""

        workspace_for(self.database, workspace_id, owner_user_id)
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT question.prompt_text,question.options_json,"
                "provenance.node_id,provenance.spec_version,provenance.objective_id,"
                "provenance.blueprint_json,reference.steps_json,reference.answer_json "
                "FROM question_engine_provenance AS provenance "
                "JOIN assessment_question_revisions AS question "
                "ON question.id=provenance.question_revision_id "
                "JOIN learning_workspaces AS workspace ON workspace.id=provenance.workspace_id "
                "JOIN assessment_reference_solutions AS reference "
                "ON reference.question_revision_id=question.id "
                "WHERE provenance.question_revision_id=? AND provenance.workspace_id=? "
                "AND provenance.publication_status='READY' "
                "AND question.owner_user_id=? AND workspace.owner_user_id=? "
                "ORDER BY reference.solution_revision DESC LIMIT 1",
                (
                    question_revision_id,
                    workspace_id,
                    owner_user_id,
                    owner_user_id,
                ),
            ).fetchone()
            if row is None:
                raise QuestionEngineRuntimeError(
                    "PRACTICE_QUESTION_NOT_FOUND",
                    "The READY practice question is not available in this learner workspace.",
                )
            rubric_rows = connection.execute(
                "SELECT criterion_id,dimension,max_fraction,description "
                "FROM assessment_rubric_criteria WHERE question_revision_id=? "
                "ORDER BY criterion_id",
                (question_revision_id,),
            ).fetchall()
        try:
            blueprint = json.loads(row["blueprint_json"])
            options = json.loads(row["options_json"])
            steps = json.loads(row["steps_json"])
            answer = json.loads(row["answer_json"])
        except (TypeError, ValueError) as error:
            raise QuestionEngineRuntimeError(
                "PRACTICE_REFERENCE_INVALID",
                "The immutable practice reference could not be verified.",
            ) from error
        rubric = [dict(item) for item in rubric_rows]
        if not rubric:
            raise QuestionEngineRuntimeError(
                "PRACTICE_RUBRIC_MISSING", "The practice rubric is unavailable."
            )
        return {
            "question_revision_id": question_revision_id,
            "question": {"text": row["prompt_text"], "options": options},
            "objective": {
                "node_id": row["node_id"],
                "spec_version": row["spec_version"],
                "objective_id": row["objective_id"],
                "text": blueprint.get("objective_text"),
            },
            "rubric": rubric,
            "reference_solution": {"answer": answer, "steps": steps},
        }

    def _claim_practice_operation(
        self,
        *,
        owner_user_id: str,
        workspace_id: str,
        question_revision_id: str,
        operation_id: str,
        kind: Literal["HINT", "ATTEMPT"],
        input_hash: str,
    ) -> dict[str, Any] | None:
        if not 8 <= len(operation_id.strip()) <= 100:
            raise QuestionEngineRuntimeError(
                "PRACTICE_OPERATION_REQUIRED",
                "A stable practice operation id between 8 and 100 characters is required.",
            )
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            inserted = connection.execute(
                "INSERT OR IGNORE INTO practice_interaction_operations("
                "workspace_id,operation_id,question_revision_id,owner_user_id,kind,"
                "input_hash,status) "
                "VALUES(?,?,?,?,?,?,'CLAIMED')",
                (
                    workspace_id,
                    operation_id,
                    question_revision_id,
                    owner_user_id,
                    kind,
                    input_hash,
                ),
            ).rowcount
            row = connection.execute(
                "SELECT * FROM practice_interaction_operations "
                "WHERE workspace_id=? AND operation_id=?",
                (workspace_id, operation_id),
            ).fetchone()
        if inserted == 1:
            return None
        if row is None or any(
            str(row[key]) != value
            for key, value in (
                ("question_revision_id", question_revision_id),
                ("owner_user_id", owner_user_id),
                ("kind", kind),
                ("input_hash", input_hash),
            )
        ):
            raise QuestionEngineRuntimeError(
                "PRACTICE_IDEMPOTENCY_CONFLICT",
                "The practice operation id is already bound to different input.",
            )
        if row["status"] == "COMPLETED":
            return json.loads(row["result_json"])
        if row["status"] == "FAILED":
            raise QuestionEngineRuntimeError(
                str(row["error_code"]),
                "The original practice operation failed and was not billed again.",
            )
        raise QuestionEngineRuntimeError(
            "PRACTICE_OPERATION_IN_PROGRESS",
            "The same practice operation is already in progress.",
        )

    def _fail_practice_operation(
        self, *, workspace_id: str, operation_id: str, error_code: str
    ) -> None:
        try:
            with self.database.connect() as connection:
                connection.execute(
                    "UPDATE practice_interaction_operations SET status='FAILED',error_code=?,"
                    "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                    "WHERE workspace_id=? AND operation_id=? AND status='CLAIMED'",
                    (error_code[:100], workspace_id, operation_id),
                )
        except Exception:
            # Preserve the original stable provider/contract failure. A stale
            # CLAIMED receipt still prevents a duplicate paid call.
            return

    def generate_hint(
        self,
        *,
        owner_user_id: str,
        workspace_id: str,
        question_revision_id: str,
        operation_id: str,
    ) -> dict[str, Any]:
        context = self._practice_context(
            owner_user_id=owner_user_id,
            workspace_id=workspace_id,
            question_revision_id=question_revision_id,
        )
        input_hash = _hash("HINT", question_revision_id, context)
        replay = self._claim_practice_operation(
            owner_user_id=owner_user_id,
            workspace_id=workspace_id,
            question_revision_id=question_revision_id,
            operation_id=operation_id,
            kind="HINT",
            input_hash=input_hash,
        )
        if replay is not None:
            return replay
        try:
            output, run = generate_practice_hint(self.provider, context=context)
            event_id = f"ph_{uuid4().hex}"
            result = {
                "id": event_id,
                "question_revision_id": question_revision_id,
                "assistance": "HINT",
                "independent": False,
                "hint": output.hint,
                "strategy": output.strategy,
                "usage": _public_run(run),
            }
            encoded_result = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
            with self.database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO practice_hint_events("
                    "id,workspace_id,question_revision_id,owner_user_id,operation_id,input_hash,"
                    "hint_json,provider_run_json) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        event_id,
                        workspace_id,
                        question_revision_id,
                        owner_user_id,
                        operation_id,
                        input_hash,
                        json.dumps(output.model_dump(mode="json"), ensure_ascii=False),
                        json.dumps(run.model_dump(mode="json"), ensure_ascii=False),
                    ),
                )
                updated = connection.execute(
                    "UPDATE practice_interaction_operations SET status='COMPLETED',result_json=?,"
                    "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                    "WHERE workspace_id=? AND operation_id=? AND status='CLAIMED'",
                    (encoded_result, workspace_id, operation_id),
                ).rowcount
                if updated != 1:
                    raise QuestionEngineRuntimeError(
                        "PRACTICE_OPERATION_LOST", "The hint operation receipt was lost."
                    )
            return result
        except QuestionEngineRuntimeError:
            raise
        except PracticeInteractionError as error:
            self._fail_practice_operation(
                workspace_id=workspace_id,
                operation_id=operation_id,
                error_code=error.code,
            )
            raise QuestionEngineRuntimeError(error.code, str(error)) from error

    def practice_state(
        self,
        *,
        owner_user_id: str,
        workspace_id: str,
        question_revision_id: str,
    ) -> dict[str, Any]:
        """Return the learner-visible interaction projection without private answers."""

        self._practice_context(
            owner_user_id=owner_user_id,
            workspace_id=workspace_id,
            question_revision_id=question_revision_id,
        )
        with self.database.connect() as connection:
            hint_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM practice_hint_events WHERE workspace_id=? "
                    "AND question_revision_id=?",
                    (workspace_id, question_revision_id),
                ).fetchone()[0]
            )
            hint = connection.execute(
                "SELECT operation.result_json FROM practice_hint_events AS event "
                "JOIN practice_interaction_operations AS operation "
                "ON operation.workspace_id=event.workspace_id "
                "AND operation.operation_id=event.operation_id "
                "WHERE event.workspace_id=? AND event.question_revision_id=? "
                "ORDER BY event.created_at DESC,event.rowid DESC LIMIT 1",
                (workspace_id, question_revision_id),
            ).fetchone()
            attempt = connection.execute(
                "SELECT operation.result_json FROM practice_question_attempts AS item "
                "JOIN practice_interaction_operations AS operation "
                "ON operation.workspace_id=item.workspace_id "
                "AND operation.operation_id=item.operation_id "
                "WHERE item.workspace_id=? AND item.question_revision_id=? "
                "ORDER BY item.created_at DESC,item.rowid DESC LIMIT 1",
                (workspace_id, question_revision_id),
            ).fetchone()
        return {
            "hint_count": hint_count,
            "latest_hint": json.loads(hint["result_json"]) if hint else None,
            "latest_attempt": json.loads(attempt["result_json"]) if attempt else None,
        }

    def grade_practice_attempt(
        self,
        *,
        owner_user_id: str,
        workspace_id: str,
        question_revision_id: str,
        operation_id: str,
        submitted_answer: str,
        answer_revealed: bool,
    ) -> dict[str, Any]:
        answer = submitted_answer.strip()
        if not 1 <= len(answer) <= 6000:
            raise QuestionEngineRuntimeError(
                "PRACTICE_ANSWER_INVALID",
                "A practice answer between 1 and 6000 characters is required.",
            )
        context = self._practice_context(
            owner_user_id=owner_user_id,
            workspace_id=workspace_id,
            question_revision_id=question_revision_id,
        )
        with self.database.connect() as connection:
            hinted = connection.execute(
                "SELECT 1 FROM practice_hint_events WHERE workspace_id=? "
                "AND question_revision_id=? LIMIT 1",
                (workspace_id, question_revision_id),
            ).fetchone()
        assistance = "ANSWER_REVEALED" if answer_revealed else "HINT" if hinted else "NONE"
        provider_context = {
            **context,
            "submitted_answer": answer,
            "assistance": assistance,
        }
        input_hash = _hash("ATTEMPT", question_revision_id, provider_context)
        replay = self._claim_practice_operation(
            owner_user_id=owner_user_id,
            workspace_id=workspace_id,
            question_revision_id=question_revision_id,
            operation_id=operation_id,
            kind="ATTEMPT",
            input_hash=input_hash,
        )
        if replay is not None:
            return replay
        try:
            output, run = generate_practice_feedback(self.provider, context=provider_context)
            expected = {str(item["criterion_id"]) for item in context["rubric"]}
            actual = {item.criterion_id for item in output.criteria}
            if actual != expected:
                raise PracticeInteractionError(
                    "PRACTICE_FEEDBACK_RUBRIC_MISMATCH",
                    "The feedback did not cover the immutable practice rubric.",
                )
            attempt_id = f"pa_{uuid4().hex}"
            status = "NEEDS_REVIEW" if output.verdict == "NEEDS_REVIEW" else "GRADED"
            result = {
                "id": attempt_id,
                "question_revision_id": question_revision_id,
                "verdict": output.verdict,
                "feedback": output.feedback,
                "strengths": output.strengths,
                "gaps": output.gaps,
                "next_step": output.next_step,
                "criteria": [item.model_dump(mode="json") for item in output.criteria],
                "assistance": assistance,
                "independent": assistance == "NONE",
                "status": status,
                "usage": _public_run(run),
            }
            encoded_result = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
            with self.database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO practice_question_attempts("
                    "id,workspace_id,question_revision_id,owner_user_id,operation_id,input_hash,"
                    "submitted_answer,assistance,status,feedback_json,provider_run_json) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        attempt_id,
                        workspace_id,
                        question_revision_id,
                        owner_user_id,
                        operation_id,
                        input_hash,
                        answer,
                        assistance,
                        status,
                        json.dumps(output.model_dump(mode="json"), ensure_ascii=False),
                        json.dumps(run.model_dump(mode="json"), ensure_ascii=False),
                    ),
                )
                updated = connection.execute(
                    "UPDATE practice_interaction_operations SET status='COMPLETED',result_json=?,"
                    "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                    "WHERE workspace_id=? AND operation_id=? AND status='CLAIMED'",
                    (encoded_result, workspace_id, operation_id),
                ).rowcount
                if updated != 1:
                    raise QuestionEngineRuntimeError(
                        "PRACTICE_OPERATION_LOST", "The attempt operation receipt was lost."
                    )
            return result
        except QuestionEngineRuntimeError:
            raise
        except PracticeInteractionError as error:
            self._fail_practice_operation(
                workspace_id=workspace_id,
                operation_id=operation_id,
                error_code=error.code,
            )
            raise QuestionEngineRuntimeError(error.code, str(error)) from error

    @staticmethod
    def _check_cancelled(should_cancel: Callable[[], bool] | None) -> None:
        """Fail closed between bounded external stages when the UI run was stopped.

        The provider SDK is synchronous, so an in-flight HTTP request remains
        bounded by its configured timeout.  This cooperative check guarantees
        that a cross-worker cancellation observed after that request cannot
        advance to another paid stage or publish a question revision.
        """

        if should_cancel is None:
            return
        try:
            cancelled = bool(should_cancel())
        except Exception as error:
            raise QuestionEngineRuntimeError(
                "QUESTION_CANCELLATION_CHECK_FAILED",
                "The exercise cancellation state could not be verified.",
            ) from error
        if cancelled:
            raise QuestionEngineRuntimeError(
                "QUESTION_CANCELLED", "The exercise request was cancelled."
            )

    def _select_prototype(
        self,
        *,
        owner_user_id: str,
        course_id: str,
        workspace_id: str,
        objective: TeachingObjective,
    ) -> _Prototype:
        if self.semantic_decisions is None:
            return _PROTOTYPES["worked_application"]
        selected = callsites.select_exercise_prototype(
            self.semantic_decisions,
            node={
                "node_id": objective.node_id,
                "spec_version": objective.spec_version,
                "objective_id": objective.item_id,
                "objective": objective.objective,
            },
            eligible_prototypes=tuple(_PROTOTYPES),
            recent_exposures=self._recent_exposures(workspace_id, objective.node_id),
            learning_evidence={
                "requirement": objective.requirement,
                "acceptance": objective.acceptance,
            },
            scope=self.semantic_decisions.scope(
                owner_user_id=owner_user_id,
                authorization_scope="exercise",
                course_id=course_id,
                workspace_id=workspace_id,
                node_id=objective.node_id,
                spec_version=objective.spec_version,
            ),
        )
        return _PROTOTYPES.get(selected, _PROTOTYPES["worked_application"])

    @staticmethod
    def _blueprint(
        *,
        course_id: str,
        objective: TeachingObjective,
        evidence: QuestionEvidencePack,
        prototype: _Prototype,
        operation_id: str,
    ) -> QuestionBlueprint:
        operation_hash = _hash(
            course_id,
            objective.node_id,
            objective.spec_version,
            objective.item_id,
            operation_id,
        )
        return QuestionBlueprint(
            blueprint_id=f"practice_{operation_hash[:32]}",
            course_id=course_id,
            node_id=objective.node_id,
            spec_version=objective.spec_version,
            spec_content_hash=objective.spec_content_hash,
            objective_id=objective.item_id,
            objective_text=objective.objective,
            source_scope=evidence.source_scope(),
            bloom_target=prototype.bloom_target,
            target_difficulty=prototype.target_difficulty,
            difficulty_features=list(prototype.difficulty_features),
            question_type=prototype.question_type,
            expected_answer_form=prototype.expected_answer_form,
            marks=100,
            scoring_criteria=[objective.acceptance],
            assumptions=[],
            conditions=[],
            unit_conventions=[],
            misconception_targets=[],
            question_family_id=f"practice_family_{operation_hash[:24]}",
            variant_seed=int(operation_hash[:8], 16),
            visibility_policy="OWNER_ONLY",
            answer_policy="HIDDEN_UNTIL_REVEAL",
            prompt_versions={"question_author": QUESTION_AUTHOR_PROMPT_VERSION},
            generation_policy_version=GENERATION_POLICY_VERSION,
        )

    @staticmethod
    def _steps(candidate: Any) -> list[ExerciseAnswerStep]:
        steps: list[ExerciseAnswerStep] = []
        for step in candidate.private_solution.solution_steps:
            body = f"{step.result}\n\n{step.explanation}".strip()
            if step.ordinal == len(candidate.private_solution.solution_steps):
                answer = candidate.private_solution.candidate_answer.strip()
                if answer.casefold() not in body.casefold():
                    body = f"{body}\n\n结论：{answer}"
            steps.append(
                ExerciseAnswerStep(
                    step_id=f"step_{step.ordinal}",
                    ordinal=step.ordinal,
                    title=step.operation,
                    text=body,
                    source_refs=step.source_refs,
                )
            )
        return steps

    @staticmethod
    def _references(evidence: QuestionEvidencePack) -> list[ExerciseReference]:
        return [
            ExerciseReference(
                id=fragment.evidence_id,
                document_id=fragment.document_id,
                document_version_id=fragment.document_version_id,
                filename=fragment.filename,
                source_scope=fragment.source_scope,
                locator_type=fragment.locator_type,
                locator_value=fragment.locator_value,
                section=fragment.section,
            )
            for fragment in evidence.fragments
        ]

    def generate_one(
        self,
        *,
        owner_user_id: str,
        workspace_id: str,
        course_id: str,
        private_course_id: str,
        node_id: str,
        operation_id: str,
        should_cancel: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Generate, independently solve, validate and persist one question."""

        if not operation_id.strip():
            raise QuestionEngineRuntimeError(
                "QUESTION_OPERATION_REQUIRED", "A stable exercise operation id is required."
            )
        try:
            self._check_cancelled(should_cancel)
            workspace = workspace_for(self.database, workspace_id, owner_user_id)
            if (
                str(workspace["course_id"]) != course_id
                or str(workspace["private_course_id"]) != private_course_id
            ):
                raise QuestionEngineRuntimeError(
                    "QUESTION_WORKSPACE_MISMATCH",
                    "The exercise request does not match the learner workspace.",
                )
            with self.database.connect() as connection:
                objective = resolve_objective(connection, node_id=node_id)
            evidence = build_evidence_pack(
                self.database,
                objective=objective,
                access=EvidencePackAccess(
                    owner_user_id=owner_user_id,
                    course_id=course_id,
                    private_course_id=private_course_id,
                ),
            )
            self._check_cancelled(should_cancel)
            prototype = self._select_prototype(
                owner_user_id=owner_user_id,
                course_id=course_id,
                workspace_id=workspace_id,
                objective=objective,
            )
            self._check_cancelled(should_cancel)
            blueprint = self._blueprint(
                course_id=course_id,
                objective=objective,
                evidence=evidence,
                prototype=prototype,
                operation_id=operation_id,
            )
            candidate = author_question(
                self.provider,
                blueprint=blueprint,
                evidence=evidence,
            )
            self._check_cancelled(should_cancel)
            blind = run_blind_solve(
                self.provider,
                candidate=candidate,
                evidence=evidence,
            )
            self._check_cancelled(should_cancel)
            scope = (
                self.semantic_decisions.scope(
                    owner_user_id=owner_user_id,
                    authorization_scope="question_validation",
                    course_id=course_id,
                    workspace_id=workspace_id,
                    node_id=node_id,
                    spec_version=objective.spec_version,
                    question_hash=candidate.question_revision,
                )
                if self.semantic_decisions is not None
                else SemanticDecisionService.scope(
                    owner_user_id=owner_user_id,
                    authorization_scope="question_validation",
                    course_id=course_id,
                    workspace_id=workspace_id,
                    node_id=node_id,
                    spec_version=objective.spec_version,
                    question_hash=candidate.question_revision,
                )
            )
            signals = collect_question_semantic_signals(
                self.semantic_decisions,
                candidate=candidate,
                blueprint=blueprint,
                evidence=evidence,
                blind_receipt=blind,
                scope=scope,
            )
            self._check_cancelled(should_cancel)
            report = validate_question_candidate(
                candidate=candidate,
                blueprint=blueprint,
                evidence=evidence,
                blind_receipt=blind,
                semantic_signals=signals,
            )
            if self.semantic_decisions is None:
                raise QuestionEngineRuntimeError(
                    "QUESTION_REVIEW_UNAVAILABLE",
                    "Question semantic review is unavailable; no exercise was published.",
                )
            self._check_cancelled(should_cancel)
            persisted = persist_question_candidate(
                database=self.database,
                owner_user_id=owner_user_id,
                workspace_id=workspace_id,
                blueprint=blueprint,
                evidence=evidence,
                candidate=candidate,
                blind_receipt=blind,
                validation_report=report,
                semantic_decisions=self.semantic_decisions,
            )
        except QuestionEngineRuntimeError:
            raise
        except (
            ObjectiveResolutionError,
            EvidencePackError,
            AuthorGenerationError,
            BlindSolveError,
            QuestionPersistenceError,
        ) as error:
            raise QuestionEngineRuntimeError(
                getattr(error, "code", "QUESTION_ENGINE_FAILED"),
                "The exercise could not be prepared from the current verified course evidence.",
            ) from error
        except ApiError as error:
            raise QuestionEngineRuntimeError(error.code, error.message) from error

        if persisted.status != "READY" or persisted.verification_method != "AI_REVIEWED":
            raise QuestionEngineRuntimeError(
                "QUESTION_NOT_READY",
                "The exercise did not pass all current validation gates and was not published.",
            )
        usage = [
            _public_run(candidate.provider_run),
            _public_run(blind.provider_run),
            {
                "role": "QUESTION_VALIDATOR",
                "semantic_receipts": [
                    signal.receipt_id
                    for signal in report.semantic_signals
                    if signal.receipt_id is not None
                ],
            },
        ]
        generated = GeneratedExercise(
            question_revision_id=persisted.question_revision_id,
            blueprint_id=blueprint.blueprint_id,
            status="READY",
            verification_status="AI_REVIEWED",
            generation_version=GENERATION_VERSION,
            prototype_id=prototype.prototype_id,
            public=candidate.public_payload(),
            private=PrivateExerciseProjection(
                answer=candidate.private_solution.candidate_answer,
                steps=self._steps(candidate),
            ),
            references=self._references(evidence),
            usage=usage,
        )
        return generated.model_dump(mode="json")
