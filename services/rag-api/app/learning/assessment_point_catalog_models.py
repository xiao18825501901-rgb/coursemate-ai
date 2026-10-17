"""Model proposals and server-only verified point projections are distinct."""

from typing import Annotated, Literal

from pydantic import Field, StrictBool

from app.learning.models import Contract, Identifier
from app.learning.question_blueprint import Hex64

NonemptyText = Annotated[str, Field(min_length=1, max_length=6000)]
CanonicalKey = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_.-]{1,200}$")]
ReceiptId = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_:-]{1,200}$")]
ScopeKey = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_:-]{1,400}$")]
ItemForm = Literal["MCQ_SINGLE", "NUMERIC", "SHORT_TEXT", "EXPLANATION", "CODE"]


class SourceRef(Contract):
    source_id: Identifier
    document_id: Identifier
    document_version: Identifier
    locator: str = Field(min_length=1, max_length=1024)


class VerifiedSourceRef(SourceRef):
    scope_key: ScopeKey


class PointDefinition(Contract):
    point_id: Identifier
    canonical_key: CanonicalKey
    objective: str = Field(min_length=1, max_length=6000)
    constraints: list[NonemptyText]
    scoring_evidence: list[NonemptyText] = Field(min_length=1)
    allowed_forms: list[ItemForm] = Field(min_length=1)
    sequence: int = Field(ge=0, strict=True)


class CandidatePoint(PointDefinition):
    source_refs: list[SourceRef] = Field(min_length=1)
    target_item_ids: list[Identifier] = Field(min_length=1)


class PointCompileCandidate(Contract):
    points: list[CandidatePoint]


class EvidenceQuote(Contract):
    source_id: Identifier
    quote: str = Field(min_length=1, max_length=6000)


class ReviewedPoint(Contract):
    point_id: Identifier
    canonical_key: CanonicalKey
    target_item_ids: list[Identifier] = Field(min_length=1)
    supported: StrictBool
    observable: StrictBool
    scorable: StrictBool
    conditions_preserved: StrictBool
    reason: str = Field(min_length=1, max_length=2000)
    evidence_quotes: list[EvidenceQuote] = Field(min_length=1)


class PointCatalogReview(Contract):
    source_snapshot: Hex64
    candidate_hash: Hex64
    points: list[ReviewedPoint]
    covered_target_item_ids: list[Identifier]
    deduplicated: StrictBool


class VerifiedPoint(PointDefinition):
    source_refs: list[VerifiedSourceRef] = Field(min_length=1)
    validation_receipt_id: ReceiptId
    status: Literal["VERIFIED"] = "VERIFIED"
    weight: Literal[1] = 1
    weight_receipt_id: None = None


class CatalogScope(Contract):
    owner_id: Identifier
    course_id: Identifier
    node_id: Identifier
    spec_version: Identifier
    source_snapshot: Hex64


class VerifiedCatalog(Contract):
    catalog_id: ReceiptId
    version: Literal["cj.assessment.points.v1"] = "cj.assessment.points.v1"
    scope: CatalogScope
    points: list[VerifiedPoint] = Field(min_length=1)
    validation_receipt_id: ReceiptId
