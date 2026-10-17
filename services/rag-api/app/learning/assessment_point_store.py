"""Persist original point plans through the existing configuration lifecycle.

Only original completed catalog receipts grant point authority. All methods
are read/planning/SQL: no implicit model calls, count heuristics or legacy edits.
"""

import hashlib
import json
import sqlite3
from typing import Any, cast

from pydantic import ValidationError

from app.db import Database
from app.errors import ApiError
from app.learning.assessment_point_configuration import (
    AssessmentPointPolicyService,
    FrozenPointPlan,
    PointQuestionSlot,
    canonical_hash,
)
from app.learning.assessment_point_sources import PointSourceSnapshot, freeze_point_sources
from app.learning.assessment_question_slots import (
    POINT_ASSESSMENT_POLICY_VERSION,
    assessment_setup_contract,
)
from app.learning.models import PointSlotSelection


def _refuse(code: str = "ASSESSMENT_POINT_PLAN_INVALID") -> ApiError:
    return ApiError(409, code, "The original assessable-point configuration is unavailable.")


def same_point_plan_content(original: FrozenPointPlan, current: FrozenPointPlan) -> bool:
    """Allow a current proof version to validate unchanged frozen business data.

    Both plans are fully rebuilt/validated before comparison. Only catalog
    identity and its point validation receipt references can differ. Sources,
    target IDs, conditions, item forms, counts, score allocation and intent must
    remain identical. The original plan and all historical scores stay intact.
    """

    def material(plan: FrozenPointPlan) -> dict[str, Any]:
        payload = plan.model_dump(
            mode="json", exclude={"content_hash", "catalog_hash", "catalog_id"}
        )
        for item in payload["items"]:
            item["verified_point"].pop("validation_receipt_id")
        return payload

    return material(original) == material(current)


