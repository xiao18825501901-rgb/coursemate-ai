"""SQLite persistence for Jev decision receipts and the suggestion cache.

A receipt is written once per call (including failed calls, with an outcome).
Cache lookup honours the catalog ``cache_scope``: it only returns a suggestion
when every dimension in scope matches — authorization scope (owner scope hash),
course, workspace, material revision, node/spec, question definition hash, input
hash and provider model version — so a material-revision change or an
authorization change is a natural miss and :meth:`invalidate` can also delete
explicitly.
"""

from __future__ import annotations

import json
from typing import Any

from app.jev.catalog import DecisionDefinition
from app.jev.gateway import Receipt
from app.jev.models import CacheScope


class SqlReceiptStore:
    """Persist receipts and look up cached suggestions in the RAG database."""

    def __init__(self, database: Any) -> None:
        self.database = database

    def save(self, receipt: Receipt) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO jev_decision_receipts(
                    id, definition_key, primitive, mode, caller_role, owner_scope_hash,
                    course_id, workspace_id, material_revision, node_id, spec_version,
                    question_hash, input_hash, output_json, outcome, latency_ms,
                    model_version, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                    strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                """,
                (
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
                ),
            )

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
        with self.database.connect() as connection:
            row = connection.execute(
                f"SELECT output_json, model_version FROM jev_decision_receipts "
                f"WHERE {where} ORDER BY created_at DESC, rowid DESC LIMIT 1",
                params,
            ).fetchone()
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
