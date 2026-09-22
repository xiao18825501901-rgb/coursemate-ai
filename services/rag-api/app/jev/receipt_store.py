"""SQLite persistence for Jev decision receipts and the suggestion cache.

A receipt is written once per call (including failed calls, with an outcome).
Cache lookup honours the catalog ``cache_scope``: it only returns a suggestion
when every dimension in scope matches — authorization scope (owner scope hash),
course, workspace, material revision, node/spec, question definition hash, input
hash and provider model version — so a material-revision change or an
authorization change is a natural miss and :meth:`invalidate` can also delete
explicitly.

**Write contention.** Some decisions are made while the caller already holds a
write transaction on the same database (the assessment grading loop is the real
case: it calls the criterion review from inside its own transaction). SQLite
allows one writer, so a receipt INSERT on a second connection would otherwise
wait for the full ``busy_timeout`` and then raise ``database is locked`` — inside
a learner's grading request. A receipt is **observability, never authority**, so
this store keeps its own short timeout and treats a lock conflict as a dropped
receipt: the decision itself is unaffected, the business operation never stalls
and never fails. Anything other than a lock/busy error is still raised, because a
real schema or data bug must not hide behind a best-effort write.

**Absent ledger.** The one schema error that is *not* a bug is the table simply not
existing yet: the receipts table arrives with migration 028, which belongs to the
V3 migration set, so a V2-only deployment — and the window in which new code is
running before its migration has been applied — has a working database without it.
Raising there would turn a deployment ordering detail into a failed learner
request, so a missing table is treated like a lock conflict: the lookup reports a
cache miss and the write drops the receipt. Every other ``OperationalError`` still
propagates.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from app.jev.catalog import DecisionDefinition
from app.jev.gateway import Receipt
from app.jev.models import CacheScope

# How long a receipt write may wait for another writer before it is dropped. Short
# on purpose: it sits in a learner-facing request path, and a missing receipt is a
# far smaller problem than a stalled or failed grading call.
RECEIPT_BUSY_TIMEOUT_MS = 250

# A caller that already holds a write transaction can lend it to the receipt write,
# which makes the receipt part of that same transaction: atomic with the business
# change, never contended, never dropped. Set by
# :func:`receipt_connection` around the semantic section of such a caller.
_ACTIVE_CONNECTION: ContextVar[Any | None] = ContextVar(
    "jev_receipt_connection", default=None
)


@contextmanager
def receipt_connection(connection: Any) -> Iterator[Any]:
    """Route receipt writes made in this context onto an already-open connection.

    Use around the part of a business operation that holds a write transaction and
    makes semantic calls (assessment grading is the real case). The caller owns the
    transaction: the receipt commits with it, and rolls back with it — so the ledger
    stays consistent with the business state instead of racing it.
    """
    token = _ACTIVE_CONNECTION.set(connection)
    try:
        yield connection
    finally:
        _ACTIVE_CONNECTION.reset(token)


_INSERT_RECEIPT = """
INSERT INTO jev_decision_receipts(
    id, definition_key, primitive, mode, caller_role, owner_scope_hash,
    course_id, workspace_id, material_revision, node_id, spec_version,
    question_hash, input_hash, output_json, outcome, latency_ms,
    model_version, created_at
) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
    strftime('%Y-%m-%dT%H:%M:%fZ','now'))
