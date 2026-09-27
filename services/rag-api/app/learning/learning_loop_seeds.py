"""Plan and publish learning-loop seed packs from existing real authorities.

The adapter never copies synthetic fixture payloads into the application DB.  It
only envelopes current course/document/spec/question references.  A course that
lacks a published target with at least two distinct READY question families is
kept as a non-active ``WAITING_SOURCE`` revision.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class SeedTarget:
    node_id: str
    spec_version: int
    objective_id: str
    ready_questions: int
    distinct_families: int


@dataclass(frozen=True)
class SeedPlan:
    course_id: str
    course_name: str
    offering_id: str
    source_refs: tuple[str, ...]
    source_manifest_hash: str
    targets: tuple[SeedTarget, ...]
    status: str
    review_status: str
    rights_status: str
    reason: str

    def public(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "source_refs": list(self.source_refs),
            "targets": [asdict(target) for target in self.targets],
        }


def _course(connection: sqlite3.Connection, course_id: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT id,name,course_type,visibility,publication_status,published_at "
        "FROM courses WHERE id=?",
        (course_id,),
    ).fetchone()


def plan_seed(connection: sqlite3.Connection, course_id: str) -> SeedPlan:
    """Build a no-write publication plan from the current real DB state."""

    connection.row_factory = sqlite3.Row
    course = _course(connection, course_id)
    if course is None:
        empty_hash = hashlib.sha256(b"[]").hexdigest()
        return SeedPlan(
            course_id=course_id,
            course_name=course_id,
            offering_id=course_id,
            source_refs=(),
            source_manifest_hash=empty_hash,
            targets=(),
            status="DRAFT",
            review_status="WAITING_SOURCE",
            rights_status="UNKNOWN",
            reason="COURSE_NOT_FOUND",
        )

    documents = connection.execute(
        "SELECT id,sha256 FROM documents WHERE course_id=? AND status='ready' "
        "ORDER BY id",
        (course_id,),
    ).fetchall()
    source_refs = tuple(
        f"document:{row['id']}@sha256:{row['sha256']}" for row in documents
    )
    manifest_hash = hashlib.sha256(_canonical(source_refs).encode("utf-8")).hexdigest()
    candidates = connection.execute(
        "SELECT provenance.node_id,provenance.spec_version,provenance.objective_id,"
        "COUNT(*) AS ready_questions,COUNT(DISTINCT question.family_id) AS families "
        "FROM question_engine_provenance AS provenance "
        "JOIN assessment_question_revisions AS question "
        "ON question.id=provenance.question_revision_id "
        "JOIN knowledge_nodes AS node ON node.id=provenance.node_id "
        "JOIN teaching_items AS item ON item.node_id=provenance.node_id "
        "AND item.spec_version=provenance.spec_version "
        "AND item.item_id=provenance.objective_id "
        "WHERE question.course_id=? AND provenance.publication_status='READY' "
        "AND node.course_id=? AND node.kind='ATOMIC' AND node.status='PUBLISHED' "
        "GROUP BY provenance.node_id,provenance.spec_version,provenance.objective_id "
        "HAVING COUNT(DISTINCT question.family_id)>=2 "
        "ORDER BY families DESC,ready_questions DESC,provenance.node_id",
        (course_id, course_id),
    ).fetchall()
    targets = tuple(
        SeedTarget(
            node_id=str(row["node_id"]),
            spec_version=int(row["spec_version"]),
            objective_id=str(row["objective_id"]),
            ready_questions=int(row["ready_questions"]),
            distinct_families=int(row["families"]),
        )
        for row in candidates
    )
    publishable_course = (
        course["course_type"] == "official"
        and course["publication_status"] == "published"
        and course["published_at"] is not None
    )
    if not source_refs:
        reason = "NO_READY_DOCUMENTS"
    elif not publishable_course:
        reason = "COURSE_NOT_PUBLISHED"
    elif not targets:
        reason = "NO_PUBLISHED_TARGET_WITH_TWO_READY_FAMILIES"
    else:
        reason = "READY"
    ready = reason == "READY"
    return SeedPlan(
        course_id=course_id,
        course_name=str(course["name"]),
        offering_id=course_id,
        source_refs=source_refs,
        source_manifest_hash=manifest_hash,
        targets=targets,
        status="ACTIVE" if ready else "DRAFT",
        review_status="SOURCE_VERIFIED" if ready else "WAITING_SOURCE",
        rights_status="CAMPUS_AUTHORIZED" if ready else "UNKNOWN",
        reason=reason,
    )


def apply_seed(
    connection: sqlite3.Connection,
    *,
    plan: SeedPlan,
    actor_user_id: str,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Idempotently apply one first-party plan after schema 60 is installed."""

    if not actor_user_id.strip():
        raise ValueError("VERIFIED_ACTOR_REQUIRED")
    connection.row_factory = sqlite3.Row
    version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    if int(version or 0) < 60:
        raise RuntimeError("LEARNING_LOOP_SCHEMA_60_REQUIRED")
    existing = connection.execute(
        "SELECT * FROM learning_loop_pack_revisions WHERE course_id=? "
        "AND offering_id=? ORDER BY revision DESC LIMIT 1",
        (plan.course_id, plan.offering_id),
    ).fetchone()
    if existing is not None:
        if (
            str(existing["source_manifest_hash"]) == plan.source_manifest_hash
            and str(existing["review_status"]) == plan.review_status
            and str(existing["status"]) == plan.status
        ):
            return {"action": "UNCHANGED", "pack_revision_id": str(existing["id"])}
        raise RuntimeError("PACK_REVISION_REVIEW_REQUIRED")

    revision = 1
    identity = {
        "course_id": plan.course_id,
        "offering_id": plan.offering_id,
        "revision": revision,
        "source_manifest_hash": plan.source_manifest_hash,
        "targets": [asdict(target) for target in plan.targets],
        "review_status": plan.review_status,
        "status": plan.status,
    }
    pack_id = "learning-pack-" + hashlib.sha256(
        _canonical(identity).encode("utf-8")
    ).hexdigest()[:24]
    timestamp = observed_at or _now()
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute(
            "INSERT INTO learning_loop_pack_revisions("
            "id,course_id,offering_id,revision,source_manifest_hash,source_refs_json,"
            "rights_status,review_status,status,created_by_user_id,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                pack_id,
                plan.course_id,
                plan.offering_id,
                revision,
                plan.source_manifest_hash,
                _canonical(plan.source_refs),
                plan.rights_status,
                plan.review_status,
                plan.status,
                actor_user_id,
                timestamp,
            ),
        )
        for target in plan.targets if plan.status == "ACTIVE" else ():
            connection.execute(
                "INSERT INTO learning_loop_pack_targets("
                "pack_revision_id,node_id,spec_version,objective_id,terminology_json,"
                "rubric_refs_json,intervention_refs_json) VALUES(?,?,?,?,?,?,?)",
                (
                    pack_id,
                    target.node_id,
                    target.spec_version,
                    target.objective_id,
                    "[]",
                    "[]",
                    "[]",
                ),
            )
        if plan.status == "ACTIVE":
            connection.execute(
                "INSERT INTO learning_loop_course_flags("
                "course_id,enabled,enabled_by_user_id,enabled_at,history_complete_from) "
                "VALUES(?,1,?,?,?) ON CONFLICT(course_id) DO UPDATE SET "
                "enabled=excluded.enabled,enabled_by_user_id=excluded.enabled_by_user_id,"
                "enabled_at=excluded.enabled_at,history_complete_from=COALESCE("
                "learning_loop_course_flags.history_complete_from,excluded.history_complete_from)",
                (plan.course_id, actor_user_id, timestamp, timestamp),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return {
        "action": "ACTIVATED" if plan.status == "ACTIVE" else "RECORDED_WAITING_SOURCE",
        "pack_revision_id": pack_id,
        "targets": len(plan.targets) if plan.status == "ACTIVE" else 0,
    }
