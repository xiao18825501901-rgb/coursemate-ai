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
from app.jev.models import owner_scope_hash
from app.jev.service import SemanticDecisionService
from app.learning.assessment_question_slots import (
    AssessmentQuestionSlot,
    default_assessment_question_slots,
)
from app.learning.blind_solve import BlindSolveError, run_blind_solve
from app.learning.models import Contract, Identifier, Text
from app.learning.practice_feedback import (
    PracticeInteractionError,
    generate_practice_feedback,
    generate_practice_hint,
)
from app.learning.question_author import (
    QUESTION_AUTHOR_PROMPT_VERSION,
    RULE_VIOLATION_POLICY_VERSION,
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
    required_specialized_semantic_dimension,
    validate_question_candidate,
)
from app.learning.workspaces import workspace_for

GENERATION_VERSION: Final = "exercise.v2+question-engine.v1"
GENERATION_POLICY_VERSION: Final = "question-generation-policy-v1"
ASSESSMENT_GENERATION_POLICY_VERSION: Final = "assessment-question-slot-policy-v1"


class _MeteredProviderProxy:
    """Forward provider identity while routing calls through the V3 usage ledger."""

    def __init__(
        self,
        provider: Any,
        generate: Callable[..., tuple[Any, dict[str, Any]]],
        *,
        workspace_id: str,
        operation_id: str,
    ) -> None:
        self._provider = provider
        self._generate = generate
        self._workspace_id = workspace_id
        self._operation_id = operation_id

    def __getattr__(self, name: str) -> Any:
        return getattr(self._provider, name)

    def generate(self, schema: Any, **kwargs: Any) -> tuple[Any, dict[str, Any]]:
        return self._generate(
            self._workspace_id,
            self._operation_id,
            schema,
            **kwargs,
        )


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
    prototype_id: Literal[
        "worked_application", "concept_short_answer", "rule_violation_analysis"
    ]
    public: PublicExerciseProjection
    private: PrivateExerciseProjection
    references: list[ExerciseReference] = Field(min_length=1, max_length=20)
    usage: list[dict[str, Any]] = Field(min_length=3, max_length=3)


@dataclass(frozen=True)
class _Prototype:
    prototype_id: Literal[
        "worked_application", "concept_short_answer", "rule_violation_analysis"
    ]
    bloom_target: Literal["UNDERSTAND", "APPLY", "ANALYZE"]
    target_difficulty: int
    difficulty_features: tuple[Literal["STEPS", "CONCEPTS"], ...]
    question_type: Literal["SHORT_TEXT", "EXPLANATION"]
    expected_answer_form: Literal["SHORT_ANSWER", "WORKED_STEPS"]
    generation_policy_version: str


