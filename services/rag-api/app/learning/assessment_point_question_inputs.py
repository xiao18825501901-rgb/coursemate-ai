"""Private point author input with every original target, not legacy v1 identity.

Schema validity is not qualification or source authorization. The runtime must
resolve original frozen server authority before constructing this input, and a
future sender must revalidate that authority before any paid call. No Teaching
Item is synthesized and no original target is chosen as a composite stand-in.
"""

from typing import Any, Literal

from pydantic import Field, model_validator

from app.errors import ApiError
from app.learning.assessment_point_catalog import canonical_hash
from app.learning.assessment_point_configuration import PointQuestionSlot
from app.learning.assessment_point_dispatch import ResolvedPointDispatch
from app.learning.models import Contract, Identifier, Text
from app.learning.question_author import point_marks_basis_points
from app.learning.question_blueprint import Hex64
from app.learning.question_evidence import QuestionEvidencePack


def _blueprint_id(payload: dict[str, Any]) -> str:
    return "point-question-" + canonical_hash(payload)[:32]


class OriginalPointTarget(Contract):
    item_id: Identifier
    requirement: Literal["REQUIRED"]
    objective: Text
    acceptance: Text
    evidence: QuestionEvidencePack

    @model_validator(mode="after")
    def original_target_matches(self) -> "OriginalPointTarget":
        if (
            self.item_id != self.evidence.objective_id
            or self.objective != self.evidence.objective_text
            or self.acceptance != self.evidence.acceptance
        ):
            raise ValueError("Every target must match its complete original evidence pack")
        return self


class AssessmentPointQuestionInput(Contract):
    schema_version: Literal["assessment-point-question-input.v1"] = (
        "assessment-point-question-input.v1"
    )
    policy_version: Literal["cj.assessment.points.v1"] = "cj.assessment.points.v1"
    blueprint_id: Identifier
    owner_user_id: Identifier
    workspace_id: Identifier
    course_id: Identifier
    private_course_id: Identifier
    node_id: Identifier
    configuration_id: Identifier
    plan_hash: Hex64
    source_snapshot: Hex64
    spec_version: int = Field(ge=1, strict=True)
    spec_content_hash: Hex64
    content_language: Literal["zh-CN", "en"]
    point_slot: PointQuestionSlot
    targets: tuple[OriginalPointTarget, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def exact_original_inputs(self) -> "AssessmentPointQuestionInput":
        slot = self.point_slot
        ids = tuple(target.item_id for target in self.targets)
        if ids != slot.original_target_item_ids or len(set(ids)) != len(ids):
            raise ValueError("Point input must retain every exact original target in order")
        if (
            slot.primary_point_id != slot.verified_point.point_id
            or slot.question_type not in slot.verified_point.allowed_forms
            or type(slot.independently_scored_parts) is not int
            or slot.independently_scored_parts != 1
            or point_marks_basis_points(slot.marks) != slot.marks_basis_points
        ):
            raise ValueError("Point input does not match the original point/item/score contract")
        # Observability belongs to the reviewed, source-bound catalog. The
        # legacy blueprint's lexical heuristic is neither that authority nor
        # a complete vocabulary for observable goals in either language.
        for target in self.targets:
            evidence = target.evidence
            if (
                evidence.course_id != self.course_id or evidence.node_id != self.node_id
                or evidence.spec_version != self.spec_version
                or evidence.spec_content_hash != self.spec_content_hash
                or any(fragment.truncated for fragment in evidence.fragments)
            ):
                raise ValueError("Every complete source pack must match the same original Spec")
        payload = self.model_dump(
            mode="json", exclude={"schema_version", "policy_version", "blueprint_id"}
        )
        if self.blueprint_id != _blueprint_id(payload):
            raise ValueError("Changed point inputs cannot retain their original blueprint identity")
        return self

    def identity(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


def build_point_question_input(
    resolved: ResolvedPointDispatch,
    *,
    owner_user_id: str,
    workspace_id: str,
    course_id: str,
    private_course_id: str,
    node_id: str,
) -> AssessmentPointQuestionInput:
    objectives, packs = resolved.objectives, resolved.evidence_packs
    versions = {(item.node_id, item.spec_version, item.spec_content_hash) for item in objectives}
    if len(versions) != 1 or len(objectives) != len(packs):
        raise ApiError(409, "ASSESSMENT_POINT_INPUT_INVALID", "Original point inputs disagree.")
    original_node, spec_version, spec_hash = versions.pop()
    if original_node != node_id:
        raise ApiError(409, "ASSESSMENT_POINT_SCOPE_CONFLICT", "Original point scope disagrees.")
    targets = []
    for objective, pack in zip(objectives, packs, strict=True):
        if objective.evidence_ids != tuple(pack.evidence_ids):
            raise ApiError(
                409, "ASSESSMENT_POINT_INPUT_INVALID", "Original point sources disagree."
            )
        targets.append({
            "item_id": objective.item_id, "requirement": objective.requirement,
            "objective": objective.objective, "acceptance": objective.acceptance,
            "evidence": pack.model_dump(mode="json"),
        })
    # model_dump -> validation creates detached nested objects, rather than
    # lending out mutable slots/packs owned by the resolved plan.
    payload: dict[str, Any] = {
        "owner_user_id": owner_user_id, "workspace_id": workspace_id,
        "course_id": course_id, "private_course_id": private_course_id, "node_id": node_id,
        "configuration_id": resolved.configuration_id, "plan_hash": resolved.plan_hash,
        "source_snapshot": resolved.source_snapshot, "spec_version": spec_version,
        "spec_content_hash": spec_hash, "content_language": resolved.content_language,
        "point_slot": resolved.slot.model_dump(mode="json"), "targets": targets,
    }
    return AssessmentPointQuestionInput.model_validate({
        **payload, "blueprint_id": _blueprint_id(payload),
    })
