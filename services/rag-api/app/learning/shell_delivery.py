"""Record a completed free-text shell teaching into the V3 evidence ledger.

The refreshed shell's two-stage flow ends with persisted free-text content in
``cmui_messages``. This module is the single submission point that turns a
reviewer-confirmed delivery into the authoritative records:

* one ``teaching_units`` row (workflow ``TEACHING``) whose content_json carries
  the actual second-stage body in a section, so the text stays recoverable;
* one ``teaching_delivery_evidence`` row per confirmed REQUIRED item with
  ``validation_status='REVIEWED'`` (schema 022) and the section content hash;
* a ``learning_coverage`` row and a consistent journey status update
  (LEARNING / LEARNED), recomputed the same way the plan-based teach() does.

Idempotency: ``operation_id`` is the stable cmui run id and
``teaching_units(journey_id, operation_id)`` is unique, so a retry after a
cross-database interruption replays the same bookkeeping and never touches the
provider again. No evidence is ever written for failed, cancelled or truncated
runs because the caller only invokes this after the run's conditional final
write has claimed ``completed``.
"""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from typing import Any

from app.learning.coverage_review import CoverageReviewer
from app.learning.orchestrator import encode

SECTION_ID = "teaching"
VALIDATION_REASON = "SHELL_COVERAGE_REVIEW_V1"
COUNTED_STATUSES = "('VALIDATED','LEGACY_PRESERVED','REVIEWED')"


def section_hash(section: dict[str, Any]) -> str:
    return hashlib.sha256(encode(section).encode()).hexdigest()


def _progress(
    connection: sqlite3.Connection, journey_id: str, required_ids: set[str]
) -> str:
    if not required_ids:
        return "LEARNED"
    covered = {
        str(row[0])
        for row in connection.execute(
            f"SELECT DISTINCT item_id FROM teaching_delivery_evidence "
            f"WHERE journey_id=? AND validation_status IN {COUNTED_STATUSES}",
            (journey_id,),
        )
    }
    return "LEARNED" if required_ids <= covered else "LEARNING"


def _replay(
    connection: sqlite3.Connection,
    journey_id: str,
    operation_id: str,
    required_ids: set[str],
) -> dict[str, Any]:
    unit = connection.execute(
        "SELECT id FROM teaching_units WHERE journey_id=? AND operation_id=?",
        (journey_id, operation_id),
    ).fetchone()
    if unit is None:
        raise RuntimeError("Expected the submitted teaching unit to exist")
    evidence = connection.execute(
        "SELECT item_id, section_id, validation_status FROM "
        "teaching_delivery_evidence WHERE teaching_unit_id=?",
        (unit["id"],),
    ).fetchall()
    return {
        "unit_id": unit["id"],
        "covered": sorted(
            {
                str(row["item_id"])
                for row in evidence
                if row["validation_status"] in ("VALIDATED", "REVIEWED")
            }
        ),
        "progress": _progress(connection, journey_id, required_ids),
        "replayed": True,
    }


def submit_shell_delivery(
    database: Any,
    *,
    workspace_id: str,
    journey_id: str,
    node: dict[str, Any],
    spec_version: int,
    items: list[dict[str, Any]],
    content: str,
    operation_id: str,
    provenance: dict[str, Any],
    reviewer: CoverageReviewer,
) -> dict[str, Any]:
    """Submit one completed free-text delivery; replay on retry."""

    required = [item for item in items if item.get("requirement") == "REQUIRED"]
    required_ids = {str(item["item_id"]) for item in required}

    with database.connect() as connection:
        existing = connection.execute(
            "SELECT id FROM teaching_units WHERE journey_id=? AND operation_id=?",
            (journey_id, operation_id),
        ).fetchone()
        if existing is not None:
            return _replay(connection, journey_id, operation_id, required_ids)

    confirmed = [
        str(item["item_id"])
        for item in required
        if item["item_id"] in reviewer.review(required, content, provenance)
    ]
    # Evidence is immutable and coverage counts distinct items: never record a
    # second confirmation for an item this journey already covered.
    with database.connect() as connection:
        already = {
            str(row[0])
            for row in connection.execute(
                f"SELECT DISTINCT item_id FROM teaching_delivery_evidence "
                f"WHERE journey_id=? AND validation_status IN {COUNTED_STATUSES}",
                (journey_id,),
            )
        }
    confirmed = [item_id for item_id in confirmed if item_id not in already]
    section = {
        "section_id": SECTION_ID,
        "content": content,
        "source": "cmui_free_text_run",
        "run_id": operation_id,
    }
    unit_id = "unit_" + uuid.uuid4().hex
    try:
        with database.connect() as connection:
            connection.execute(
                "INSERT INTO teaching_units("
                "id,journey_id,operation_id,workflow,content_json,plan_json,provenance_json"
                ") VALUES(?,?,?,'TEACHING',?,'{}',?)",
                (
                    unit_id,
                    journey_id,
                    operation_id,
                    encode({"sections": [section]}),
                    encode(
                        {
                            **provenance,
                            "workflow": "SHELL_FREE_TEXT_V1",
                            "spec_hash": node.get("spec_hash"),
                            "node_id": node["id"],
                            "spec_version": spec_version,
                        }
                    ),
                ),
            )
            for item_id in confirmed:
                connection.execute(
                    "INSERT INTO teaching_delivery_evidence("
                    "id,journey_id,node_id,spec_version,item_id,teaching_unit_id,"
                    "section_id,plan_version_id,plan_unit_key,content_hash,"
                    "validation_status,validation_reason"
                    ") VALUES(?,?,?,?,?,?,?,NULL,NULL,?,'REVIEWED',?)",
                    (
                        "evidence_" + uuid.uuid4().hex,
                        journey_id,
                        node["id"],
                        spec_version,
                        item_id,
                        unit_id,
                        SECTION_ID,
                        section_hash(section),
                        VALIDATION_REASON,
                    ),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO learning_coverage("
                    "journey_id,item_id,unit_id,section_ids_json"
                    ") VALUES(?,?,?,?)",
                    (journey_id, item_id, unit_id, encode([SECTION_ID])),
                )
            progress = _progress(connection, journey_id, required_ids)
            connection.execute(
                "UPDATE learning_journeys SET status=? WHERE id=?", (progress, journey_id)
            )
    except sqlite3.IntegrityError:
        # A concurrent retry (another worker or a recovery pass) claimed the same
        # operation id first; the unique index on teaching_units(journey_id,
        # operation_id) turns this into a replay instead of a duplicate.
        with database.connect() as connection:
            return _replay(connection, journey_id, operation_id, required_ids)
    return {
        "unit_id": unit_id,
        "covered": confirmed,
        "progress": progress,
        "replayed": False,
        "workspace_id": workspace_id,
        "journey_id": journey_id,
        "spec_version": spec_version,
    }
