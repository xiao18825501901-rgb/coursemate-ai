"""Read-only exact authority for point compilation, never a verified catalog.

This input retains direct source conditions and the original Teaching Spec. A
citation pack is not entailment/dedup/scorability approval and has no K value.
"""

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal

from pydantic import Field

from app.db import Database
from app.errors import ApiError
from app.learning.models import Contract, Identifier
from app.learning.question_blueprint import Hex64, ObjectiveResolutionError, resolve_objective
from app.learning.question_evidence import (
    EvidencePackAccess,
    EvidencePackError,
    QuestionEvidencePack,
    build_evidence_pack,
)
from app.learning.workspaces import workspace_for


class PointSourceSnapshot(Contract):
    schema_version: Literal["cj.assessment.point-source.v1"] = "cj.assessment.point-source.v1"
    owner_user_id: Identifier
    workspace_id: Identifier
    course_id: Identifier
    private_course_id: Identifier
    node_id: Identifier
    spec_version: int = Field(ge=1, strict=True)
    spec_content_hash: Hex64
    targets: list[QuestionEvidencePack] = Field(min_length=1)

    def identity(self) -> str:
        body = json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(body.encode()).hexdigest()


class _SourceReadView(Database):
    """Canonical readers share one fresh read-only transaction, not a cache."""

    def __init__(self, database: Database, connection: sqlite3.Connection):
        self.path = database.path
        self.upload_dir = database.upload_dir
        self.storage_cache_dir = database.storage_cache_dir
        self.storage_path_resolver = database.storage_path_resolver
        self.storage_object_probe = database.storage_object_probe
        self.storage_range_resolver = database.storage_range_resolver
        self.v3_enabled = database.v3_enabled
        # The mounted campus/identity policy is dynamic, not a Database field.
        self.course_content_authorizer = getattr(database, "course_content_authorizer", None)
        self._connection = connection

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        # Only the outer Database context owns commit, rollback and close.
        yield self._connection


def freeze_point_sources(
    database: Database,
    *,
    workspace_id: str,
    owner: str,
    node_id: str,
    spec_version: int | None = None,
) -> PointSourceSnapshot:
    with database.connect() as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        return _freeze_point_sources(
            _SourceReadView(database, connection),
            workspace_id=workspace_id,
            owner=owner,
            node_id=node_id,
            spec_version=spec_version,
        )


def _freeze_point_sources(
    database: Database,
    *,
    workspace_id: str,
    owner: str,
    node_id: str,
    spec_version: int | None = None,
) -> PointSourceSnapshot:
    # Imported locally so AssessmentService can consume this source input while
    # retaining its existing, canonical node/publication authority in one place.
    from app.learning.assessments import AssessmentService

    if spec_version is not None and (type(spec_version) is not int or spec_version < 1):
        raise ApiError(422, "ASSESSMENT_SPEC_VERSION_INVALID", "The source version is invalid.")
    workspace = workspace_for(database, workspace_id, owner)
    with database.connect() as db:
        node = AssessmentService._atomic_node(db, workspace, node_id, spec_version=spec_version)
        version = int(node["spec_version"])
        rows = db.execute(
            "SELECT item_id FROM teaching_items WHERE node_id=? AND spec_version=? "
            "AND requirement='REQUIRED' ORDER BY ordinal,item_id",
            (node_id, version),
        ).fetchall()
        objectives = [
            resolve_objective(
                db, node_id=node_id, spec_version=version, item_id=str(row["item_id"])
            )
            for row in rows
        ]
    if not objectives:
        raise ApiError(409, "ASSESSMENT_POINTS_NOT_READY", "Assessable sources are not ready.")
    access = EvidencePackAccess(
        owner, str(workspace["course_id"]), str(workspace["private_course_id"])
    )
    try:
        targets = [
            build_evidence_pack(database, objective=item, access=access, excerpt_limit=6000)
            for item in objectives
        ]
    except (EvidencePackError, ObjectiveResolutionError):
        raise ApiError(
            409, "ASSESSMENT_POINTS_NOT_READY", "Assessable sources are not ready."
        ) from None
    if any(fragment.truncated for target in targets for fragment in target.fragments):
        # Do not silently discard later conditions from a source to make a point.
        raise ApiError(409, "ASSESSMENT_POINTS_SOURCE_TOO_LARGE", "The source needs preparation.")
    return PointSourceSnapshot(
        owner_user_id=owner,
        workspace_id=workspace_id,
        course_id=str(workspace["course_id"]),
        private_course_id=str(workspace["private_course_id"]),
        node_id=node_id,
        spec_version=version,
        spec_content_hash=objectives[0].spec_content_hash,
        targets=targets,
    )


def verify_point_sources(database: Database, saved: PointSourceSnapshot) -> None:
    actual = freeze_point_sources(
        database,
        workspace_id=saved.workspace_id,
        owner=saved.owner_user_id,
        node_id=saved.node_id,
        spec_version=saved.spec_version,
    )
    if actual.identity() != saved.identity():
        raise ApiError(409, "ASSESSMENT_POINT_SOURCE_CHANGED", "The saved source is unavailable.")
