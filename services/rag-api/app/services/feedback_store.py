"""Durable persistence for user-initiated feedback reports (the human review queue).

The triage itself is a semantic suggestion (`app/jev/feedback_triage.py`); this store
is the deterministic backend side of it and owns the only write:

* one row per submitted report, written idempotently by ``report_key`` so a repeated
  submission cannot duplicate the queue;
* identifiers by default — the body columns are written **only** when the user set
  ``attach_body``, and migration 030's CHECK constraint enforces that structurally;
* the triage outcome is stored as a *suggestion* (category, severity, suggested human
  queue, receipts) and ``status`` starts ``OPEN``. Nothing here resolves, closes,
  deletes or sanctions anything: a human moves the status, and the module has no
  method that could do it automatically.

Reads are deliberately narrow: a reviewer lists the queue through the admin route, and
the per-owner projection exists so a user's own report is never mixed with another's.
"""

from __future__ import annotations

import sqlite3
from typing import Any
from uuid import uuid4

from app.db import Database
from app.jev.feedback_triage import FeedbackTriageResult

_INSERT = """
INSERT OR IGNORE INTO feedback_reports(
    id, report_key, owner_user_id, owner_scope_hash, course_id, product_surface,
    message_id, run_id, model, template_version, app_version,
    category, severity, suggested_queue, path, used_jev, jev_calls, confidence,
    definition_version, latency_ms, category_receipt_id, severity_receipt_id,
    attach_body, report_text, question_text, answer_text
) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


class FeedbackStore:
    """Read/write access to the durable feedback queue."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def record(
        self,
        result: FeedbackTriageResult,
        *,
        owner_user_id: str,
        authorization_scope: str,
    ) -> str:
        """Persist one triaged report and return its row id.

        The body fields are taken from the report the user submitted; because the
        report was validated before triage (``_require_opt_in``), a report that did
        not opt in carries no body text at all, and the table's CHECK constraint
        would reject one that did.
        """
        report = result.report
        row_id = f"feedback_{uuid4().hex}"
        with self.database.connect() as connection:
            connection.execute(
                _INSERT,
                (
                    row_id,
                    result.report_key,
                    owner_user_id,
                    result.owner_scope_hash,
                    result.course_id or report.course_id,
                    report.product_surface,
                    report.message_id,
                    report.run_id,
                    report.model,
                    report.template_version,
                    report.app_version,
                    result.category,
                    int(result.severity),
                    result.suggested_queue,
                    result.path,
                    1 if result.used_jev else 0,
                    int(result.jev_calls),
                    result.confidence,
                    result.definition_version,
                    result.latency_ms,
                    result.category_receipt_id,
                    result.severity_receipt_id,
                    1 if report.attach_body else 0,
                    report.report_text if report.attach_body else None,
                    report.question_text if report.attach_body else None,
                    report.answer_text if report.attach_body else None,
                ),
            )
            stored = connection.execute(
                "SELECT id FROM feedback_reports WHERE report_key=?",
                (result.report_key,),
            ).fetchone()
        return str(stored["id"]) if stored is not None else row_id

    # ------------------------------------------------------------------ reads

    def queue(
        self,
        *,
        status: str | None = "OPEN",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """The review queue, most severe first and then oldest first.

        Populated only by user submissions; ``status=None`` returns every status.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM feedback_reports {where} "
                "ORDER BY severity DESC, created_at ASC, rowid ASC LIMIT ? OFFSET ?",
                (*params, max(1, int(limit)), max(0, int(offset))),
            ).fetchall()
        return [_public(row) for row in rows]

    def owned(self, owner_user_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """This user's own reports only — never another owner's."""
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM feedback_reports WHERE owner_user_id=? "
                "ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (owner_user_id, max(1, int(limit))),
            ).fetchall()
        return [_public(row) for row in rows]

    def by_report_key(self, report_key: str) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM feedback_reports WHERE report_key=?", (report_key,)
            ).fetchone()
        return _public(row) if row is not None else None


def _public(row: sqlite3.Row) -> dict[str, Any]:
    """Project a row for a reviewer without inventing or dropping a field.

    ``dict(row)`` reads the column names through the row's mapping protocol; iterating
    the row directly would yield *values*, which silently breaks the projection.
    """
    item = dict(row)
    item["used_jev"] = bool(item.get("used_jev"))
    item["attach_body"] = bool(item.get("attach_body"))
    return item


__all__ = ["FeedbackStore"]