_PROTOTYPES: Final[dict[str, _Prototype]] = {
    "worked_application": _Prototype(
        prototype_id="worked_application",
        bloom_target="APPLY",
        target_difficulty=3,
        difficulty_features=("STEPS", "CONCEPTS"),
        question_type="EXPLANATION",
        expected_answer_form="WORKED_STEPS",
        generation_policy_version=GENERATION_POLICY_VERSION,
    ),
    "concept_short_answer": _Prototype(
        prototype_id="concept_short_answer",
        bloom_target="UNDERSTAND",
        target_difficulty=2,
        difficulty_features=("CONCEPTS",),
        question_type="SHORT_TEXT",
        expected_answer_form="SHORT_ANSWER",
        generation_policy_version=GENERATION_POLICY_VERSION,
    ),
    "rule_violation_analysis": _Prototype(
        prototype_id="rule_violation_analysis",
        bloom_target="ANALYZE",
        target_difficulty=4,
        difficulty_features=("CONCEPTS", "STEPS"),
        question_type="EXPLANATION",
        expected_answer_form="WORKED_STEPS",
        generation_policy_version=RULE_VIOLATION_POLICY_VERSION,
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
        metered_generate: Callable[..., tuple[Any, dict[str, Any]]] | None = None,
    ) -> None:
        self.database = database
        self.provider = provider
        self.semantic_decisions = semantic_decisions
        self.metered_generate = metered_generate

    def _provider_for_operation(
        self,
        *,
        workspace_id: str,
        operation_id: str | None,
    ) -> Any:
        if operation_id is None or self.metered_generate is None:
            return self.provider
        return _MeteredProviderProxy(
            self.provider,
            self.metered_generate,
            workspace_id=workspace_id,
            operation_id=operation_id,
        )

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
            if inserted == 1:
                connection.execute(
                    "INSERT INTO practice_operation_metering_guards("
                    "workspace_id,operation_id,guard_version) VALUES(?,?,'metered-practice.v1')",
                    (workspace_id, operation_id),
                )
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
            output, run = generate_practice_hint(
                self._provider_for_operation(
                    workspace_id=workspace_id,
                    operation_id=operation_id,
                ),
                context=context,
            )
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
            output, run = generate_practice_feedback(
                self._provider_for_operation(
                    workspace_id=workspace_id,
                    operation_id=operation_id,
                ),
                context=provider_context,
            )
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
            generation_policy_version=prototype.generation_policy_version,
        )

    @staticmethod
    def _assessment_blueprint(
        *,
        course_id: str,
        objective: TeachingObjective,
        evidence: QuestionEvidencePack,
        slot: AssessmentQuestionSlot,
        preparation_key: str,
    ) -> QuestionBlueprint:
        operation_hash = _hash(
            course_id,
            objective.node_id,
            objective.spec_version,
            objective.item_id,
            preparation_key,
            slot.model_dump(mode="json"),
        )
        return QuestionBlueprint(
            blueprint_id=f"assessment_{operation_hash[:32]}",
            course_id=course_id,
            node_id=objective.node_id,
            spec_version=objective.spec_version,
            spec_content_hash=objective.spec_content_hash,
            objective_id=objective.item_id,
            objective_text=objective.objective,
            source_scope=evidence.source_scope(),
            bloom_target=slot.bloom_target,
            target_difficulty=slot.target_difficulty,
            difficulty_features=slot.difficulty_features,
            question_type=slot.question_type,
            expected_answer_form=slot.expected_answer_form,
            marks=slot.marks,
            scoring_criteria=[objective.acceptance, slot.scoring_focus],
            assumptions=[],
            conditions=[],
            unit_conventions=[],
            misconception_targets=[slot.misconception_target],
            question_family_id=f"assessment_family_{operation_hash[:24]}",
            variant_seed=int(operation_hash[:8], 16),
            visibility_policy="OWNER_ONLY",
            answer_policy="HIDDEN_UNTIL_REVEAL",
            prompt_versions={"question_author": QUESTION_AUTHOR_PROMPT_VERSION},
            generation_policy_version=ASSESSMENT_GENERATION_POLICY_VERSION,
        )

    def _execute_pipeline(
        self,
        *,
        owner_user_id: str,
        workspace_id: str,
        course_id: str,
        node_id: str,
        objective: TeachingObjective,
        evidence: QuestionEvidencePack,
        blueprint: QuestionBlueprint,
        should_cancel: Callable[[], bool] | None,
        model_operation_id: str | None = None,
    ) -> tuple[Any, Any, Any, Any]:
        """Run author, blind solve, validation and READY persistence for one blueprint."""

        self._check_cancelled(should_cancel)
        provider = self._provider_for_operation(
            workspace_id=workspace_id,
            operation_id=model_operation_id,
        )
        candidate = author_question(
            provider,
            blueprint=blueprint,
            evidence=evidence,
        )
        self._check_cancelled(should_cancel)
        blind = run_blind_solve(
            provider,
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
        if persisted.status != "READY" or persisted.verification_method != "AI_REVIEWED":
            raise QuestionEngineRuntimeError(
                "QUESTION_NOT_READY",
                "The question did not pass all current validation gates and was not published.",
            )
        return persisted, candidate, blind, report

    def _existing_assessment_slot(
        self,
        *,
        owner_user_id: str,
        workspace_id: str,
        blueprint: QuestionBlueprint,
        evidence: QuestionEvidencePack,
    ) -> tuple[str, list[dict[str, Any]]] | None:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT provenance.question_revision_id,provenance.question_revision_hash,"
                "provenance.blueprint_hash,"
                "provenance.evidence_pack_hash,provenance.publication_status,"
                "provenance.author_run_json,provenance.blind_run_json,"
                "provenance.validation_report_json,"
                "question.validation_status,question.verification_method "
                "FROM question_engine_provenance AS provenance "
                "JOIN assessment_question_revisions AS question "
                "ON question.id=provenance.question_revision_id "
                "WHERE provenance.workspace_id=? AND provenance.blueprint_id=?",
                (workspace_id, blueprint.blueprint_id),
            ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise QuestionEngineRuntimeError(
                "ASSESSMENT_SLOT_CONFLICT",
                "The assessment slot is bound to more than one question revision.",
            )
        row = rows[0]
        current = (
            str(row["blueprint_hash"]) == blueprint.identity()
            and str(row["evidence_pack_hash"]) == evidence.identity()
            and str(row["publication_status"]) == "READY"
            and str(row["validation_status"]) == "VALIDATED"
            and str(row["verification_method"]) == "AI_REVIEWED"
        )
        if not current:
            raise QuestionEngineRuntimeError(
                "ASSESSMENT_SLOT_STALE",
                "The saved assessment slot no longer matches its current verified inputs.",
            )
        try:
            author_run = json.loads(str(row["author_run_json"]))
            blind_run = json.loads(str(row["blind_run_json"]))
            report = json.loads(str(row["validation_report_json"]))
            signals = report["semantic_signals"]
            expected_definitions = {
                "AMBIGUITY": "question.ambiguity.v1",
                "AUTHOR_BLIND_AGREEMENT": "question.answer_agreement.v1",
            }
            specialized_dimension = required_specialized_semantic_dimension(blueprint)
            if specialized_dimension == "MCQ_DISTRACTOR_QUALITY":
                expected_definitions[specialized_dimension] = (
                    "question.mcq_distractor_quality.v1"
                )
            elif specialized_dimension == "RULE_VIOLATION_QUALITY":
                expected_definitions[specialized_dimension] = (
                    "question.rule_violation_quality.v1"
                )
            if not isinstance(signals, list) or len(signals) != len(expected_definitions):
                raise ValueError("semantic signals are incomplete")
            dimensions = [signal["dimension"] for signal in signals]
            receipts = [signal["receipt_id"] for signal in signals]
        except (KeyError, TypeError, ValueError) as error:
            raise QuestionEngineRuntimeError(
                "ASSESSMENT_SLOT_RECEIPT_INVALID",
                "The saved assessment slot receipts could not be verified.",
            ) from error
        if (
            set(dimensions) != set(expected_definitions)
            or not all(isinstance(receipt, str) and receipt for receipt in receipts)
            or len(set(receipts)) != len(expected_definitions)
        ):
            raise QuestionEngineRuntimeError(
                "ASSESSMENT_SLOT_RECEIPT_INVALID",
                "The saved assessment slot receipts could not be verified.",
            )
        with self.database.connect() as connection:
            receipt_rows = connection.execute(
                "SELECT * FROM jev_decision_receipts WHERE id IN ("
                + ",".join("?" for _ in receipts)
                + ")",
                receipts,
            ).fetchall()
        receipts_by_id = {str(receipt["id"]): receipt for receipt in receipt_rows}
        expected_scope = owner_scope_hash(owner_user_id, "question_validation")
        for signal in signals:
            receipt = receipts_by_id.get(str(signal["receipt_id"]))
            try:
                output = json.loads(str(receipt["output_json"])) if receipt is not None else None
                current_receipt = (
                    receipt is not None
                    and signal["used_jev"] is True
                    and signal["path"] == "jev"
                    and str(receipt["definition_key"])
                    == expected_definitions[signal["dimension"]]
                    and str(receipt["primitive"]) == "Choice"
                    and str(receipt["mode"]) == "on"
                    and str(receipt["caller_role"]) == "question_validator"
                    and str(receipt["owner_scope_hash"]) == expected_scope
                    and str(receipt["course_id"]) == blueprint.course_id
                    and str(receipt["workspace_id"]) == workspace_id
                    and str(receipt["node_id"]) == blueprint.node_id
                    and str(receipt["spec_version"]) == str(blueprint.spec_version)
                    and str(receipt["question_hash"]) == str(row["question_revision_hash"])
                    and str(receipt["outcome"]) == "ok"
                    and isinstance(output, dict)
                    and output.get("choice") == signal["verdict"]
                )
            except (KeyError, TypeError, ValueError):
                current_receipt = False
            if not current_receipt:
                raise QuestionEngineRuntimeError(
                    "ASSESSMENT_SLOT_RECEIPT_INVALID",
                    "The saved assessment slot receipts could not be verified.",
                )
        usage = [
            _public_run(author_run),
            _public_run(blind_run),
            {"role": "QUESTION_VALIDATOR", "semantic_receipts": receipts},
        ]
        return str(row["question_revision_id"]), usage

    def _record_assessment_slot(
        self,
        *,
        preparation_key: str,
        workspace_id: str,
        slot: AssessmentQuestionSlot,
        objective: TeachingObjective,
        blueprint: QuestionBlueprint,
        question_revision_id: str,
    ) -> None:
        values = (
            preparation_key,
            workspace_id,
            slot.ordinal,
            slot.slot_key,
            slot.marks,
            objective.item_id,
            blueprint.blueprint_id,
            question_revision_id,
            blueprint.question_family_id,
        )
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT OR IGNORE INTO assessment_preparation_questions("
                "preparation_job_id,workspace_id,ordinal,slot_key,marks,objective_id,"
                "blueprint_id,question_revision_id,family_id) VALUES(?,?,?,?,?,?,?,?,?)",
                values,
            )
            row = connection.execute(
                "SELECT preparation_job_id,workspace_id,ordinal,slot_key,marks,objective_id,"
                "blueprint_id,question_revision_id,family_id "
                "FROM assessment_preparation_questions "
                "WHERE preparation_job_id=? AND ordinal=?",
                (preparation_key, slot.ordinal),
            ).fetchone()
        if row is None or tuple(row) != values:
            raise QuestionEngineRuntimeError(
                "ASSESSMENT_SLOT_CONFLICT",
                "The assessment preparation slot is already bound to different input.",
            )

    def generate_assessment_set(
        self,
        *,
        owner_user_id: str,
        workspace_id: str,
        course_id: str,
        private_course_id: str,
        node_id: str,
        preparation_key: str,
        operation_id: str | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> list[dict[str, Any]]:
        """Prepare five complementary READY revisions for the existing AssessmentService."""

        if not 8 <= len(preparation_key.strip()) <= 100:
            raise QuestionEngineRuntimeError(
                "ASSESSMENT_PREPARATION_KEY_REQUIRED",
                "A stable assessment preparation key between 8 and 100 characters is required.",
            )
        if self.metered_generate is not None and operation_id is None:
            raise QuestionEngineRuntimeError(
                "QUESTION_METERING_REQUIRED",
                "Integrated assessment generation requires a claimed metered operation.",
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
                    "The assessment request does not match the learner workspace.",
                )
            with self.database.connect() as connection:
                version = connection.execute(
                    "SELECT MAX(version) FROM teaching_specs WHERE node_id=?", (node_id,)
                ).fetchone()[0]
                item_rows = connection.execute(
                    "SELECT item_id FROM teaching_items WHERE node_id=? AND spec_version=? "
                    "AND requirement='REQUIRED' ORDER BY ordinal,item_id",
                    (node_id, version),
                ).fetchall()
                objectives = [
                    resolve_objective(
                        connection,
                        node_id=node_id,
                        spec_version=int(version),
                        item_id=str(row["item_id"]),
                    )
                    for row in item_rows
                ]
            if not objectives:
                raise QuestionEngineRuntimeError(
                    "NO_REQUIRED_ITEM",
                    "The node has no REQUIRED teaching objective for an assessment.",
                )

            prepared: list[dict[str, Any]] = []
            for slot in default_assessment_question_slots():
                self._check_cancelled(should_cancel)
                objective = objectives[(slot.ordinal - 1) % len(objectives)]
                evidence = build_evidence_pack(
                    self.database,
                    objective=objective,
                    access=EvidencePackAccess(
                        owner_user_id=owner_user_id,
                        course_id=course_id,
                        private_course_id=private_course_id,
                    ),
                )
                blueprint = self._assessment_blueprint(
                    course_id=course_id,
                    objective=objective,
                    evidence=evidence,
                    slot=slot,
                    preparation_key=preparation_key,
                )
                existing = self._existing_assessment_slot(
                    owner_user_id=owner_user_id,
                    workspace_id=workspace_id,
                    blueprint=blueprint,
                    evidence=evidence,
                )
                if existing is None:
                    persisted, candidate, blind, report = self._execute_pipeline(
                        owner_user_id=owner_user_id,
                        workspace_id=workspace_id,
                        course_id=course_id,
                        node_id=node_id,
                        objective=objective,
                        evidence=evidence,
                        blueprint=blueprint,
                        should_cancel=should_cancel,
                        model_operation_id=operation_id,
                    )
                    question_revision_id = persisted.question_revision_id
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
                else:
                    question_revision_id, usage = existing
                self._record_assessment_slot(
                    preparation_key=preparation_key,
                    workspace_id=workspace_id,
                    slot=slot,
                    objective=objective,
                    blueprint=blueprint,
                    question_revision_id=question_revision_id,
                )
                prepared.append(
                    {
                        "slot_key": slot.slot_key,
                        "ordinal": slot.ordinal,
                        "marks": slot.marks,
                        "blueprint_id": blueprint.blueprint_id,
                        "family_id": blueprint.question_family_id,
                        "question_revision_id": question_revision_id,
                        "verification_status": "AI_REVIEWED",
                        "usage": usage,
                    }
                )
            return prepared
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
                "The assessment set could not be prepared from verified course evidence.",
            ) from error
        except (ApiError, TypeError) as error:
            code = error.code if isinstance(error, ApiError) else "NO_TEACHING_SPEC"
            message = (
                error.message
                if isinstance(error, ApiError)
                else "No Teaching Spec was found."
            )
            raise QuestionEngineRuntimeError(code, message) from error

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
            persisted, candidate, blind, report = self._execute_pipeline(
                owner_user_id=owner_user_id,
                workspace_id=workspace_id,
                course_id=course_id,
                node_id=node_id,
                objective=objective,
                evidence=evidence,
                blueprint=blueprint,
                should_cancel=should_cancel,
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
