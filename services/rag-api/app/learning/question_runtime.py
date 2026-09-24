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

from pydantic import Field

from app.db import Database
from app.errors import ApiError
from app.jev import callsites
from app.jev.service import SemanticDecisionService
from app.learning.blind_solve import BlindSolveError, run_blind_solve
from app.learning.models import Contract, Identifier, Text
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