"""


def _is_absent_ledger(error: sqlite3.OperationalError) -> bool:
    """Is this the receipts table simply not existing yet (migration 028 unapplied)?"""
    return "no such table" in str(error).lower()


def _receipt_row(receipt: Receipt) -> tuple[Any, ...]:
    return (
        receipt.id,
        receipt.definition_key,
        receipt.primitive,
        receipt.mode,
        receipt.caller_role,
        receipt.owner_scope_hash,
        receipt.course_id,
        receipt.workspace_id,
        receipt.material_revision,
        receipt.node_id,
        receipt.spec_version,
        receipt.question_hash,
        receipt.input_hash,
        receipt.output_json,
        receipt.outcome,
        receipt.latency_ms,
        receipt.model_version,
    )


class SqlReceiptStore:
    """Persist receipts and look up cached suggestions in the RAG database."""

    def __init__(self, database: Any, *, busy_timeout_ms: int = RECEIPT_BUSY_TIMEOUT_MS) -> None:
        self.database = database
        self.busy_timeout_ms = max(0, int(busy_timeout_ms))

    def save(self, receipt: Receipt) -> None:
        # 1. A caller that lent its open transaction: write on that connection, so the
        #    receipt is atomic with the business change and cannot contend with it.
        active = _ACTIVE_CONNECTION.get()
        if active is not None:
            try:
                active.execute(_INSERT_RECEIPT, _receipt_row(receipt))
            except sqlite3.OperationalError as error:
                # Unapplied migration: the caller's business transaction must still
                # commit, so the receipt is dropped rather than the grading failing.
                if not _is_absent_ledger(error):
                    raise
            return
        # 2. Otherwise its own connection, best-effort: a lock conflict drops the
        #    receipt rather than stalling or failing the decision.
        try:
            with self.database.connect() as connection:
                connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
                connection.execute(_INSERT_RECEIPT, _receipt_row(receipt))
        except sqlite3.OperationalError as error:
            # Another connection holds the write lock (the caller's own transaction is
            # the normal case), or the ledger table has not been migrated in yet.
            # Drop the receipt, keep the decision.
            if not _is_absent_ledger(error) and not _is_lock_conflict(error):
                raise

    def lookup(
        self,
        definition: DecisionDefinition,
        cache_scope: CacheScope,
        *,
        provider_model_version: str | None,
    ) -> dict[str, Any] | None:
        values = _scope_values(cache_scope, provider_model_version)
        columns = definition.cache_columns()
        if not columns:
            return None
        clauses = ["definition_key = ?", "outcome IN ('ok')"]
        params: list[Any] = [definition.key]
        for column in columns:
            # ``IS`` compares with ``=`` semantics but also matches NULLs, which
            # lets a partially-specified scope (e.g. no node) still participate
            # without ever colliding with a different value.
            clauses.append(f"{column} IS ?")
            params.append(values[column])
        where = " AND ".join(clauses)
        try:
            with self.database.connect() as connection:
                row = connection.execute(
                    f"SELECT output_json, model_version FROM jev_decision_receipts "
                    f"WHERE {where} ORDER BY created_at DESC, rowid DESC LIMIT 1",
                    params,
                ).fetchone()
        except sqlite3.OperationalError as error:
            # An unmigrated ledger means there is nothing to serve from cache — never
            # a reason to fail the decision that was about to be made.
            if _is_absent_ledger(error):
                return None
            raise
        if row is None:
            return None
        try:
            payload = json.loads(row["output_json"])
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        payload["model_version"] = payload.get("model_version") or row["model_version"]
        return payload

    def invalidate(
        self,
        *,
        owner_scope_hash: str | None = None,
        course_id: str | None = None,
        material_revision: str | None = None,
    ) -> int:
        """Delete receipts matching the given invalidation dimensions."""
        clauses: list[str] = []
        params: list[Any] = []
        if owner_scope_hash is not None:
            clauses.append("owner_scope_hash = ?")
            params.append(owner_scope_hash)
        if course_id is not None:
            clauses.append("course_id = ?")
            params.append(course_id)
        if material_revision is not None:
            clauses.append("material_revision = ?")
            params.append(material_revision)
        if not clauses:
            return 0
        with self.database.connect() as connection:
            cursor = connection.execute(
                f"DELETE FROM jev_decision_receipts WHERE {' AND '.join(clauses)}", params
            )
        return cursor.rowcount


def _is_lock_conflict(error: sqlite3.OperationalError) -> bool:
    """Another writer holds the database (the caller's own transaction, normally)."""
    message = str(error).lower()
    return "locked" in message or "busy" in message


def _scope_values(cache_scope: CacheScope, provider_model_version: str | None) -> dict[str, Any]:
    return {
        "owner_scope_hash": cache_scope.owner_scope_hash,
        "course_id": cache_scope.course_id,
        "workspace_id": cache_scope.workspace_id,
        "material_revision": cache_scope.material_revision,
        "node_id": cache_scope.node_id,
        "spec_version": cache_scope.spec_version,
        "question_hash": cache_scope.question_hash,
        "input_hash": cache_scope.input_hash,
        "model_version": provider_model_version,
    }
