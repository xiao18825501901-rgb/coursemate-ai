import json
import sqlite3
from typing import Any, cast
from uuid import uuid4

from app.db import Database
from app.errors import ApiError
from app.learning.models import TeachingPlan


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class TeachingPlanRepository:
    """Owns the private, immutable plan cache and its narrow mutable lifecycle."""

    def __init__(self, database: Database) -> None:
        self.db = database

    def preference_version(
        self, workspace_id: str, preference_hash: str, payload: dict[str, str]
    ) -> dict[str, Any]:
        with self.db.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM learning_preference_versions "
                "WHERE workspace_id=? AND preference_hash=?",
                (workspace_id, preference_hash),
            ).fetchone()
            if row is None:
                version = int(
                    connection.execute(
                        "SELECT COALESCE(MAX(version),0)+1 FROM learning_preference_versions "
                        "WHERE workspace_id=?",
                        (workspace_id,),
                    ).fetchone()[0]
                )
                connection.execute(
                    "INSERT INTO learning_preference_versions("
                    "workspace_id,version,preference_hash,preference_json) VALUES(?,?,?,?)",
                    (workspace_id, version, preference_hash, encode(payload)),
                )
                row = connection.execute(
                    "SELECT * FROM learning_preference_versions "
                    "WHERE workspace_id=? AND version=?",
                    (workspace_id, version),
                ).fetchone()
        return dict(cast(sqlite3.Row, row))

    @staticmethod
    def invalidation_reason(
        row: sqlite3.Row,
        identity: dict[str, Any],
        stored_trigger_ids: list[str],
    ) -> str:
        if stored_trigger_ids != identity["performance_trigger_ids"]:
            return "PERFORMANCE_CHANGED"
        if row["preference_hash"] != identity["preference_hash"]:
            return "PREFERENCE_CHANGED"
        if json.loads(row["source_version_ids_json"]) != identity["source_version_ids"]:
            return "SOURCE_SET_CHANGED"
        if row["bridge_id"] != identity["bridge_id"] or row["bridge_revision"] != identity[
            "bridge_revision"
        ]:
            return "BRIDGE_CHANGED"
        if (
            row["template_version"] != identity["template_version"]
            or row["schema_version"] != identity["schema_version"]
            or row["model_id"] != identity["model_id"]
            or row["protocol"] != identity["protocol"]
        ):
            return "RUNTIME_CHANGED"
        return "PLAN_INPUT_CHANGED"

    def cached_plan(
        self,
        *,
        workspace_id: str,
        node_id: str,
        journey_id: str,
        identity: dict[str, Any],
        cache_key: str,
        explicit_replan: bool,
    ) -> sqlite3.Row | None:
        with self.db.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE teaching_plan_versions SET status='INVALIDATED',"
                "invalidated_reason='SPEC_UPDATED',"
                "invalidated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                "WHERE workspace_id=? AND node_id=? AND journey_id!=? AND status='ACTIVE'",
                (workspace_id, node_id, journey_id),
            )
            rows = connection.execute(
                "SELECT * FROM teaching_plan_versions WHERE workspace_id=? AND node_id=? "
                "AND journey_id=? AND status='ACTIVE' ORDER BY version DESC",
                (workspace_id, node_id, journey_id),
            ).fetchall()
            for row in rows:
                stored_trigger_ids = sorted(
                    str(trigger[0])
                    for trigger in connection.execute(
                        "SELECT trigger_id FROM teaching_plan_performance_triggers "
                        "WHERE plan_version_id=?",
                        (row["id"],),
                    )
                )
                if explicit_replan or row["cache_key"] != cache_key:
                    reason = (
                        "EXPLICIT_REPLAN"
                        if explicit_replan
                        else self.invalidation_reason(
                            row,
                            identity,
                            stored_trigger_ids,
                        )
                    )
                    connection.execute(
                        "UPDATE teaching_plan_versions SET status='INVALIDATED',"
                        "invalidated_reason=?,"
                        "invalidated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                        (reason, row["id"]),
                    )
                else:
                    return cast(sqlite3.Row, row)
        return None

    def invalidate(self, plan_id: str, reason: str) -> None:
        with self.db.connect() as connection:
            connection.execute(
                "UPDATE teaching_plan_versions SET status='INVALIDATED',"
                "invalidated_reason=?,"
                "invalidated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                "WHERE id=? AND status='ACTIVE'",
                (reason, plan_id),
            )

    def save(
        self,
        *,
        workspace: sqlite3.Row,
        journey: sqlite3.Row,
        request_revision: int,
        operation_id: str,
        plan: TeachingPlan,
        run: dict[str, Any],
        preference: dict[str, Any],
        identity: dict[str, Any],
        cache_key: str,
        input_hash: str,
        template_version: str,
        model_id: str,
        protocol: str,
    ) -> sqlite3.Row:
        plan_id = uuid4().hex
        with self.db.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current_revision = connection.execute(
                "SELECT revision FROM learning_workspaces WHERE id=?", (workspace["id"],)
            ).fetchone()
            if current_revision is None or current_revision["revision"] != request_revision + 1:
                raise ApiError(
                    409,
                    "REVISION_CONFLICT",
                    "The workspace changed before the teaching plan could be saved.",
                )
            version = int(
                connection.execute(
                    "SELECT COALESCE(MAX(version),0)+1 FROM teaching_plan_versions "
                    "WHERE journey_id=?",
                    (journey["id"],),
                ).fetchone()[0]
            )
            connection.execute(
                "INSERT INTO teaching_plan_versions("
                "id,workspace_id,owner_user_id,course_id,journey_id,node_id,spec_version,"
                "version,case_type,preference_version,preference_hash,template_version,"
                "schema_version,model_id,protocol,source_version_ids_json,bridge_id,"
                "bridge_revision,cache_key,input_hash,plan_json,planner_operation_id,"
                "provider_usage_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    plan_id,
                    workspace["id"],
                    workspace["owner_user_id"],
                    workspace["course_id"],
                    journey["id"],
                    journey["node_id"],
                    journey["spec_version"],
                    version,
                    plan.case_type,
                    preference["version"],
                    preference["preference_hash"],
                    template_version,
                    plan.schema_version,
                    model_id,
                    protocol,
                    encode(identity["source_version_ids"]),
                    identity["bridge_id"],
                    identity["bridge_revision"],
                    cache_key,
                    input_hash,
                    encode(plan.model_dump()),
                    operation_id,
                    encode(run),
                ),
            )
            for ordinal, unit in enumerate(plan.units):
                connection.execute(
                    "INSERT INTO teaching_plan_units("
                    "plan_version_id,unit_key,ordinal,target_item_ids_json,content_json) "
                    "VALUES(?,?,?,?,?)",
                    (
                        plan_id,
                        unit.unit_key,
                        ordinal,
                        encode(unit.target_item_ids),
                        encode(unit.model_dump()),
                    ),
                )
            for trigger_id in identity["performance_trigger_ids"]:
                connection.execute(
                    "INSERT INTO teaching_plan_performance_triggers("
                    "plan_version_id,trigger_id) VALUES(?,?)",
                    (plan_id, trigger_id),
                )
            row = connection.execute(
                "SELECT * FROM teaching_plan_versions WHERE id=?", (plan_id,)
            ).fetchone()
        return cast(sqlite3.Row, row)

    def delivered_unit_keys(self, plan_id: str) -> set[str]:
        with self.db.connect() as connection:
            return {
                str(row[0])
                for row in connection.execute(
                    "SELECT plan_unit_key FROM teaching_unit_plan_links "
                    "WHERE plan_version_id=?",
                    (plan_id,),
                )
            }

    @staticmethod
    def complete_if_delivered(connection: sqlite3.Connection, plan_id: str) -> None:
        pending = connection.execute(
            "SELECT COUNT(*) FROM teaching_plan_units AS plan_unit "
            "WHERE plan_unit.plan_version_id=? AND NOT EXISTS("
            "SELECT 1 FROM teaching_unit_plan_links AS link "
            "WHERE link.plan_version_id=plan_unit.plan_version_id "
            "AND link.plan_unit_key=plan_unit.unit_key)",
            (plan_id,),
        ).fetchone()[0]
        if pending == 0:
            connection.execute(
                "UPDATE teaching_plan_versions SET status='COMPLETED' WHERE id=?",
                (plan_id,),
            )
