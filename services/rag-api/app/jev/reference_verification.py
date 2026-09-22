"""Module A (ExtractionVerification) wired to a real business surface.

The query-reference parser reads a question number and sub-part out of the
learner's own message, and that label does not stay a hint: it becomes a **hard
exact-locator filter** (``json_extract(metadata_json,'$.question_number') = ?``)
that runs *before* similarity search, in both the official and the learner's
private scope, and its hits are placed at the head of the candidate list. So a
label that was invented or mis-read silently pins retrieval onto the wrong
sub-question — the opposite of the exactness the locator exists to provide.

This module puts the extraction pipeline between that parser and every consumer:

1. **deterministic first** — the label's shape, the presence of a locator, and
   the authority of its source are checked in code. A label that fails is dropped
   without any model call;
2. **Jev on the residue** — only over the learner's own message text: is this
   token actually a reference to that question, or is it prose, a negated
   reference ("it is not question 3, it is 4"), or a value read from the wrong
   field? The judgment goes through ``callsites.verify_extraction_field``;
3. **bounded field-level disposal** — an affirmatively defective label is dropped
   from the reference (the only repair on this surface: retrieval then falls back
   to hybrid search, which is the documented safe path). Nothing is rewritten.

Authority boundary (rule 8). Dropping a label can only ever *remove* a filter, so
this module can never widen what the learner may read; it cannot grant a course
permission, cannot add a source, and cannot make an unauthorized chunk reachable.
The opposite operation — inventing a label to reach material — is exactly what the
deterministic layer forbids.

Honest scope note. Unlike a document extraction there is no image here: the
supplied text *is* the source (the learner's message), not a transcription of it,
so "a model agreeing with its own transcription" cannot occur on this surface. What
remains genuinely semantic — negation, wrong field, insufficient context — is what
the Jev candidate set covers.

Degradation (rule 7). ``off``/``shadow``/no-service/timeout keep the deterministic
result unchanged and only record a receipt; a label is dropped only for a
deterministic failure or an affirmative Jev defect. So a deployment that has not
been calibrated behaves exactly as before, and the receipts show what an enabled
decision would have done.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.jev.extraction import (
    ExtractionRecord,
    ExtractionVerifier,
    RecordRole,
    Status,
    Verdict,
)
from app.jev.gateway import JevGateway
from app.jev.models import CacheScope, owner_scope_hash
from app.jev.service import SemanticDecisionService
from app.tutor.references import QueryReference, normalize_query

# The label produced by the query-reference parser is a *query* label, not course
# material: its source is the learner's own message.
QUERY_REFERENCE_SOURCE = "query"
QUERY_REFERENCE_VERSION = "1.0.0"
QUERY_EXTRACTION_VERSION = "query-reference-1.0.0"

# This surface's label shapes. A question number here is digits (optionally
# Q-prefixed) or a roman numeral, because ``app.rag.structure`` writes either form
# into chunk metadata and the locator must match it verbatim; a sub-part is a
# single letter or a multi-digit number (``Question 3(2)``).
QUERY_QUESTION_ID_PATTERN = r"^(?:[Qq]?[0-9]+|[IVXLCDM]+)$"
QUERY_PART_PATTERN = r"^(?:[a-z]|[0-9]+)$"

# The two labels that are verified. ``document``/``document_kind``/
# ``document_number`` are deliberately not: they are literal substrings of an
# explicit filename the learner typed ("assignment_2.pdf"), not semantic guesses
# about prose, and dropping them would discard an unambiguous locator.
QUESTION_NUMBER_FIELD = "question_number"
QUESTION_PART_FIELD = "question_part"
VERIFIED_FIELDS = (QUESTION_NUMBER_FIELD, QUESTION_PART_FIELD)

# A verdict that affirmatively says the label is wrong. Only these drop a locator;
# SOURCE_INSUFFICIENT and UNCERTAIN are surfaced as review instead of acted on.
DEFECT_VERDICTS = frozenset(
    {
        Verdict.WRONG_FIELD,
        Verdict.NEGATION_LOST,
        Verdict.CONSTRAINT_LOST,
        Verdict.SOURCE_INSUFFICIENT,
    }
)


class QueryTextSourceRegistry:
    """The learner's own message is the source of a query label.

    It is treated as in scope for every course because it is not course material:
    it carries no material rights, so authorizing it cannot widen anyone's access.
    Any other source id is unknown here, and the deterministic layer rejects it.
    """

    def source_exists(self, source_id: str) -> bool:
        return source_id == QUERY_REFERENCE_SOURCE

    def source_in_scope(self, source_id: str, *, course_scope: str) -> bool:
        del course_scope  # a query label has no course-material rights to check
        return source_id == QUERY_REFERENCE_SOURCE


@dataclass(frozen=True)
class FieldVerification:
    """The disposition of one label, with what an operator needs to audit it."""

    field: str
    value: str
    status: str
    verdict: str | None
    path: str
    fallback_reason: str | None
    receipt_id: str | None
    used_jev: bool
    trusted: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "value": self.value,
            "status": self.status,
            "verdict": self.verdict,
            "path": self.path,
            "fallback_reason": self.fallback_reason,
            "receipt_id": self.receipt_id,
            "used_jev": self.used_jev,
            "trusted": self.trusted,
        }


@dataclass(frozen=True)
class ReferenceVerification:
    """The reference a caller may actually use, plus why it differs."""

    reference: QueryReference
    fields: tuple[FieldVerification, ...] = ()
    dropped: tuple[str, ...] = ()
    jev_calls: int = 0

    @property
    def questioned(self) -> bool:
        """Was a question label present at all (and therefore judged)?"""
        return bool(self.fields)

    @property
    def needs_review(self) -> tuple[str, ...]:
        """Labels kept but not confirmed — surfaced, never silently acted on."""
        return tuple(
            field.field
            for field in self.fields
            if field.status == Status.NEEDS_REVIEW.value
        )

    @property
    def blocked(self) -> bool:
        """Did verification drop anything (i.e. did it change retrieval)?"""
        return bool(self.dropped)

    def as_dict(self) -> dict[str, Any]:
        return {
            "questioned": self.questioned,
            "fields": [field.as_dict() for field in self.fields],
            "dropped": list(self.dropped),
            "needs_review": list(self.needs_review),
            "jev_calls": self.jev_calls,
        }


def reference_records(
    query: str,
    reference: QueryReference,
) -> tuple[ExtractionRecord, ...]:
    """One extraction record per present question label.

    There is no model call here and no new parsing: the record is a projection of
    what the deterministic parser already produced, carrying the label, the
    learner's own (normalized) message as its supplied text, and the character span
    it was read from as its locator.
    """
    normalized = normalize_query(query)
    span = reference.question_span
    region = normalized[span[0] : span[1]] if span is not None else None
    records: list[ExtractionRecord] = []
    if reference.question_number is not None:
        records.append(
            _record(
                normalized=normalized,
                span=span,
                region=region,
                question_id=reference.question_number,
                part_id=reference.question_part,
                field_name=QUESTION_NUMBER_FIELD,
                value=reference.question_number,
            )
        )
    if reference.question_part is not None:
        if reference.question_number is None:
            # A sub-part with no question number is not a locator at all; there is
            # nothing to verify against and nothing safe to filter on.
            return tuple(records)
        records.append(
            _record(
                normalized=normalized,
                span=span,
                region=region,
                question_id=reference.question_number,
                part_id=reference.question_part,
                field_name=QUESTION_PART_FIELD,
                value=reference.question_part,
            )
        )
    return tuple(records)


def _record(
    *,
    normalized: str,
    span: tuple[int, int] | None,
    region: str | None,
    question_id: str,
    part_id: str | None,
    field_name: str,
    value: str,
) -> ExtractionRecord:
    return ExtractionRecord(
        source_id=QUERY_REFERENCE_SOURCE,
        source_version=QUERY_REFERENCE_VERSION,
        page=None,
        region=region,
        span=span,
        question_id=question_id,
        part_id=part_id,
        field_name=field_name,
        candidate_value=value,
        unit=None,
        uncertainty=None,
        extraction_version=QUERY_EXTRACTION_VERSION,
        supplied_text=normalized,
        role=RecordRole.SOURCE,
    )


def build_verifier(
    service: SemanticDecisionService | None,
    *,
    gateway: JevGateway | None = None,
) -> ExtractionVerifier:
    """The module-A verifier configured for this surface's label shapes.

    ``service`` is the production route (through the business call site);
    ``gateway`` is for a standalone or offline run. Exactly one of them is used,
    and with neither the deterministic path is all that runs.

    ``repair_budget`` is one allowance per label this surface can ever carry. The
    budget is not a model-call budget here — nothing is re-read — but the module
    spends it to bound how often one slot may be re-planned, so a shared budget of
    one would leave the second label unplanned and looking confirmed.
    """
    return ExtractionVerifier(
        service=service,
        gateway=gateway,
        source_registry=QueryTextSourceRegistry(),
        repair_budget=len(VERIFIED_FIELDS),
        question_number_pattern=QUERY_QUESTION_ID_PATTERN,
        part_number_pattern=QUERY_PART_PATTERN,
    )


def verify_query_reference(
    query: str,
    reference: QueryReference,
    *,
    service: SemanticDecisionService | None,
    owner_user_id: str,
    authorization_scope: str = "official",
    course_id: str | None = None,
    verifier: ExtractionVerifier | None = None,
) -> ReferenceVerification:
    """Verify a parsed reference's question labels and return a usable reference.

    A message with no question label costs **zero** model calls: the whole feature
    is skipped, so ordinary teaching questions are untouched. When a label is
    present it is judged once, and only an affirmative defect (deterministic
    failure, or a Jev ``WRONG_FIELD``/``NEGATION_LOST``/``CONSTRAINT_LOST``/
    ``SOURCE_INSUFFICIENT``) removes it. Everything else keeps the deterministic
    reference exactly as it was.

    ``owner_user_id`` and ``authorization_scope`` are required because they are
    what make the judgment's cache entry owner-scoped: a signature that let a
    caller forget them would let one learner's private-scope judgment be served to
    another (§7).
    """
    records = reference_records(query, reference)
    if not records:
        return ReferenceVerification(reference=reference)

    active = verifier or build_verifier(service)
    if active.source_registry is None:
        # Without a registry every record fails the source check and would be
        # silently dropped, which would look like a clean verification. Refuse.
        raise ValueError(
            "an extraction verifier for query references needs a source registry; "
            "build it with build_verifier() or pass one explicitly"
        )
    scope = _scope(
        owner_user_id=owner_user_id,
        authorization_scope=authorization_scope,
        course_id=course_id,
    )

    fields: list[FieldVerification] = []
    dropped: list[str] = []
    jev_calls = 0
    for record in records:
        result = active.verify(record, cache_scope=scope, course_scope=course_id or "")
        jev_calls += result.jev_calls
        verdict = result.verdict.value if result.verdict is not None else None
        trusted = _trusted(result)
        fields.append(
            FieldVerification(
                field=record.field_name,
                value=str(record.candidate_value),
                status=result.status.value,
                verdict=verdict,
                path=result.path,
                fallback_reason=(
                    result.fallback_reason.value if result.fallback_reason is not None else None
                ),
                receipt_id=result.receipt_id,
                used_jev=result.used_jev,
                trusted=trusted,
            )
        )
        if not trusted:
            dropped.append(record.field_name)

    return ReferenceVerification(
        reference=_narrow(reference, dropped),
        fields=tuple(fields),
        dropped=tuple(dropped),
        jev_calls=jev_calls,
    )


def _trusted(result: Any) -> bool:
    """May this label stay a hard exact-locator filter?

    The rule is verdict-driven rather than status-driven on purpose. A verdict of
    ``WRONG_FIELD``/``NEGATION_LOST``/``CONSTRAINT_LOST``/``SOURCE_INSUFFICIENT``
    is a real answer from an enabled decision, whether or not the module went on to
    plan a repair; reading only the status would let an exhausted repair allowance
    leave a label the model called wrong in place as a filter. Dropping is the
    conservative direction (retrieval falls back to hybrid search), and nothing
    downstream may re-add the label.
    """
    if result.status is Status.REJECTED:
        return False  # a deterministic check failed: the label is not well formed
    # A verdict outside the defect set — including no verdict at all — keeps the
    # deterministic reference exactly as it was.
    return result.verdict not in DEFECT_VERDICTS


def _narrow(reference: QueryReference, dropped: list[str]) -> QueryReference:
    """Drop exactly the untrusted labels, and nothing else."""
    if not dropped:
        return reference
    number = None if QUESTION_NUMBER_FIELD in dropped else reference.question_number
    # A sub-part whose parent question is untrusted is not trustworthy on its own:
    # filtering on "part b" across every question is not the reference the learner
    # wrote, so it goes with the number.
    part = (
        None
        if number is None or QUESTION_PART_FIELD in dropped
        else reference.question_part
    )
    return QueryReference(
        document=reference.document,
        document_kind=reference.document_kind,
        document_number=reference.document_number,
        question_number=number,
        question_part=part,
        page_number=reference.page_number,
        slide_number=reference.slide_number,
        question_span=reference.question_span if number is not None else None,
    )


def _scope(
    *,
    owner_user_id: str,
    authorization_scope: str,
    course_id: str | None,
) -> CacheScope:
    """The cache scope for this judgment: always derived from the caller.

    This is deliberately *not* taken from the decision service. The scope is a
    property of whose authority the judgment was made under, so deriving it from
    the transport would make it depend on how the call is wired — and a run with no
    service object would fall back to one shared server-internal scope, which is
    exactly how one learner's answer could be served to another.
    """
    return CacheScope(
        owner_scope_hash=owner_scope_hash(owner_user_id, authorization_scope),
        course_id=course_id,
    )


__all__ = [
    "DEFECT_VERDICTS",
    "FieldVerification",
    "QUERY_EXTRACTION_VERSION",
    "QUERY_PART_PATTERN",
    "QUERY_QUESTION_ID_PATTERN",
    "QUERY_REFERENCE_SOURCE",
    "QUERY_REFERENCE_VERSION",
    "QUESTION_NUMBER_FIELD",
    "QUESTION_PART_FIELD",
    "QueryTextSourceRegistry",
    "ReferenceVerification",
    "VERIFIED_FIELDS",
    "build_verifier",
    "reference_records",
    "verify_query_reference",
]
