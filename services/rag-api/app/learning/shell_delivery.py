"""Record a completed free-text shell teaching into the V3 evidence ledger.

The refreshed shell's two-stage flow ends with persisted free-text content in
``cmui_messages``. This module is the single submission point that turns a
reviewer-confirmed delivery into the authoritative records:

* one ``teaching_units`` row (workflow ``TEACHING``) whose content_json carries
  the actual second-stage body in a section, so the text stays recoverable, and
  whose provenance persists the full review outcome (reviewer, policy version,
  per-item verdicts and error state);
* one ``teaching_delivery_evidence`` row per SERVER-VALIDATED item with
  ``validation_status='REVIEWED'`` (schema 022) and the section content hash;
* a ``learning_coverage`` row and a consistent journey status update
  (LEARNING / LEARNED), recomputed the same way the plan-based teach() does.

The reviewer only proposes candidates. Before any evidence is written the
server checks, for every ``covered`` verdict: the item exists in the frozen
spec passed in, the verdict's evidence quote appears verbatim in the saved
body, and the item is not already covered in this journey.

Idempotency: ``operation_id`` is the stable cmui run id and
``teaching_units(journey_id, operation_id)`` is unique, so a retry after a
cross-database interruption replays the same bookkeeping and never calls the
teaching or reviewing model again. No evidence is ever written for failed,
cancelled or truncated runs because the caller only invokes this after the
run's conditional final write has claimed ``completed``.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import uuid
from typing import Any

from app.learning.coverage_review import CoverageReviewer, ReviewOutcome
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


_QUOTE_SEGMENT_SPLIT = re.compile(r"(?:…|\.\.\.|\n)+")
_MIN_SEGMENT_CHARS = 5
_FORMAT_STRIP = re.compile(r"\*\*|`|\$")
_PUNCTUATION_MAP = str.maketrans(
    {
        "：": ":",
        "，": ",",
        "。": ".",
        "？": "?",
        "！": "!",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "≥": ">=",
        "≤": "<=",
        "→": "->",
        "“": '"',
        "”": '"',
    }
)


def _normalize_quote_text(text: str) -> str:
    """Formatting-tolerant normalisation for quote anchoring.

    Live reviewers quote loosely: markdown bold, backticks, LaTeX delimiters
    and Chinese/ASCII punctuation variants differ from the saved body. These
    are stripped/normalised on BOTH sides so anchoring still verifies the
    substantive words exist verbatim, not that formatting was copied.
    """

    lowered = text.lower()
    stripped = _FORMAT_STRIP.sub("", lowered)
    mapped = stripped.translate(_PUNCTUATION_MAP)
    return re.sub(r"\s+", " ", mapped)


def _quote_anchored(quote: str, content: str) -> bool:
    """The reviewer's evidence quote must anchor to the saved body.

    Live reviewers join fragments with ellipses; a single contiguous match is
    therefore too strict. Every non-trivial segment of the quote must appear
    verbatim in the saved content after formatting-tolerant normalisation,
    which anchors the evidence to the real body without demanding one
    unbroken, identically formatted sentence.
    """

    segments = [
        part.strip()
        for part in _QUOTE_SEGMENT_SPLIT.split(_normalize_quote_text(quote or ""))
        if len(part.strip()) >= _MIN_SEGMENT_CHARS
    ]
    if not segments:
        return False
    normalized_content = _normalize_quote_text(content or "")
    return all(part in normalized_content for part in segments)


def _server_validate(
    outcome: ReviewOutcome,
    required: list[dict[str, Any]],
    content: str,
) -> list[str]:
    """Server-side confirmation of the reviewer's candidate verdicts.

    A ``covered`` verdict only counts when its evidence quote anchors to the
    saved body (every non-trivial segment appears verbatim after formatting
    normalisation) and the item is in the frozen spec passed in. Uncertain,
    partial, refusals, out-of-scope ids and quote mismatches never write
    coverage.
    """

    if outcome.status != "completed":
        return []
    confirmed: list[str] = []
    for item in required:
        item_id = str(item["item_id"])
        verdict = outcome.verdicts.get(item_id)
        if not verdict or verdict.get("decision") != "covered":
            continue
        if _quote_anchored(str(verdict.get("evidence_quote") or ""), content or ""):
            confirmed.append(item_id)
    return confirmed


async def submit_shell_delivery(
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
            # The review was already persisted with the unit: replay the saved
            # bookkeeping and never call a model again.
            return _replay(connection, journey_id, operation_id, required_ids)

    # The review runs on the already-saved body, outside any write transaction.
    outcome = await reviewer.review(
        required,
        content,
        {
            **provenance,
            "spec_version": spec_version,
            "node_id": node["id"],
        },
    )
    confirmed = _server_validate(outcome, required, content)
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
                            "review": {
                                "status": outcome.status,
                                "reviewer": outcome.reviewer,
                                "policy_version": outcome.policy_version,
                                "verdicts": outcome.verdicts,
                                "error": outcome.error,
                                "confirmed": confirmed,
                            },
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
        "review": {
            "status": outcome.status,
            "reviewer": outcome.reviewer,
            "error": outcome.error,
        },
    }
