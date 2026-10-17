"""Server-owned dynamic-K planning from an already verified point catalog.

This module does not compile or review semantic points. It consumes a verified,
source-bound catalog reader and produces the immutable private plan accepted by
schema 078. Legacy assessment configuration remains a separate policy.
"""

import hashlib
import json
from collections import defaultdict
from typing import Any, Literal, Protocol

from pydantic import Field, ValidationError

from app.errors import ApiError
from app.learning.assessment_point_catalog_models import VerifiedCatalog, VerifiedPoint
from app.learning.assessment_question_slots import (
    POINT_ASSESSMENT_POLICY_VERSION,
    assessment_setup_contract,
    point_item_marks_basis_points,
    question_slot_values,
)
from app.learning.models import Contract, Identifier, PointSlotSelection, Text
from app.learning.question_blueprint import (
    AnswerForm,
    BloomTarget,
    DifficultyFeature,
    Hex64,
    QuestionType,
)

SecondPurpose = Literal[
    "APPLICATION", "CONDITION_CHANGE", "DISCRIMINATION", "ERROR_DIAGNOSIS"
]


def canonical_hash(value: Any) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


class PointSourceIdentity(Protocol):
    owner_user_id: str
    course_id: str
    node_id: str
    spec_version: int

    def identity(self) -> str: ...


class VerifiedCatalogReader(Protocol):
    def read_with_targets_for(
        self, source: PointSourceIdentity, language: str
    ) -> tuple[VerifiedCatalog, dict[str, tuple[str, ...]]] | None: ...


class PointQuestionSlot(Contract):
    schema_version: Literal["assessment-question-slot.points.v1"] = (
        "assessment-question-slot.points.v1"
    )
    slot_key: Identifier
    ordinal: int = Field(ge=1)
    marks: float = Field(ge=0.01, le=100)
    marks_basis_points: int = Field(ge=1, le=10_000, strict=True)
    bloom_target: BloomTarget
    target_difficulty: int = Field(ge=1, le=5)
    difficulty_features: list[DifficultyFeature] = Field(min_length=1)
    empirical_difficulty: None = None
    question_type: QuestionType
    task_form: Literal[
        "concept", "definition", "calculation", "analysis", "evaluation", "code"
    ]
    expected_answer_form: AnswerForm
    scoring_focus: Text
    misconception_target: Text
    primary_point_id: Identifier
    variation_purpose: SecondPurpose | None = None
    independently_scored_parts: Literal[1] = 1
    original_target_item_ids: tuple[Identifier, ...] = Field(min_length=1)
    verified_point: VerifiedPoint


class FrozenPointPlan(Contract):
    policy_version: Literal["cj.assessment.points.v1"] = POINT_ASSESSMENT_POLICY_VERSION
    intent_id: Identifier
    content_language: Literal["zh-CN", "en"]
    source_snapshot: Hex64
    catalog_hash: Hex64
    catalog_id: str
    scope: dict[str, str]
    items: tuple[PointQuestionSlot, ...] = Field(min_length=1)
    content_hash: Hex64


def _refuse(code: str = "ASSESSMENT_POINTS_NOT_READY") -> ApiError:
    return ApiError(
        409,
        code,
        "Verified assessable points and original source evidence are required.",
    )


