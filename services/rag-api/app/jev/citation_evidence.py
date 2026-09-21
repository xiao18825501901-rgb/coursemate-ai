"""DocumentEvidenceResolver: the production layer-1 evidence resolver.

Module D's layer 1 — does the cited document/version/location exist, and is the
caller authorized to read it — is the backend's deterministic job and must never
cost a Jev call. This resolver answers it against the real authorized CourseMate
store, reusing the same access rules the retrieval path already enforces:

* authorization is :func:`app.learning.workspaces.can_read_document_version`
  (OFFICIAL -> accessible course; OWNER_COURSE -> owner or a public+publish
  course; WORKSPACE_PRIVATE -> owner only);
* chunk text is read through
  :meth:`app.repositories.chunks.ChunkRepository.resolve_document_chunks`, which
  uses the same ``_source_access`` scope as every other chunk query.

The resolver is strictly read-only, returns ``ok``/``missing``/``unauthorized``
(never raising on an authorization or existence problem), and bounds the text so
a semantic call can never receive an unbounded document.
"""

from __future__ import annotations

import sqlite3

from app.db import Database
from app.jev.citation_audit import ResolvedEvidence
from app.learning.workspaces import can_read_document_version
from app.repositories.chunks import ChunkRepository, RetrievalAccess

_DEFAULT_MAX_CHARS = 4000


def _scope_for(version_row: sqlite3.Row) -> str:
    if version_row["source_scope"] == "WORKSPACE_PRIVATE":
        return "mine"
    return "official"


def _narrow_chunks(chunks: list[sqlite3.Row], location: str | None) -> list[sqlite3.Row]:
    """Narrow already-authorized chunks to the narrowest locator match.

    ``location`` may be a chunk id, a ``type:value`` locator (``page:3``), or a
    section label. When it does not resolve, the whole document's chunks are
    returned rather than failing.
    """
    if location is None or not chunks:
        return list(chunks)
    by_id = [row for row in chunks if row["chunk_id"] == location]
    if by_id:
        return by_id
    if ":" in location:
        locator_type, _, locator_value = location.partition(":")
        located = [
            row
            for row in chunks
            if row["locator_type"] == locator_type and row["locator_value"] == locator_value
        ]
        return located or list(chunks)
    by_section = [
        row
        for row in chunks
        if row["section"] == location
        or (row["locator_type"] == "section" and row["locator_value"] == location)
    ]
    return by_section or list(chunks)


class DocumentEvidenceResolver:
    """EvidenceResolver over the authorized CourseMate document/chunk store."""

    def __init__(
        self,
        database: Database,
        *,
        owner_user_id: str,
        course_id: str | None = None,
        max_chars: int = _DEFAULT_MAX_CHARS,
    ) -> None:
        self.database = database
        self.owner_user_id = owner_user_id
        self.course_id = course_id
        self.max_chars = max_chars
        self._chunks = ChunkRepository(database)

    def _version(self, document_id: str, version: str | None) -> sqlite3.Row | None:
        with self.database.connect() as connection:
            if version is None:
                return connection.execute(
                    "SELECT * FROM document_versions WHERE document_id = ? "
                    "ORDER BY version DESC LIMIT 1",
                    (document_id,),
                ).fetchone()
            return connection.execute(
                "SELECT * FROM document_versions WHERE document_id = ? "
                "AND CAST(version AS TEXT) = ?",
                (document_id, version),
            ).fetchone()

    def _scoped_to_course(self, version_row: sqlite3.Row) -> bool:
        """True when the version belongs to ``self.course_id``'s authorized corpus."""
        if self.course_id is None:
            return True
        if version_row["source_scope"] in ("OFFICIAL", "OWNER_COURSE"):
            return version_row["course_id"] == self.course_id
        # WORKSPACE_PRIVATE: only this subject's own workspace corpus for the course.
        with self.database.connect() as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM learning_workspaces "
                    "WHERE course_id = ? AND owner_user_id = ? AND private_course_id = ?",
                    (self.course_id, self.owner_user_id, version_row["course_id"]),
                ).fetchone()
                is not None
            )

    def resolve(
        self, *, document_id: str, version: str | None, location: str | None
    ) -> ResolvedEvidence:
        version_row = self._version(document_id, version)
        if version_row is None:
            return ResolvedEvidence(
                status="missing", document_id=document_id, version=version, location=location
            )
        if not self._scoped_to_course(version_row):
            return ResolvedEvidence(
                status="unauthorized",
                document_id=document_id,
                version=version,
                location=location,
                text="",
            )
        if not can_read_document_version(self.database, version_row, self.owner_user_id):
            return ResolvedEvidence(
                status="unauthorized",
                document_id=document_id,
                version=version,
                location=location,
                text="",
            )

        chunks = self._chunks.resolve_document_chunks(
            version_row["course_id"],
            document_id,
            access=RetrievalAccess(self.owner_user_id, _scope_for(version_row)),
            version=str(version_row["version"]),
        )
        selected = _narrow_chunks(chunks, location)
        text = "\n\n".join(str(row["content"]) for row in selected)
        if len(text) > self.max_chars:
            text = text[: self.max_chars]
        span_id = selected[0]["chunk_id"] if len(selected) == 1 else document_id
        return ResolvedEvidence(
            status="ok",
            document_id=document_id,
            version=str(version_row["version"]),
            location=location,
            text=text,
            span_id=span_id,
        )