class AssessmentPointConfigurationStore:
    def __init__(self, database: Database, policy: AssessmentPointPolicyService) -> None:
        self.db, self.policy = database, policy

    def _source(self, workspace: sqlite3.Row, node: sqlite3.Row) -> PointSourceSnapshot:
        return freeze_point_sources(
            self.db,
            workspace_id=str(workspace["id"]),
            owner=str(workspace["owner_user_id"]),
            node_id=str(node["id"]),
            spec_version=int(node["spec_version"]),
        )

    def setup(
        self, workspace: sqlite3.Row, node: sqlite3.Row, language: str | None
    ) -> dict[str, Any]:
        if language not in ("zh-CN", "en"):
            raise _refuse("ASSESSMENT_CONTENT_LANGUAGE_INVALID")
        try:
            result = self.policy.setup(self._source(workspace, node), language)
        except ApiError as error:
            if error.code != "ASSESSMENT_POINTS_NOT_READY":
                raise
            result = {
                **assessment_setup_contract(),
                "schema_version": "assessment-setup.points.v1",
                "policy_version": POINT_ASSESSMENT_POLICY_VERSION,
                "status": "ASSESSMENT_POINTS_NOT_READY",
                "minimum_questions": 0,
                "maximum_questions": 0,
                "default_slots": [],
                "points": [],
                "catalog_id": None,
                "catalog_hash": None,
                "source_snapshot": None,
                "content_language": language,
            }
        return result

    def read(
        self, connection: sqlite3.Connection, configuration_id: str
    ) -> tuple[sqlite3.Row, FrozenPointPlan]:
        row = connection.execute(
            "SELECT * FROM assessment_configurations WHERE id=? AND status='FROZEN' "
            "AND policy_version=?",
            (configuration_id, POINT_ASSESSMENT_POLICY_VERSION),
        ).fetchone()
        private = connection.execute(
            "SELECT * FROM assessment_point_configuration_plans WHERE configuration_id=?",
            (configuration_id,),
        ).fetchone()
        if row is None or private is None:
            raise _refuse()
        try:
            plan = FrozenPointPlan.model_validate_json(private["plan_json"])
            payload = plan.model_dump(mode="json")
            expected_hash = payload.pop("content_hash")
            if (
                canonical_hash(payload) != expected_hash
                or plan.content_hash != str(private["content_hash"])
                or plan.content_hash != str(row["content_hash"])
                or plan.catalog_hash != str(private["catalog_hash"])
                or plan.source_snapshot != str(private["source_snapshot"])
                or plan.content_language != str(row["language"])
                or plan.scope
                != {
                    "owner_id": str(row["owner_user_id"]),
                    "course_id": str(row["course_id"]),
                    "node_id": str(row["node_id"]),
                    "spec_version": str(row["spec_version"]),
                    "source_snapshot": plan.source_snapshot,
                }
            ):
                raise _refuse()
            saved = connection.execute(
                "SELECT * FROM assessment_configuration_slots "
                "WHERE configuration_id=? ORDER BY ordinal",
                (configuration_id,),
            ).fetchall()
            if len(saved) != len(plan.items) or any(
                (
                    str(slot["slot_id"]) != item.slot_key
                    or int(slot["ordinal"]) != item.ordinal
                    or str(slot["question_type"]) != item.question_type
                    or str(slot["task_form"]) != item.task_form
                    or str(slot["objective_text"]) != item.scoring_focus
                    or int(slot["marks_basis_points"]) != item.marks_basis_points
                    or str(slot["primary_point_id"]) != item.primary_point_id
                    or json.loads(slot["point_slot_json"]) != item.model_dump(mode="json")
                )
                for slot, item in zip(saved, plan.items, strict=True)
            ):
                raise _refuse()
        except (ValidationError, TypeError, ValueError, KeyError):
            raise _refuse() from None

        # Revalidate the exact authorized source and original completed catalog;
        # cached receipt reads never invoke a model or invent a new qualification.
        source = freeze_point_sources(
            self.db,
            workspace_id=str(row["workspace_id"]),
            owner=str(row["owner_user_id"]),
            node_id=str(row["node_id"]),
            spec_version=int(row["spec_version"]),
        )
        if source.identity() != plan.source_snapshot:
            raise _refuse("ASSESSMENT_POINT_SOURCE_CHANGED")
        selections: list[dict[str, Any] | PointSlotSelection] = [
            PointSlotSelection(
                slot_id=item.slot_key,
                question_type=item.question_type,
                task_form=item.task_form,
                primary_point_id=item.primary_point_id,
                variation_purpose=item.variation_purpose,
            )
            for item in plan.items
        ]
        actual = self.policy.freeze_plan(source, plan.content_language, plan.intent_id, selections)
        if not same_point_plan_content(plan, actual):
            raise _refuse()
        return cast(sqlite3.Row, row), plan

    def freeze(
        self,
        connection: sqlite3.Connection,
        workspace: sqlite3.Row,
        node: sqlite3.Row,
        selections: list[Any],
        *,
        requested_id: str | None,
        intent_id: str | None,
        content_language: str | None,
    ) -> tuple[sqlite3.Row, tuple[PointQuestionSlot, ...]]:
        if not intent_id:
            raise _refuse("ASSESSMENT_INTENT_REQUIRED")
        if requested_id:
            # Scope authorization precedes any interpretation of private
            # plan/source/catalog state belonging to the requested record.
            authorized = connection.execute(
                "SELECT language FROM assessment_configurations WHERE id=? AND status='FROZEN' "
                "AND policy_version=? AND workspace_id=? AND owner_user_id=? AND course_id=? "
                "AND node_id=? AND spec_version=?",
                (
                    requested_id,
                    POINT_ASSESSMENT_POLICY_VERSION,
                    workspace["id"],
                    workspace["owner_user_id"],
                    workspace["course_id"],
                    node["id"],
                    node["spec_version"],
                ),
            ).fetchone()
            if authorized is None or (
                content_language is not None and content_language != str(authorized["language"])
            ):
                raise _refuse("ASSESSMENT_CONFIGURATION_CONFLICT")
            row, saved = self.read(connection, requested_id)
            if (
                str(row["workspace_id"]) != str(workspace["id"])
                or str(row["owner_user_id"]) != str(workspace["owner_user_id"])
                or str(row["course_id"]) != str(workspace["course_id"])
                or str(row["node_id"]) != str(node["id"])
                or int(row["spec_version"]) != int(node["spec_version"])
                or saved.intent_id != intent_id
                or (content_language is not None and content_language != saved.content_language)
            ):
                raise _refuse("ASSESSMENT_CONFIGURATION_CONFLICT")
            if selections:
                actual = self.policy.freeze_plan(
                    self._source(workspace, node), saved.content_language, intent_id, selections
                )
                if not same_point_plan_content(saved, actual):
                    raise _refuse("ASSESSMENT_CONFIGURATION_CONFLICT")
            return row, saved.items
        if content_language not in ("zh-CN", "en"):
            raise _refuse("ASSESSMENT_CONTENT_LANGUAGE_INVALID")
        if not selections:
            raise _refuse("ASSESSMENT_CONFIGURATION_REQUIRED")
        plan = self.policy.freeze_plan(
            self._source(workspace, node), content_language, intent_id, selections
        )
        # Start an outer caller-owned transaction before the savepoint. Without
        # it RELEASE would commit an otherwise transaction-free configuration.
        # The write reservation also serializes same-intent read/insert races.
        if not connection.in_transaction:
            connection.execute("BEGIN IMMEDIATE")
        # The preflight source may change before the write reservation. Re-read
        # under that reservation so no concurrent writer can silently bind an
        # obsolete catalog/plan to a newly frozen configuration.
        if self._source(workspace, node).identity() != plan.source_snapshot:
            raise _refuse("ASSESSMENT_POINT_SOURCE_CHANGED")
        existing = connection.execute(
            "SELECT config.id FROM assessment_configurations AS config "
            "JOIN assessment_point_configuration_plans AS plan ON plan.configuration_id=config.id "
            "WHERE config.workspace_id=? AND json_extract(plan.plan_json,'$.intent_id')=? LIMIT 2",
            (workspace["id"], intent_id),
        ).fetchall()
        if len(existing) > 1:
            raise _refuse("ASSESSMENT_CONFIGURATION_CONFLICT")
        if existing:
            row, saved = self.read(connection, str(existing[0]["id"]))
            if not same_point_plan_content(saved, plan):
                raise _refuse("ASSESSMENT_CONFIGURATION_CONFLICT")
            return row, saved.items
        series_id = (
            "assessment-"
            + hashlib.sha256(f"{workspace['id']}|{node['id']}".encode()).hexdigest()[:32]
        )
        revision = int(
            connection.execute(
                "SELECT COALESCE(MAX(revision),0)+1 FROM assessment_configurations "
                "WHERE series_id=?",
                (series_id,),
            ).fetchone()[0]
        )
        config_id = "assessment-config-" + plan.content_hash[:32]
        # Savepoint prevents partial DRAFT/plan/slot state even if the caller
        # catches a late SQLite refusal within its enclosing transaction.
        connection.execute("SAVEPOINT freeze_original_point_configuration")
        try:
            connection.execute(
                "INSERT INTO assessment_configurations("
                "id,series_id,revision,workspace_id,owner_user_id,course_id,node_id,spec_version,"
                "language,status,content_hash,policy_version) "
                "VALUES(?,?,?,?,?,?,?,?,?,'DRAFT',?,?)",
                (
                    config_id,
                    series_id,
                    revision,
                    workspace["id"],
                    workspace["owner_user_id"],
                    workspace["course_id"],
                    node["id"],
                    node["spec_version"],
                    plan.content_language,
                    plan.content_hash,
                    plan.policy_version,
                ),
            )
            connection.execute(
                "INSERT INTO assessment_point_configuration_plans(configuration_id,plan_json,"
                "content_hash,catalog_hash,source_snapshot) VALUES(?,?,?,?,?)",
                (
                    config_id,
                    plan.model_dump_json(),
                    plan.content_hash,
                    plan.catalog_hash,
                    plan.source_snapshot,
                ),
            )
            for item in plan.items:
                connection.execute(
                    "INSERT INTO assessment_configuration_slots("
                    "configuration_id,slot_id,ordinal,question_type,task_form,objective_text,"
                    "marks_basis_points,primary_point_id,point_slot_json) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        config_id,
                        item.slot_key,
                        item.ordinal,
                        item.question_type,
                        item.task_form,
                        item.scoring_focus,
                        item.marks_basis_points,
                        item.primary_point_id,
                        item.model_dump_json(),
                    ),
                )
            connection.execute(
                "UPDATE assessment_configurations SET status='FROZEN' WHERE id=?", (config_id,)
            )
            connection.execute("RELEASE SAVEPOINT freeze_original_point_configuration")
        except Exception:
            connection.execute("ROLLBACK TO SAVEPOINT freeze_original_point_configuration")
            connection.execute("RELEASE SAVEPOINT freeze_original_point_configuration")
            raise
        row = connection.execute(
            "SELECT * FROM assessment_configurations WHERE id=?", (config_id,)
        ).fetchone()
        return cast(sqlite3.Row, row), plan.items
