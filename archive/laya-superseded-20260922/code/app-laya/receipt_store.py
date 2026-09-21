"""SQLite persistence for Laya decision receipts and the suggestion cache.

A receipt is written once per decision (successful OR failed, with an outcome) so
every transport hit is auditable: ``provider="laya"``, model revision, definition
id + version, compiler version, calibration version, mode, the cache-scope keys
(authorization scope, course, workspace, material revision, node/spec, question
definition hash, input hash and model revision), latency and the outcome.

Cache lookup honours the same cache-scope dimensions as the retired Jev layer: it
only returns a suggestion when every dimension in scope matches, so a
material-revision change or an authorization change is a natural miss. Historical
``jev_decision_receipts`` rows are untouched and stay readable.
"""

from __future__ import annotations

import json
from typing import Any

from app.laya.adapter import LayaReceipt
from app.laya.models import LayaScope

# The Laya cache-scope entries map onto receipt columns. The provider-model-version
# dimension is the Laya ``model_revision`` (vs the Jev ``model_version`` column).
_CACHE_SCOPE_COLUMNS: dict[str, tuple[str, ...]] = {
    "authorization_scope": ("owner_scope_hash",),
    "course": ("course_id",),
    "workspace": ("workspace_id",),
    "material_revision": ("material_revision",),
    "node_spec_version": ("node_id", "spec_version"),
    "question_definition_hash": ("question_hash",),
    "input_hash": ("input_hash",),
    "provider_model_version": ("model_revision",),
}

# The catalog definitions live in app.jev.catalog; replicate the cache_scope order
# so lookups match the jev cache_columns() projection with model_revision.
_DEFAULT_SCOPE_ORDER = (
    "authorization_scope",
    "course",
    "workspace",
    "material_revision",
    "node_spec_version",
    "question_definition_hash",
    "input_hash",
    "provider_model_version",
)


class SqlLayaReceiptStore:
    """Persist receipts and look up cached suggestions in the RAG database."""

    def __init__(self, database: Any) -> None:
        self.database = database

    def save(self, receipt: LayaReceipt) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO laya_decision_receipts(
                    id, provider, definition_id, definition_version, model_revision,
                    compiler_version, calibration_version, temperature, mode, outcome,
                    owner_scope_hash, course_id, workspace_id, material_revision, node_id,
                    spec_version, question_hash, input_hash, output_json, latency_ms,
                    created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                    strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                """,
                (
                    receipt.id,
                    "laya",
                    receipt.definition_id,
                    receipt.definition_version,
                    receipt.model_revision,
                    receipt.compiler_version,
                    receipt.calibration_version,
                    receipt.temperature,
                    receipt.mode,
                    receipt.outcome,
                    receipt.owner_scope_hash,
                    receipt.course_id,
                    receipt.workspace_id,
                    receipt.material_revision,
                    receipt.node_id,
                    receipt.spec_version,
                    receipt.question_hash,
                    receipt.input_hash,
                    receipt.output_json,
                    receipt.latency_ms,
                ),
            )

    def lookup(
        self, definition_id: str, scope: LayaScope, *, model_revision: str
    ) -> dict[str, Any] | None:
        columns = self._cache_columns()
        values = {
            "owner_scope_hash": scope.owner_scope_hash,
            "course_id": scope.course_id,
            "workspace_id": scope.workspace_id,
            "material_revision": scope.material_revision,
            "node_id": scope.node_id,
            "spec_version": scope.spec_version,
            "question_hash": scope.question_hash,
            "input_hash": scope.input_hash,
            "model_revision": model_revision,
        }
        clauses = ["definition_id = ?", "outcome = 'ok'"]
        params: list[Any] = [definition_id]
        for column in columns:
            clauses.append(f"{column} IS ?")
            params.append(values[column])
        where = " AND ".join(clauses)
        with self.database.connect() as connection:
            row = connection.execute(
                f"SELECT output_json, model_revision FROM laya_decision_receipts "
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
        payload["model_revision"] = payload.get("model_revision") or row["model_revision"]
        return payload

    @staticmethod
    def _cache_columns() -> tuple[str, ...]:
        columns: list[str] = []
        for entry in _DEFAULT_SCOPE_ORDER:
            columns.extend(_CACHE_SCOPE_COLUMNS.get(entry, ()))
        return tuple(dict.fromkeys(columns))