class AssessmentPointPolicyService:
    def __init__(self, catalogs: VerifiedCatalogReader) -> None:
        self.catalogs = catalogs

    def _catalog(
        self,
        source: PointSourceIdentity,
        language: str,
    ) -> tuple[VerifiedCatalog, list[VerifiedPoint], dict[str, tuple[str, ...]]]:
        if language not in ("zh-CN", "en"):
            raise _refuse("ASSESSMENT_CONTENT_LANGUAGE_INVALID")
        result = self.catalogs.read_with_targets_for(source, language)
        if result is None:
            raise _refuse()
        catalog, targets = result
        expected = {
            "owner_id": source.owner_user_id,
            "course_id": source.course_id,
            "node_id": source.node_id,
            "spec_version": str(source.spec_version),
            "source_snapshot": source.identity(),
        }
        if catalog.scope.model_dump() != expected or not catalog.points:
            raise _refuse("ASSESSMENT_POINT_SCOPE_CONFLICT")
        points = sorted(catalog.points, key=lambda point: (point.sequence, point.point_id))
        if len({point.point_id for point in points}) != len(points):
            raise _refuse("ASSESSMENT_POINT_CATALOG_INVALID")
        if set(targets) != {point.point_id for point in points} or any(
            not targets[point.point_id] for point in points
        ):
            raise _refuse("ASSESSMENT_POINT_CATALOG_INVALID")
        return catalog, points, targets

    @staticmethod
    def _defaults(points: list[VerifiedPoint]) -> list[PointSlotSelection]:
        forms = {
            "MCQ_SINGLE": "concept",
            "NUMERIC": "calculation",
            "SHORT_TEXT": "definition",
            "EXPLANATION": "analysis",
            "CODE": "code",
        }
        return [
            PointSlotSelection.model_validate(
                {
                    "slot_id": "point-item-"
                    + canonical_hash({"point": point.point_id, "item": 1})[:24],
                    "primary_point_id": point.point_id,
                    "question_type": point.allowed_forms[0],
                    "task_form": forms[point.allowed_forms[0]],
                }
            )
            for point in points
        ]

    def setup(self, source: PointSourceIdentity, language: str) -> dict[str, Any]:
        try:
            catalog, points, _ = self._catalog(source, language)
        except ApiError as error:
            if error.code != "ASSESSMENT_POINTS_NOT_READY":
                raise
            catalog, points = None, []
        contract = assessment_setup_contract()
        contract.update(
            {
                "schema_version": "assessment-setup.points.v1",
                "policy_version": POINT_ASSESSMENT_POLICY_VERSION,
                "status": "READY" if points else "ASSESSMENT_POINTS_NOT_READY",
                "minimum_questions": len(points),
                "maximum_questions": len(points) * 2,
                "default_slots": [
                    item.model_dump(mode="json") for item in self._defaults(points)
                ],
                "points": [
                    {"point_id": point.point_id, "allowed_forms": point.allowed_forms}
                    for point in points
                ],
                "catalog_id": catalog.catalog_id if catalog else None,
                "catalog_hash": canonical_hash(catalog.model_dump(mode="json"))
                if catalog
                else None,
                "source_snapshot": source.identity(),
                "content_language": language,
            }
        )
        return contract

    def freeze_plan(
        self,
        source: PointSourceIdentity,
        language: str,
        intent_id: str,
        selections: list[dict[str, Any] | PointSlotSelection] | None,
    ) -> FrozenPointPlan:
        catalog, points, targets = self._catalog(source, language)
        try:
            selected = (
                self._defaults(points)
                if selections is None
                else [PointSlotSelection.model_validate(item) for item in selections]
            )
        except (ValidationError, TypeError, ValueError):
            raise _refuse("ASSESSMENT_POINT_SELECTION_INVALID") from None
        by_point = {point.point_id: point for point in points}
        groups: dict[str, list[PointSlotSelection]] = defaultdict(list)
        if not selected or len({item.slot_id for item in selected}) != len(selected):
            raise _refuse("ASSESSMENT_POINT_SELECTION_INVALID")
        for item in selected:
            if item.primary_point_id not in by_point:
                raise _refuse("ASSESSMENT_UNKNOWN_POINT")
            if item.question_type not in by_point[item.primary_point_id].allowed_forms:
                raise _refuse("ASSESSMENT_POINT_FORM_NOT_ALLOWED")
            groups[item.primary_point_id].append(item)
        if set(groups) != set(by_point):
            raise _refuse("ASSESSMENT_POINT_COVERAGE_INCOMPLETE")
        if any(not 1 <= len(group) <= 2 for group in groups.values()):
            raise _refuse("ASSESSMENT_POINT_ITEM_LIMIT")
        if any(
            group[0].variation_purpose is not None
            or (len(group) == 2 and group[1].variation_purpose is None)
            for group in groups.values()
        ):
            raise _refuse("ASSESSMENT_SECOND_ITEM_PURPOSE_REQUIRED")
        try:
            marks = point_item_marks_basis_points(
                [len(groups[point.point_id]) for point in points]
            )
            items: list[PointQuestionSlot] = []
            for point, shares in zip(points, marks, strict=True):
                for selected_item, basis_points in zip(
                    groups[point.point_id], shares, strict=True
                ):
                    values = question_slot_values(
                        selected_item, len(items) + 1, basis_points
                    )
                    items.append(
                        PointQuestionSlot.model_validate(
                            {
                                **values,
                                "task_form": selected_item.task_form,
                                "primary_point_id": point.point_id,
                                "variation_purpose": selected_item.variation_purpose,
                                "independently_scored_parts": 1,
                                "original_target_item_ids": targets[point.point_id],
                                "verified_point": point,
                            }
                        )
                    )
            payload = {
                "policy_version": POINT_ASSESSMENT_POLICY_VERSION,
                "intent_id": intent_id,
                "content_language": language,
                "source_snapshot": source.identity(),
                "catalog_hash": canonical_hash(catalog.model_dump(mode="json")),
                "catalog_id": catalog.catalog_id,
                "scope": catalog.scope.model_dump(),
                "items": [item.model_dump(mode="json") for item in items],
            }
            return FrozenPointPlan.model_validate(
                {**payload, "content_hash": canonical_hash(payload)}
            )
        except (KeyError, ValidationError, TypeError, ValueError):
            raise _refuse("ASSESSMENT_POINT_PLAN_INVALID") from None
