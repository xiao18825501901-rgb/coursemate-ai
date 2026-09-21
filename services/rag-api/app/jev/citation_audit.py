"""ClaimCitationAudit: the single citation audit service (cases 4 + 10 merged).

One service replaces the two historical citation cases, reusing the existing
``source.supports_claim.v1`` and ``source.select_span.v1`` definitions — there is
**no second citation service** and no new citation definition.

Three layers, of which only the third is semantic::

    1. existence + authorization  (deterministic — backend owns permissions/locator)
    2. quoted text/number exists   (deterministic — whitespace-only normalization)
    3. evidence supports the claim (semantic — source.supports_claim.v1 + select_span)

Verdict labels::

    SUPPORTED                          evidence supports the specific claim
    PARTIALLY_SUPPORTED                supports part of the claim
    CONTRADICTED                       a direct (numeric/inequality) contradiction
    NOT_ADDRESSED_IN_AVAILABLE_EVIDENCE the fragment does not address the claim
    INSUFFICIENT_CONTEXT               not enough context to judge
    REJECTED                           layer-1 failure (missing / unauthorized)

Guarantees:

* ``"the available fragment does not mention it"`` is reported as
  ``NOT_ADDRESSED_IN_AVAILABLE_EVIDENCE`` — never as "the whole document disproves
  it" (``CONTRADICTED`` requires a direct value conflict).
* ``"the quote exists"`` is never reported as "the claim is correct": layer 2 only
  gates passage to layer 3; ``SUPPORTED`` requires a real Jev support signal.
* Jev never invents a page, quotation or URL: span/document ids come from the
  backend resolver, and ``source.select_span.v1`` may only select from the
  backend-supplied span ids.
* Matching normalizes whitespace in a traceable way and never erases a sign, an
  inequality, a number or a unit: ``5%`` and ``5 percentage points`` are not the
  same number.
* Streaming teaching shows nothing as verified before it is checked
  (``is_verified`` is True only for a real Jev ``SUPPORTED``); the audit binds to
  the fixed message revision (``document_id`` + ``version``); a problem appends a
  correction or a new version instead of silently rewriting history (caller
  contract). High-impact material (reference solutions, grading rationale) is
  verified before the result is finalized (see :func:`is_definitive`).
* Verification is against the current course material only: no external web
  fetch, and a link inside a document is never turned into an arbitrary URL
  reader.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from app.jev.models import CacheScope
from app.jev.service import DecisionResult, SemanticDecisionService

SUPPORTED = "SUPPORTED"
PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
CONTRADICTED = "CONTRADICTED"
NOT_ADDRESSED_IN_AVAILABLE_EVIDENCE = "NOT_ADDRESSED_IN_AVAILABLE_EVIDENCE"
INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"
REJECTED = "REJECTED"

LABELS = (
    SUPPORTED,
    PARTIALLY_SUPPORTED,
    CONTRADICTED,
    NOT_ADDRESSED_IN_AVAILABLE_EVIDENCE,
    INSUFFICIENT_CONTEXT,
)

_SUPPORTED_THRESHOLD = 0.75
_PARTIAL_THRESHOLD = 0.5

# Number-with-unit assertions used for the deterministic contradiction check.
# The unit is required, so a bare integer is never used to "prove" a conflict.
_NUMBER = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*"
    r"(%|percent|percentage\s+points?|个百分点|百分点|km|m/s|ms|kg|℃|°C|°F|m|s)",
    re.I,
)


def _canonical_unit(unit: str) -> str:
    normalized = unit.casefold().strip()
    if normalized in {"%", "percent"}:
        return "percent"
    if normalized in {"percentage points", "percentage point", "个百分点", "百分点"}:
        return "percentage_points"
    return normalized


def normalize_whitespace(text: str) -> str:
    """Collapse whitespace runs to single spaces (traceable, reversible in spirit).

    Only Unicode whitespace is touched; a sign, an inequality, a number and a unit
    all survive verbatim, so ``5 %`` and ``5%`` stay distinct literals and a
    comparison never erases ``%`` or ``>=``.
    """
    return " ".join(text.split())


@dataclass(frozen=True)
class QuoteMatch:
    """Layer-2 result: does the quoted text/number exist in the document?"""

    matched: bool
    normalized_quote: str


def quote_exists(quote: str, text: str) -> QuoteMatch:
    """Deterministic substring existence after whitespace-only normalization.

    A traceable match: both sides are whitespace-normalized and then the normalized
    quote must appear as a literal substring. Units and signs are preserved, so
    ``5%`` and ``5 percentage points`` can never match each other.
    """
    normalized = normalize_whitespace(quote)
    return QuoteMatch(matched=normalized in normalize_whitespace(text), normalized_quote=normalized)


def _numeric_assertions(text: str) -> dict[str, set[float]]:
    assertions: dict[str, set[float]] = {}
    for number, unit in _NUMBER.findall(text):
        key = _canonical_unit(unit)
        assertions.setdefault(key, set()).add(float(number))
    return assertions


def _numeric_contradiction(claim: str, evidence_text: str) -> bool:
    """Deterministic (unit-aware) contradiction: same quantity, different value.

    Only numbers carrying a unit are compared, and only across the *same*
    canonical unit. ``5%`` vs ``5 percentage points`` differ in unit and are never
    a contradiction; a bare integer is never treated as proof of conflict.
    """
    claim_assertions = _numeric_assertions(claim)
    evidence_assertions = _numeric_assertions(evidence_text)
    for unit, claim_values in claim_assertions.items():
        evidence_values = evidence_assertions.get(unit)
        if evidence_values is None:
            continue
        for value in claim_values:
            for evidence_value in evidence_values:
                if value != evidence_value:
                    return True
    return False


@dataclass(frozen=True)
class ResolvedEvidence:
    """The backend-resolved document/version/location (layer 1)."""

    status: str  # "ok" | "missing" | "unauthorized"
    document_id: str
    version: str | None = None
    location: str | None = None
    text: str = ""
    span_id: str | None = None


class EvidenceResolver(Protocol):
    """Ask the deterministic backend for authorized evidence (never a network fetch)."""

    def resolve(
        self, *, document_id: str, version: str | None, location: str | None
    ) -> ResolvedEvidence:
        """Return the authorized fragment, or ``missing``/``unauthorized``."""


class StaticEvidenceResolver:
    """In-memory resolver for tests and offline flows (the backend shim)."""

    def __init__(self, documents: dict[str, str], *, authorized: set[str] | None = None) -> None:
        self.documents = documents
        self.authorized = set(authorized) if authorized is not None else set(documents)

    def resolve(
        self, *, document_id: str, version: str | None, location: str | None
    ) -> ResolvedEvidence:
        if document_id not in self.documents:
            return ResolvedEvidence(
                status="missing", document_id=document_id, version=version, location=location
            )
        if document_id not in self.authorized:
            return ResolvedEvidence(
                status="unauthorized", document_id=document_id, version=version, location=location
            )
        return ResolvedEvidence(
            status="ok",
            document_id=document_id,
            version=version,
            location=location,
            text=self.documents[document_id],
            span_id=document_id,
        )


@dataclass(frozen=True)
class CitationRequest:
    """One citation to audit (claim + backend-supplied document/version/location)."""

    claim: str
    document_id: str
    version: str | None = None
    location: str | None = None
    quote: str | None = None
    candidate_spans: tuple[str, ...] = ()


@dataclass(frozen=True)
class CitationAuditResult:
    """The audit verdict, the producing layer, and its traceability."""

    label: str
    layer: str  # "existence" | "quote" | "support"
    reject_reason: str | None = None
    matched_quote: bool | None = None
    normalized_quote: str | None = None
    selected_span: str | None = None
    support_probability: float | None = None
    used_jev: bool = False

    @property
    def is_verified(self) -> bool:
        """True only for a real Jev SUPPORTED verdict (safe to show as verified)."""
        return self.label == SUPPORTED and self.used_jev


def is_definitive(result: CitationAuditResult) -> bool:
    """True when the verdict is a definite, checked result safe to finalize.

    High-impact material (reference solutions, grading rationale) is held open
    until this returns True: SUPPORTED (verified) or CONTRADICTED (must correct).
    PARTIAL/NOT_ADDRESSED/INSUFFICIENT are not definitive.
    """
    return result.label in (SUPPORTED, CONTRADICTED)


def _map_support(claim: str, evidence_text: str, result: DecisionResult) -> str:
    if result.used_jev and isinstance(result.value, float):
        if result.value >= _SUPPORTED_THRESHOLD:
            return SUPPORTED
        if result.value >= _PARTIAL_THRESHOLD:
            return PARTIALLY_SUPPORTED
        # A strong "no": only a direct, deterministic, unit-aware numeric conflict
        # may be reported as a contradiction; otherwise the fragment merely fails
        # to address the claim.
        if _numeric_contradiction(claim, evidence_text):
            return CONTRADICTED
        return NOT_ADDRESSED_IN_AVAILABLE_EVIDENCE
    return INSUFFICIENT_CONTEXT


def audit_citation(
    service: SemanticDecisionService | None,
    request: CitationRequest,
    *,
    resolver: EvidenceResolver | None = None,
    scope: CacheScope | None = None,
) -> CitationAuditResult:
    """Run the three-layer audit; layers 1 and 2 are deterministic (zero Jev)."""
    if resolver is None:
        return CitationAuditResult(label=INSUFFICIENT_CONTEXT, layer="existence")

    # Layer 1 — existence + authorization (deterministic, zero Jev).
    evidence = resolver.resolve(
        document_id=request.document_id, version=request.version, location=request.location
    )
    if evidence.status == "unauthorized":
        return CitationAuditResult(label=REJECTED, layer="existence", reject_reason="unauthorized")
    if evidence.status == "missing":
        return CitationAuditResult(label=REJECTED, layer="existence", reject_reason="missing")

    # Layer 2 — quoted text/number actually exists (deterministic, zero Jev).
    match: QuoteMatch | None = None
    if request.quote:
        match = quote_exists(request.quote, evidence.text)
        if not match.matched:
            return CitationAuditResult(
                label=NOT_ADDRESSED_IN_AVAILABLE_EVIDENCE,
                layer="quote",
                matched_quote=False,
                normalized_quote=match.normalized_quote,
            )

    # Layer 3 — evidence supports the specific claim (semantic only).
    selected_span = evidence.span_id
    if request.candidate_spans and service is not None:
        selected = service.select_span(
            claim=request.claim,
            candidate_spans=list(request.candidate_spans),
            caller_role="citation",
            cache_scope=scope or CacheScope(),
        )
        if (
            selected.value not in (None, "NO_SUPPORT")
            and str(selected.value) in request.candidate_spans
        ):
            selected_span = str(selected.value)

    matched_quote = match.matched if match is not None else None
    normalized_quote = match.normalized_quote if match is not None else None
    if service is None:
        return CitationAuditResult(
            label=INSUFFICIENT_CONTEXT,
            layer="support",
            matched_quote=matched_quote,
            normalized_quote=normalized_quote,
            selected_span=selected_span,
        )

    result = service.supports_claim(
        claim=request.claim,
        source_span=evidence.text,
        source_version=evidence.version or request.version or "",
        task_scope=evidence.location or request.location or "audit",
        caller_role="citation",
        cache_scope=scope or CacheScope(),
    )
    probability: float | None = None
    if result.used_jev and isinstance(result.value, float):
        probability = result.value
    return CitationAuditResult(
        label=_map_support(request.claim, evidence.text, result),
        layer="support",
        matched_quote=matched_quote,
        normalized_quote=normalized_quote,
        selected_span=selected_span,
        support_probability=probability,
        used_jev=result.used_jev,
    )


class ClaimCitationAudit:
    """Service wrapper over :func:`audit_citation`."""

    def __init__(
        self, service: SemanticDecisionService | None, *, resolver: EvidenceResolver | None = None
    ) -> None:
        self.service = service
        self.resolver = resolver

    def audit(
        self, request: CitationRequest, *, scope: CacheScope | None = None
    ) -> CitationAuditResult:
        return audit_citation(self.service, request, resolver=self.resolver, scope=scope)


__all__ = [
    "CONTRADICTED",
    "CitationAuditResult",
    "CitationRequest",
    "ClaimCitationAudit",
    "EvidenceResolver",
    "INSUFFICIENT_CONTEXT",
    "LABELS",
    "NOT_ADDRESSED_IN_AVAILABLE_EVIDENCE",
    "PARTIALLY_SUPPORTED",
    "QuoteMatch",
    "REJECTED",
    "ResolvedEvidence",
    "StaticEvidenceResolver",
    "SUPPORTED",
    "audit_citation",
    "is_definitive",
    "normalize_whitespace",
    "quote_exists",
]
