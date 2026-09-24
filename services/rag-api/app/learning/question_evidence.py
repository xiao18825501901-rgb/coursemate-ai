"""Question Engine stage 2: a bounded, authorised pack of objective evidence.

The Teaching Spec already selected the evidence for an objective.  This stage does not run a
broader retrieval or substitute a relevant-looking course chunk when that evidence is missing: it
resolves exactly those chunk ids, pins their immutable document versions, rechecks the canonical
document ACL, and refuses with ``SOURCE_INSUFFICIENT`` when any cited source is unavailable.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Annotated, Final, Literal, cast

from pydantic import Field, StringConstraints, model_validator

from app.db import Database
from app.learning.models import Contract, Identifier, Text
from app.learning.question_blueprint import Hex64, SourceScopeEntry, TeachingObjective
from app.learning.workspaces import can_read_document_version

SCHEMA_VERSION: Final = "question-evidence-pack.v1"
DEFAULT_EXCERPT_LIMIT: Final = 2500

SourceKind = Literal["OFFICIAL", "OWNER_COURSE", "WORKSPACE_PRIVATE"]
Excerpt = Annotated[str, StringConstraints(min_length=1, max_length=6000)]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=255)]


class EvidencePackError(RuntimeError):
    """A stable refusal from evidence preparation, before any provider call."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = "SOURCE_INSUFFICIENT"


@dataclass(frozen=True)
class EvidencePackAccess:
    """The two course scopes of one already-authorised learning workspace."""

    owner_user_id: str
    course_id: str
    private_course_id: str

    def __post_init__(self) -> None:
        if not self.owner_user_id or not self.course_id or not self.private_course_id:
            raise ValueError("evidence access requires owner, course and private-course ids")
        if self.course_id == self.private_course_id:
            raise ValueError("the workspace course and private course must be different")


class EvidenceFragment(Contract):
    evidence_id: Identifier
    document_id: Identifier
    document_version_id: Identifier
    document_version: int = Field(ge=1)
    document_sha256: Hex64
    filename: ShortText
    source_scope: SourceKind
    ordinal: int = Field(ge=0)
    locator_type: ShortText
    locator_value: ShortText
    section: Annotated[str, StringConstraints(max_length=500)] | None = None
    content: Excerpt
    truncated: bool
    source_content_sha256: Hex64
    excerpt_sha256: Hex64

    @property
    def locator(self) -> str:
        return f"{self.locator_type}:{self.locator_value}"


