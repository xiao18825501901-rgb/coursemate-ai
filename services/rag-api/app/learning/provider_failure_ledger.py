"""The durable ledger of failed model calls.

A failure used to leave one thing behind: the string
HYBRID_REVIEW_PROVIDER_FAILED, a row id and a step number.  Everything that
would say *where* the call failed -- the adapter error class, the terminal
status, the HTTP status, whether a response arrived at all, the latency and the
usage -- existed in memory and was dropped at the persistence boundary.  The
result was that no stored run could answer the only question that matters for a
failure rate: is this our request, our configuration, the network, or the model?

This module is the persistence boundary, and it records facts rather than
judgements.  It never retries, never rewrites a historical result and never
turns a failure into a semantic negative.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from app.db import Database
from app.learning.provider import FAILURE_LAYER_UNKNOWN, classify_failure_layer

# Roles that can appear in the ledger.  Kept open-ended on purpose: an author or
# blind-solve failure is a different class from a reviewer failure and must be
# distinguishable without inventing a roster that a later role would break.
KNOWN_FAILURE_ROLES = (
    "evidence_audit",
    "adversarial_audit",
    "specification_audit",
    "question_author",
    "blind_solve",
    "unknown",
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def failure_row(
    *,
    policy_revision: str,
    role: str,
    run: dict[str, Any],
    question_revision_hash: str | None = None,
    blueprint_hash: str | None = None,
    evidence_pack_hash: str | None = None,
    message: str = "",
) -> dict[str, Any]:
    """The exact row a failed call produces.  Pure, so it can be tested alone."""
    error_class = str(run.get("error_class") or "UNKNOWN")
    status = str(run.get("status") or "UNKNOWN")
    response_text = run.get("response_text")
    return {
        "id": f"hybridfail-{uuid4().hex}",
        "question_revision_hash": question_revision_hash,
        "blueprint_hash": blueprint_hash,
        "evidence_pack_hash": evidence_pack_hash,
        "policy_revision": policy_revision,
        "role": role,
        "call_id": str(run.get("provider_response_id") or run.get("call_id") or "UNASSIGNED"),
        "input_hash": str(run.get("input_hash") or ("0" * 64)),
        "model": str(run.get("model") or "UNKNOWN"),
        "provider": str(run.get("provider") or "UNKNOWN"),
        "protocol": str(run.get("protocol") or "UNKNOWN"),
        "region": str(run.get("region") or "UNKNOWN"),
        "template_version": str(run.get("template_version") or "UNVERSIONED"),
        "schema_version": str(run.get("schema_version") or "UNVERSIONED"),
        "terminal_status": status if status in {"BLOCKED", "FAILED", "UNKNOWN"} else "UNKNOWN",
        "error_class": error_class,
        "failure_layer": str(
            run.get("failure_layer")
            or classify_failure_layer(error_class=error_class, status=status)
        )
        or FAILURE_LAYER_UNKNOWN,
        "http_status": run.get("http_status"),
        "timeout_kind": run.get("timeout_kind"),
        "cause_chain_json": json.dumps(list(run.get("cause_chain") or [])),
        "latency_ms": int(run.get("latency_ms") or 0),
        "input_tokens": int(run.get("input_tokens") or 0),
        "output_tokens": int(run.get("output_tokens") or 0),
        "provider_response_id": run.get("provider_response_id"),
        "response_received": 1 if run.get("response_received") else 0,
        "output_limit_tokens": run.get("max_output_tokens"),
        "response_digest": (
            _digest(str(response_text))
            if response_text is not None
            else run.get("response_digest")
        ),
        # Private course material and model output live in the private database
        # and nowhere else; this column is why a complete response that failed
        # schema validation can be re-parsed locally instead of being re-bought.
        "response_text": str(response_text) if response_text is not None else None,
        "message": message[:500],
    }


def record_provider_failure(
    database: Database,
    *,
    policy_revision: str,
    role: str,
    run: dict[str, Any],
    question_revision_hash: str | None = None,
    blueprint_hash: str | None = None,
    evidence_pack_hash: str | None = None,
    message: str = "",
) -> str:
    """Persist one failed call and return its row id.  Never retries."""
    row = failure_row(
        policy_revision=policy_revision,
        role=role,
        run=run,
        question_revision_hash=question_revision_hash,
        blueprint_hash=blueprint_hash,
        evidence_pack_hash=evidence_pack_hash,
        message=message,
    )
    columns = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    with database.connect() as connection:
        connection.execute(
            f"INSERT INTO hybrid_provider_failures ({columns}) VALUES ({placeholders})",
            tuple(row.values()),
        )
    return str(row["id"])


def failure_census(
    database: Database, *, question_revision_hash: str | None = None
) -> dict[str, int]:
    """Counts by layer, so a run can report its own failure composition."""
    sql = (
        "SELECT failure_layer, COUNT(*) FROM hybrid_provider_failures"
        + (" WHERE question_revision_hash = ?" if question_revision_hash else "")
        + " GROUP BY failure_layer"
    )
    parameters = (question_revision_hash,) if question_revision_hash else ()
    with database.connect() as connection:
        rows = connection.execute(sql, parameters).fetchall()
    return {str(row[0]): int(row[1]) for row in rows}
