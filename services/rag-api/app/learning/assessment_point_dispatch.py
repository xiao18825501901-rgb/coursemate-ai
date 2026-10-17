"""Read exact server point authority before any question-generation stage.

No model, synthesized objective, first-target selection or qualification is
created here. The separately frozen catalog/plan and original source ACL remain
authoritative; dispatch carries every original target, including dedup aliases.
"""

from dataclasses import dataclass
from typing import Literal

from app.db import Database
from app.errors import ApiError
from app.learning.assessment_point_configuration import PointQuestionSlot
from app.learning.assessment_point_sources import freeze_point_sources
from app.learning.assessment_point_store import AssessmentPointConfigurationStore
from app.learning.assessment_question_slots import POINT_ASSESSMENT_POLICY_VERSION
from app.learning.assessments import AssessmentService
from app.learning.question_blueprint import TeachingObjective, resolve_objective
from app.learning.question_evidence import QuestionEvidencePack
from app.learning.workspaces import workspace_for


@dataclass(frozen=True)
class ResolvedPointDispatch:
    slot: PointQuestionSlot
    objectives: tuple[TeachingObjective, ...]
    evidence_packs: tuple[QuestionEvidencePack, ...]
    content_language: Literal["zh-CN", "en"]
    source_snapshot: str
    configuration_id: str
    plan_hash: str


def _refuse(code: str = "ASSESSMENT_POINT_SCOPE_CONFLICT") -> ApiError:
    return ApiError(409, code, "The original point-generation authority is unavailable.")


def resolve_point_dispatch(
    database: Database,
    store: AssessmentPointConfigurationStore | None,
    *,
    owner_user_id: str,
    workspace_id: str,
    course_id: str,
    private_course_id: str,
    node_id: str,
    configuration_id: str,
    slots: tuple[PointQuestionSlot, ...] | None,
    content_language: str | None,
) -> tuple[ResolvedPointDispatch, ...]:
    workspace = workspace_for(database, workspace_id, owner_user_id)
    if (
        str(workspace["course_id"]) != course_id
        or str(workspace["private_course_id"]) != private_course_id
    ):
        raise _refuse()
    # Metadata scope precedes the private plan/catalog read. A valid caller's
    # other workspace cannot use this configuration merely by naming its ID.
    with database.connect() as connection:
        configuration = connection.execute(
            "SELECT * FROM assessment_configurations WHERE id=? AND workspace_id=? "
            "AND owner_user_id=? AND course_id=? AND node_id=? AND status='FROZEN' "
            "AND policy_version=?",
            (configuration_id, workspace_id, owner_user_id, course_id, node_id,
             POINT_ASSESSMENT_POLICY_VERSION),
        ).fetchone()
        if configuration is None:
            raise _refuse()
        AssessmentService._atomic_node(
            connection, workspace, node_id,
            spec_version=int(configuration["spec_version"]),
        )
        if store is None:
            raise _refuse("ASSESSMENT_POINT_METHOD_NOT_QUALIFIED")
        if store.db is not database:
            raise _refuse()
        if content_language is not None and content_language != str(configuration["language"]):
            raise _refuse("ASSESSMENT_CONTENT_LANGUAGE_INVALID")
        _, plan = store.read(connection, configuration_id)
        requested = plan.items if slots is None else slots
        original = {item.slot_key: item for item in plan.items}
        if (
            any(not isinstance(item, PointQuestionSlot) for item in requested)
            or len({item.slot_key for item in requested}) != len(requested)
            or [item.ordinal for item in requested] != sorted(item.ordinal for item in requested)
            or any(
                item.slot_key not in original
                or item.model_dump(mode="json") != original[item.slot_key].model_dump(mode="json")
                for item in requested
            )
        ):
            raise _refuse("ASSESSMENT_POINT_SLOT_MISMATCH")
        # The original completed catalog has already been revalidated by read.
        # Resolve source/targets at that SAME Spec, not latest/MAX/round-robin.
        source = freeze_point_sources(
            database, workspace_id=workspace_id, owner=owner_user_id,
            node_id=node_id, spec_version=int(configuration["spec_version"]),
        )
        if source.identity() != plan.source_snapshot:
            raise _refuse("ASSESSMENT_POINT_SOURCE_CHANGED")
        packs = {target.objective_id: target for target in source.targets}
        result: list[ResolvedPointDispatch] = []
        for requested_slot in requested:
            # Return server objects, never the caller's VERIFIED-labelled copy.
            slot = original[requested_slot.slot_key]
            ids = slot.original_target_item_ids
            if len(set(ids)) != len(ids) or any(target not in packs for target in ids):
                raise _refuse("ASSESSMENT_POINT_PLAN_INVALID")
            objectives = tuple(
                resolve_objective(
                    connection, node_id=node_id, spec_version=source.spec_version,
                    item_id=target,
                )
                for target in ids
            )
            result.append(ResolvedPointDispatch(
                slot=slot, objectives=objectives,
                evidence_packs=tuple(packs[target] for target in ids),
                content_language=plan.content_language, source_snapshot=plan.source_snapshot,
                configuration_id=configuration_id, plan_hash=plan.content_hash,
            ))
        return tuple(result)