class QuestionEvidencePack(Contract):
    schema_version: Literal["question-evidence-pack.v1"] = SCHEMA_VERSION
    course_id: Identifier
    node_id: Identifier
    spec_version: int = Field(ge=1)
    spec_content_hash: Hex64
    objective_id: Identifier
    objective_text: Text
    acceptance: Text
    evidence_ids: list[Identifier] = Field(min_length=1, max_length=20)
    fragments: list[EvidenceFragment] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def exact_scope(self) -> QuestionEvidencePack:
        fragment_ids = [fragment.evidence_id for fragment in self.fragments]
        if fragment_ids != self.evidence_ids:
            raise ValueError("evidence fragments must exactly match the declared evidence ids")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("evidence ids must be unique")
        return self

    def source_scope(self) -> list[SourceScopeEntry]:
        """Project the exact fragments into the blueprint's immutable source scope."""
        return [
            SourceScopeEntry(
                document_id=fragment.document_id,
                version=fragment.document_version,
                locator=fragment.locator,
                content_hash=fragment.document_sha256,
            )
            for fragment in self.fragments
        ]

    def identity(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


def _refuse(evidence_id: str, reason: str) -> EvidencePackError:
    return EvidencePackError(f"cited evidence {evidence_id!r} is unavailable: {reason}")


def _source_kind_matches_workspace(row: sqlite3.Row, access: EvidencePackAccess) -> bool:
    course_id = cast(str, row["course_id"])
    source_scope = cast(str, row["source_scope"])
    if course_id == access.course_id:
        return source_scope in {"OFFICIAL", "OWNER_COURSE"}
    if course_id == access.private_course_id:
        return source_scope == "WORKSPACE_PRIVATE"
    return False


def build_evidence_pack(
    database: Database,
    *,
    objective: TeachingObjective,
    access: EvidencePackAccess,
    excerpt_limit: int = DEFAULT_EXCERPT_LIMIT,
) -> QuestionEvidencePack:
    """Resolve and authorise exactly the chunks cited by ``objective``.

    No model or embedding call is made here.  There is also no fallback retrieval: a missing,
    revoked, cross-course or cross-user citation makes the pack insufficient and therefore stops
    question generation before it can spend money or invent evidence.
    """
    if excerpt_limit < 1 or excerpt_limit > 6000:
        raise ValueError("excerpt_limit must be between 1 and 6000 characters")
    evidence_ids = list(objective.evidence_ids)
    if not evidence_ids:
        raise EvidencePackError("the teaching objective cites no evidence")
    if len(evidence_ids) != len(set(evidence_ids)):
        raise EvidencePackError("the teaching objective contains duplicate evidence ids")

    fragments: list[EvidenceFragment] = []
    for evidence_id in evidence_ids:
        with database.connect() as connection:
            row = connection.execute(
                "SELECT version.*,chunk.id AS evidence_id,chunk.ordinal AS chunk_ordinal,"
                "chunk.content AS chunk_content,chunk.locator_type AS chunk_locator_type,"
                "chunk.locator_value AS chunk_locator_value,chunk.section AS chunk_section "
                "FROM chunks AS chunk JOIN chunk_source_versions AS source "
                "ON source.chunk_id=chunk.id JOIN document_versions AS version "
                "ON version.id=source.document_version_id WHERE chunk.id=?",
                (evidence_id,),
            ).fetchone()
            if row is None:
                raise _refuse(evidence_id, "no immutable chunk/version binding")
            statuses = {
                str(status["status"])
                for status in connection.execute(
                    "SELECT status FROM material_evidence WHERE node_id=? AND chunk_id=? "
                    "AND document_version_id=?",
                    (objective.node_id, evidence_id, row["id"]),
                ).fetchall()
            }

        if not _source_kind_matches_workspace(row, access):
            raise _refuse(evidence_id, "outside the workspace source scope")
        if not can_read_document_version(database, row, access.owner_user_id):
            raise _refuse(evidence_id, "not authorised for this learner")
        if "REVOKED" in statuses and "ACTIVE" not in statuses:
            raise _refuse(evidence_id, "the material evidence was revoked")

        full_content = cast(str, row["chunk_content"])
        excerpt = full_content[:excerpt_limit]
        if not excerpt.strip():
            raise _refuse(evidence_id, "the cited chunk contains no usable text")
        fragments.append(
            EvidenceFragment(
                evidence_id=evidence_id,
                document_id=cast(str, row["document_id"]),
                document_version_id=cast(str, row["id"]),
                document_version=int(row["version"]),
                document_sha256=cast(str, row["sha256"]),
                filename=cast(str, row["filename"]),
                source_scope=cast(SourceKind, row["source_scope"]),
                ordinal=int(row["chunk_ordinal"]),
                locator_type=cast(str, row["chunk_locator_type"]),
                locator_value=cast(str, row["chunk_locator_value"]),
                section=cast(str | None, row["chunk_section"]),
                content=excerpt,
                truncated=len(excerpt) < len(full_content),
                source_content_sha256=hashlib.sha256(full_content.encode()).hexdigest(),
                excerpt_sha256=hashlib.sha256(excerpt.encode()).hexdigest(),
            )
        )

    return QuestionEvidencePack(
        course_id=access.course_id,
        node_id=objective.node_id,
        spec_version=objective.spec_version,
        spec_content_hash=objective.spec_content_hash,
        objective_id=objective.item_id,
        objective_text=objective.objective,
        acceptance=objective.acceptance,
        evidence_ids=evidence_ids,
        fragments=fragments,
    )
