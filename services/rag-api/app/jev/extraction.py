"""Extraction verification: stop silently-wrong extraction from poisoning teaching.

A vision/parser pass produces structured fields out of questions, tables, figures
and (where a student typed or uploaded them) answer fields. This module is the
guard that sits between that pass and anything that teaches or grades:

* **deterministic checks run first** (required fields, numeric parse, unit
  consistency, question-number shape, table structure, source exists, source is
  inside the authorized course scope) — a record failing any of these is
  rejected/flagged with **zero** Jev calls;
* **Jev then judges only the semantic residue**, and only over the supplied text:
  does the value actually belong to this question/condition, was it copied from an
  adjacent example, was a negation or constraint dropped, does a student answer map
  to the right sub-question, is the supplied source enough to confirm it;
* **only the flagged field / source region may be repaired**, within a bounded,
  planned budget (at most one repair step per extraction, never a whole-document
  re-read, never an implicit SDK retry, never a model-tier upgrade, never another
  generation provider).

**A Jev agreement is NOT vision verification.** If a character is still
unreadable, or the value came from an unreadable region, the result is always
``NEEDS_REVIEW`` with the source region preserved — never a confident acceptance.
A Jev ``GROUNDED`` verdict only ever confirms that the *already-read* supplied text
supports the field; it cannot read pixels for us.

**Never help a student cheat.** A student answer may be repaired for legibility
only; it is never rewritten into the correct answer. Drafts, transcriptions,
submissions and grading revisions stay separate, and a reference solution is
prepared without reading student answers (the semantic state for a reference
solution never carries student-answer fields).

The decision definition is ``extraction.field_grounded.v1`` with candidates
``GROUNDED / WRONG_FIELD / NEGATION_LOST / CONSTRAINT_LOST / SOURCE_INSUFFICIENT /
UNCERTAIN``. It is registered in ``decision_catalog.json`` (19 definitions), and
:func:`field_grounded_definition` projects it from there rather than carrying a
second copy of the vocabulary; the candidate tuple below exists so a caller can
assert the agreement.

The semantic judgment goes through the ``callsites.verify_extraction_field`` call
site, so an extraction decision is observable and budgeted exactly like the other
business decisions, and never reaches the transport directly.

Degradation is typed and safe: Jev unavailable / invalid / oversized / off / shadow
falls back to the deterministic result plus ``NEEDS_REVIEW`` wherever the decision
mattered, with a typed :class:`FallbackReason`. No state is written here; the only
table involved is ``jev_decision_receipts`` (via the gateway's receipt store).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from app.jev import callsites
from app.jev.catalog import DecisionDefinition, Primitive, load_catalog
from app.jev.errors import JevError, JevRequestError
from app.jev.gateway import Decision, DecisionRequest, JevGateway
from app.jev.models import CacheScope, owner_scope_hash
from app.jev.service import SemanticDecisionService

# --------------------------------------------------------------------------- #
# Definition constants (the catalog owner registers these; we only *use* them)
# --------------------------------------------------------------------------- #

EXTRACTION_FIELD_GROUNDED_KEY = "extraction.field_grounded.v1"
EXTRACTION_FIELD_GROUNDED_VERSION = "1.0.0-design"

FIELD_GROUNDED_CANDIDATES = (
    "GROUNDED",
    "WRONG_FIELD",
    "NEGATION_LOST",
    "CONSTRAINT_LOST",
    "SOURCE_INSUFFICIENT",
    "UNCERTAIN",
)

FIELD_GROUNDED_CRITERIA: dict[str, str] = {
    "GROUNDED": (
        "The candidate value actually belongs to this question/condition and is "
        "fully supported by the supplied source text"
    ),
    "WRONG_FIELD": (
        "The value was copied from an adjacent example or a different field, not this "
        "question/condition"
    ),
    "NEGATION_LOST": "A negation (not/no/except/unless) was dropped, inverting the value",
    "CONSTRAINT_LOST": (
        "A constraint or condition (range, unit, scope, if/when) was dropped from the value"
    ),
    "SOURCE_INSUFFICIENT": (
        "The supplied source text is not enough to confirm the value belongs here"
    ),
    "UNCERTAIN": "Cannot resolve reliably from the supplied text",
}

FIELD_GROUNDED_INSTRUCTIONS = (
    "Judge ONLY the supplied source text: does the candidate value actually belong to "
    "this question/condition, or was it copied from an adjacent example, or a negation/"
    "constraint dropped? Use no outside knowledge; never confirm a value the supplied "
    "text does not show; when the text is insufficient say SOURCE_INSUFFICIENT."
)

FIELD_GROUNDED_REQUIRED_STATE = (
    "question_id",
    "part_id",
    "field_name",
    "candidate_value",
    "unit",
    "supplied_text",
    "source_region",
)

# Same 8-way cache scope as the existing 12 definitions.
_FIELD_GROUNDED_CACHE_SCOPE = (
    "authorization_scope",
    "course",
    "workspace",
    "material_revision",
    "node_spec_version",
    "question_definition_hash",
    "input_hash",
    "provider_model_version",
)

# --------------------------------------------------------------------------- #
# Bounds
# --------------------------------------------------------------------------- #

# At most one repair step per extraction, planned explicitly (never an SDK retry).
MAX_REPAIR_STEPS_PER_RECORD = 1

# The semantic residue sent to Jev is only the single field + its source region,
# so the practical ceiling is small; this is the verifier's own bound (the
# gateway's global 40k-char bound still applies as a backstop).
DEFAULT_MAX_STATE_CHARS = 8_000

DEFAULT_QUESTION_NUMBER_PATTERN = r"^[Qq]?\d+$"
DEFAULT_PART_NUMBER_PATTERN = r"^[A-Za-z]?$"

# Server-internal owner/authorization used when the caller does not supply a
# user-scoped :class:`CacheScope`. The digest is still server-derived (never
# client-supplied), so receipts never hit the ``owner_scope_hash`` NOT NULL
# constraint even for pipeline-internal decisions.
_EXTRACTION_OWNER = "extraction-pipeline"
_EXTRACTION_SCOPE = "extraction"


def field_grounded_definition() -> DecisionDefinition:
    """The registered ``extraction.field_grounded.v1`` definition.

    Projected from ``decision_catalog.json`` so the catalog stays the single owner
    of the vocabulary, instructions and failure policy. The module constants below
    are then asserted against it: this guard's whole job is to stop a wrong field
    from reaching teaching, so a catalog edit that silently changed what the guard
    is allowed to answer must fail loudly here instead.
    """
    definition = load_catalog().get(EXTRACTION_FIELD_GROUNDED_KEY)
    if definition.primitive != Primitive.CHOICE:
        raise ValueError(
            f"{EXTRACTION_FIELD_GROUNDED_KEY}: expected a Choice, got {definition.primitive!r}"
        )
    if set(definition.criteria or {}) != set(FIELD_GROUNDED_CANDIDATES):
        raise ValueError(
            f"{EXTRACTION_FIELD_GROUNDED_KEY}: catalog candidates "
            f"{sorted(definition.criteria or {})} != {sorted(FIELD_GROUNDED_CANDIDATES)}"
        )
    if definition.required_state != FIELD_GROUNDED_REQUIRED_STATE:
        raise ValueError(
            f"{EXTRACTION_FIELD_GROUNDED_KEY}: catalog required_state "
            f"{definition.required_state} != {FIELD_GROUNDED_REQUIRED_STATE}"
        )
    if definition.cache_scope != _FIELD_GROUNDED_CACHE_SCOPE:
        raise ValueError(
            f"{EXTRACTION_FIELD_GROUNDED_KEY}: catalog cache_scope "
            f"{definition.cache_scope} != {_FIELD_GROUNDED_CACHE_SCOPE}"
        )
    return definition


# --------------------------------------------------------------------------- #
# Typed result vocabulary
# --------------------------------------------------------------------------- #


class Verdict(StrEnum):
    """The semantic judgment over the residue (mirrors the definition candidates)."""

    GROUNDED = "GROUNDED"
    WRONG_FIELD = "WRONG_FIELD"
    NEGATION_LOST = "NEGATION_LOST"
    CONSTRAINT_LOST = "CONSTRAINT_LOST"
    SOURCE_INSUFFICIENT = "SOURCE_INSUFFICIENT"
    UNCERTAIN = "UNCERTAIN"


_VERDICT_BY_VALUE = {member.value: member for member in Verdict}


class Status(StrEnum):
    """The final disposition of an extraction record."""

    ACCEPTED = "ACCEPTED"  # deterministic + Jev GROUNDED
    REJECTED = "REJECTED"  # a deterministic check failed (zero Jev calls)
    FLAGGED = "FLAGGED"  # Jev found a semantic defect; a repair may be planned
    NEEDS_REVIEW = "NEEDS_REVIEW"  # cannot be resolved confidently


class FallbackReason(StrEnum):
    """Typed reason a decision degraded to the deterministic/NEEDS_REVIEW path."""

    NO_SERVICE = "no_service"
    JEV_OFF = "jev_off"
    JEV_SHADOW = "jev_shadow"
    JEV_NOT_CONFIGURED = "jev_not_configured"
    JEV_UNAVAILABLE = "jev_unavailable"
    JEV_TIMEOUT = "jev_timeout"
    JEV_INVALID_RESPONSE = "jev_invalid_response"
    JEV_UNCERTAIN = "jev_uncertain"
    INPUT_TOO_LONG = "input_too_long"
    UNREADABLE_REGION = "unreadable_region"
    REPAIR_NOT_ALLOWED = "repair_not_allowed"
    REPAIR_BUDGET_EXHAUSTED = "repair_budget_exhausted"
    REPAIR_STEP_LIMIT = "repair_step_limit"
    STUDENT_REPAIR_NOT_LEGIBILITY = "student_repair_not_legibility"
    STUDENT_ANSWER_REWRITE_REFUSED = "student_answer_rewrite_refused"


class RecordRole(StrEnum):
    """What an extraction record is *for*, which bounds how it may be repaired."""

    SOURCE = "source"
    REFERENCE_SOLUTION = "reference_solution"
    STUDENT_ANSWER = "student_answer"
    DRAFT = "draft"
    TRANSCRIPTION = "transcription"
    SUBMISSION = "submission"
    GRADING_REVISION = "grading_revision"


# Roles whose content is the student's own: legibility-only repair, never a
# rewrite toward correctness.
_CHEATING_SENSITIVE_ROLES = frozenset(
    {
        RecordRole.STUDENT_ANSWER,
        RecordRole.DRAFT,
        RecordRole.TRANSCRIPTION,
        RecordRole.SUBMISSION,
        RecordRole.GRADING_REVISION,
    }
)


# --------------------------------------------------------------------------- #
# The normalized extraction record
# --------------------------------------------------------------------------- #


@dataclass
class ExtractionRecord:
    """One normalized, structured field produced by a vision/parser pass.

    ``candidate_value`` is the value the parser believes it read; ``supplied_text``
    is the (bounded) source text for the exact region that was read, which is the
    *only* thing the semantic judgment may look at. ``role`` tells the verifier
    whether the field is source material, a student's own answer, or a prepared
    reference, so the repair/anti-cheat rules can be applied.
    """

    source_id: str
    source_version: str
    page: int | None
    region: str | None
    span: tuple[int, int] | None
    question_id: str
    part_id: str | None
    field_name: str
    candidate_value: Any
    unit: str | None
    uncertainty: float | None
    extraction_version: str
    supplied_text: str | None = None
    role: RecordRole = RecordRole.SOURCE
    table_rows: tuple[tuple[str, ...], ...] | None = None
    unreadable: bool = False

    def as_dict(self) -> dict[str, Any]:
        """A JSON-friendly projection of the record."""
        return {
            "source_id": self.source_id,
            "source_version": self.source_version,
            "page": self.page,
            "region": self.region,
            "span": list(self.span) if self.span is not None else None,
            "question_id": self.question_id,
            "part_id": self.part_id,
            "field_name": self.field_name,
            "candidate_value": self.candidate_value,
            "unit": self.unit,
            "uncertainty": self.uncertainty,
            "extraction_version": self.extraction_version,
            "supplied_text": self.supplied_text,
            "role": self.role.value,
            "table_rows": [list(row) for row in self.table_rows]
            if self.table_rows is not None
            else None,
            "unreadable": self.unreadable,
        }

    def identity(self) -> str:
        """A stable id of the *slot* the field occupies (not its value).

        A repair changes ``candidate_value``/``supplied_text`` but not the slot,
        so an original record and its repaired form share an identity and the
        single-repair bound applies across them.
        """
        payload = {
            "source_id": self.source_id,
            "source_version": self.source_version,
            "page": self.page,
            "region": self.region,
            "span": list(self.span) if self.span is not None else None,
            "question_id": self.question_id,
            "part_id": self.part_id,
            "field_name": self.field_name,
            "extraction_version": self.extraction_version,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()


# --------------------------------------------------------------------------- #
# Deterministic checks (all in code, no model)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FieldSpec:
    """What the deterministic backend already knows about a field's shape."""

    kind: str = "text"  # "text" | "number"
    expected_unit: str | None = None


@dataclass(frozen=True)
class DeterministicFailure:
    """One failed deterministic check, with a stable code."""

    code: str
    field: str
    detail: str


@dataclass(frozen=True)
class DeterministicVerdict:
    """The outcome of the code-only checks."""

    ok: bool
    failures: tuple[DeterministicFailure, ...]


class SourceRegistry(Protocol):
    """Minimal source-authority the deterministic backend owns."""

    def source_exists(self, source_id: str) -> bool: ...

    def source_in_scope(self, source_id: str, *, course_scope: str) -> bool: ...


class StaticSourceRegistry:
    """In-memory registry: ``sources`` maps source id -> tuple of authorized scopes."""

    def __init__(self, sources: dict[str, tuple[str, ...]] | None = None) -> None:
        self._sources = dict(sources or {})

    def source_exists(self, source_id: str) -> bool:
        return source_id in self._sources

    def source_in_scope(self, source_id: str, *, course_scope: str) -> bool:
        scopes = self._sources.get(source_id)
        if scopes is None:
            return False
        return not scopes or course_scope in scopes


def run_deterministic_checks(
    record: ExtractionRecord,
    *,
    source_registry: SourceRegistry | None,
    course_scope: str,
    field_specs: dict[str, FieldSpec],
    question_number_pattern: str,
    part_number_pattern: str,
) -> DeterministicVerdict:
    """Run every code-only check; collect all failures (never short-circuit).

    The order is the documented order: required fields, numeric parse, unit
    consistency, question-number shape, table structure, source exists, source in
    scope. A record failing any of these is rejected without a Jev call.
    """
    failures: list[DeterministicFailure] = []

    # 1. Required fields present.
    if not record.source_id:
        failures.append(DeterministicFailure("missing_source_id", "source_id", "empty"))
    if not record.source_version:
        failures.append(DeterministicFailure("missing_source_version", "source_version", "empty"))
    if not record.question_id:
        failures.append(DeterministicFailure("missing_question_id", "question_id", "empty"))
    if not record.field_name:
        failures.append(DeterministicFailure("missing_field_name", "field_name", "empty"))
    if record.candidate_value is None:
        failures.append(DeterministicFailure("missing_candidate_value", "candidate_value", "None"))
    if not record.extraction_version:
        failures.append(
            DeterministicFailure("missing_extraction_version", "extraction_version", "empty")
        )
    if record.page is None and record.region is None and record.span is None:
        failures.append(
            DeterministicFailure("missing_locator", "page/region/span", "no locator present")
        )
    if record.uncertainty is not None and not (0.0 <= record.uncertainty <= 1.0):
        failures.append(
            DeterministicFailure(
                "uncertainty_range", "uncertainty", f"out of [0,1]: {record.uncertainty}"
            )
        )

    spec = field_specs.get(record.field_name)

    # 2. Numeric parse (only when the backend expects a number for this field).
    if (
        spec is not None
        and spec.kind == "number"
        and _parse_number(record.candidate_value) is None
    ):
        failures.append(
            DeterministicFailure("non_numeric", "candidate_value", repr(record.candidate_value))
        )

    # 3. Unit consistency.
    if spec is not None and spec.expected_unit:
        expected = spec.expected_unit.strip().lower()
        if not record.unit or not record.unit.strip():
            failures.append(
                DeterministicFailure("missing_unit", "unit", f"expected {spec.expected_unit!r}")
            )
        elif record.unit.strip().lower() != expected:
            failures.append(
                DeterministicFailure(
                    "unit_mismatch",
                    "unit",
                    f"{record.unit!r} != {spec.expected_unit!r}",
                )
            )

    # 4. Question-number shape.
    if re.fullmatch(question_number_pattern, record.question_id) is None:
        failures.append(
            DeterministicFailure(
                "question_number_shape", "question_id", repr(record.question_id)
            )
        )
    if record.part_id and re.fullmatch(part_number_pattern, record.part_id) is None:
        failures.append(
            DeterministicFailure("question_number_shape", "part_id", repr(record.part_id))
        )

    # 5. Table structure (rows/columns consistent, no shifted cells).
    failures.extend(_check_table_structure(record.table_rows))

    # 6. Source id exists.
    if source_registry is None or not source_registry.source_exists(record.source_id):
        failures.append(
            DeterministicFailure("source_unknown", "source_id", repr(record.source_id))
        )

    # 7. Source is inside the authorized course scope.
    elif not source_registry.source_in_scope(record.source_id, course_scope=course_scope):
        failures.append(
            DeterministicFailure(
                "source_out_of_scope",
                "source_id",
                f"{record.source_id!r} not in course scope {course_scope!r}",
            )
        )

    return DeterministicVerdict(ok=not failures, failures=tuple(failures))


def _check_table_structure(
    table_rows: tuple[tuple[str, ...], ...] | None,
) -> list[DeterministicFailure]:
    """Detect inconsistent column counts and shifted cells in a parsed table."""
    if table_rows is None:
        return []
    failures: list[DeterministicFailure] = []
    width = len(table_rows[0])
    for index, row in enumerate(table_rows):
        if len(row) != width:
            failures.append(
                DeterministicFailure(
                    "table_column_count",
                    "table_rows",
                    f"row {index} has {len(row)} cells, expected {width}",
                )
            )
    # A shifted cell shows up as an empty cell in a column whose header (and the
    # other rows) are populated — the value landed in the wrong column.
    for col in range(width):
        header = table_rows[0][col].strip()
        if not header:
            continue
        for index, row in enumerate(table_rows[1:], start=1):
            cell = row[col].strip() if col < len(row) else ""
            if not cell:
                failures.append(
                    DeterministicFailure(
                        "table_shifted_cell",
                        "table_rows",
                        f"row {index} col {col} empty under header {header!r}",
                    )
                )
    return failures


def _parse_number(value: Any) -> float | None:
    """Parse a numeric candidate; ``None`` when it is not a plain number."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Repair planning (bounded; never a re-read of the whole document)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RepairRequest:
    """The *only* authorized repair: one field, one source region, one step.

    ``kind`` is ``"legibility"`` for a student's own content (clarify characters,
    never change the answer) and ``"re_extract"`` for source/reference material.
    The request pins the source region so the caller can never fall back to a
    whole-document re-read.
    """

    record_identity: str
    field_name: str
    question_id: str
    source_region: dict[str, Any]
    kind: str
    reason: str


@dataclass(frozen=True)
class VerificationResult:
    """The disposition of one extraction record after the full pipeline."""

    status: Status
    record: dict[str, Any]
    verdict: Verdict | None
    used_jev: bool
    jev_calls: int
    deterministic_failures: tuple[DeterministicFailure, ...]
    repair_request: RepairRequest | None
    fallback_reason: FallbackReason | None
    path: str
    receipt_id: str | None
    input_hash: str | None
    repair_budget_remaining: int


@dataclass(frozen=True)
class Judgment:
    """What the verifier needs to keep from one semantic attempt.

    Both the gateway path and the business call-site path normalise into this, so
    a result can report its receipt, its input digest and its mode without the
    caller knowing which route produced it.
    """

    receipt_id: str | None
    input_hash: str | None
    mode: str


# The service reports a fallback in its own vocabulary (``shadow``/``off``/
# ``timeout``/...); map it onto the module's typed reasons. An unmapped reason is
# never silently treated as success.
_SERVICE_FALLBACKS: dict[str, FallbackReason] = {
    "no_service": FallbackReason.NO_SERVICE,
    "off": FallbackReason.JEV_OFF,
    "shadow": FallbackReason.JEV_SHADOW,
    "timeout": FallbackReason.JEV_TIMEOUT,
    "not_configured": FallbackReason.JEV_NOT_CONFIGURED,
    "invalid_response": FallbackReason.JEV_INVALID_RESPONSE,
}


class ExtractionVerifier:
    """Orchestrates deterministic-first, Jev-on-residue, bounded-repair verification.

    ``gateway`` may be ``None`` for the fully deterministic path (zero Jev calls;
    the semantic residue then degrades to ``NEEDS_REVIEW``). ``service`` — a
    :class:`SemanticDecisionService`, mutually exclusive in practice with
    ``gateway`` — routes the same judgment through the
    ``callsites.verify_extraction_field`` business call site instead, which is how
    production reaches it. ``repair_budget`` is the caller's remaining allowance
    for repair model calls; ``repair_allowed`` is the user-mode gate. A repair is
    *planned* here (a single, region-scoped step) and its model call is executed by
    the generation provider — never by this module, which only ever reaches the
    Jev layer.
    """

    def __init__(
        self,
        *,
        gateway: JevGateway | None = None,
        service: SemanticDecisionService | None = None,
        source_registry: SourceRegistry | None = None,
        field_specs: dict[str, FieldSpec] | None = None,
        repair_budget: int = 1,
        repair_allowed: bool = True,
        max_state_chars: int = DEFAULT_MAX_STATE_CHARS,
        question_number_pattern: str = DEFAULT_QUESTION_NUMBER_PATTERN,
        part_number_pattern: str = DEFAULT_PART_NUMBER_PATTERN,
    ) -> None:
        self.gateway = gateway
        self.service = service
        self.source_registry = source_registry
        self.field_specs = field_specs or {}
        self.repair_budget = repair_budget
        self.repair_allowed = repair_allowed
        self.max_state_chars = max_state_chars
        self.question_number_pattern = question_number_pattern
        self.part_number_pattern = part_number_pattern
        self._repairs_by_record: dict[str, int] = {}

    # ------------------------------------------------------------- entry point

    def verify(
        self,
        record: ExtractionRecord,
        *,
        cache_scope: CacheScope | None = None,
        course_scope: str = "",
    ) -> VerificationResult:
        """Verify one record: deterministic -> unreadable guard -> semantic -> repair.

        The semantic judgment runs only over the supplied text of the flagged
        field/source region, and only after every deterministic check passed.
        """
        deterministic = run_deterministic_checks(
            record,
            source_registry=self.source_registry,
            course_scope=course_scope,
            field_specs=self.field_specs,
            question_number_pattern=self.question_number_pattern,
            part_number_pattern=self.part_number_pattern,
        )
        if not deterministic.ok:
            return VerificationResult(
                status=Status.REJECTED,
                record=record.as_dict(),
                verdict=None,
                used_jev=False,
                jev_calls=0,
                deterministic_failures=deterministic.failures,
                repair_request=None,
                fallback_reason=None,
                path="deterministic_reject",
                receipt_id=None,
                input_hash=None,
                repair_budget_remaining=self.repair_budget,
            )

        if record.unreadable:
            return self._needs_review(record, FallbackReason.UNREADABLE_REGION, verdict=None)

        verdict, judgment, reason = self._judge(record, cache_scope)
        if verdict is None:
            assert reason is not None
            return self._needs_review(
                record,
                reason,
                verdict=None,
                judgment=judgment,
            )

        if verdict is Verdict.GROUNDED:
            return VerificationResult(
                status=Status.ACCEPTED,
                record=record.as_dict(),
                verdict=verdict,
                used_jev=True,
                jev_calls=1,
                deterministic_failures=(),
                repair_request=None,
                fallback_reason=None,
                path="jev",
                receipt_id=judgment.receipt_id if judgment is not None else None,
                input_hash=judgment.input_hash if judgment is not None else None,
                repair_budget_remaining=self.repair_budget,
            )

        if verdict is Verdict.UNCERTAIN:
            return self._needs_review(
                record, FallbackReason.JEV_UNCERTAIN, verdict=verdict, judgment=judgment
            )

        may_repair, refuse_reason = self._may_repair(record)
        if not may_repair:
            assert refuse_reason is not None
            return self._needs_review(record, refuse_reason, verdict=verdict, judgment=judgment)

        self._spend_repair(record)
        request = self._build_repair_request(record, verdict)
        return VerificationResult(
            status=Status.FLAGGED,
            record=record.as_dict(),
            verdict=verdict,
            used_jev=True,
            jev_calls=1,
            deterministic_failures=(),
            repair_request=request,
            fallback_reason=None,
            path="flagged_repair",
            receipt_id=judgment.receipt_id if judgment is not None else None,
            input_hash=judgment.input_hash if judgment is not None else None,
            repair_budget_remaining=self.repair_budget,
        )

    def apply_repair(
        self,
        original: ExtractionRecord,
        repaired: ExtractionRecord,
        *,
        repair_kind: str = "legibility",
        correct_answer: Any = None,
        cache_scope: CacheScope | None = None,
        course_scope: str = "",
    ) -> VerificationResult:
        """Apply a bounded repair and re-verify, enforcing anti-cheat + the step bound.

        A student's own content may be repaired only for legibility, and never
        rewritten into the correct answer; if the caller passes the known correct
        answer, a repair that changes a student answer *into* it is refused.
        """
        guard = self._repair_guard(
            original, repaired, repair_kind=repair_kind, correct_answer=correct_answer
        )
        if guard is not None:
            return self._needs_review(original, guard, verdict=None)
        self._spend_repair(original)
        # Re-verify the repaired record; because a repair was already spent for this
        # slot identity, no second repair can be planned here.
        return self.verify(repaired, cache_scope=cache_scope, course_scope=course_scope)

    # -------------------------------------------------------------- semantics

    def _judge(
        self, record: ExtractionRecord, cache_scope: CacheScope | None
    ) -> tuple[Verdict | None, Judgment | None, FallbackReason | None]:
        """Run the ``extraction.field_grounded.v1`` choice over the residue only."""
        state = self._residue_state(record)
        if len(json.dumps(state, default=str)) > self.max_state_chars:
            return None, None, FallbackReason.INPUT_TOO_LONG
        if self.service is not None:
            return self._judge_via_callsite(record, state, cache_scope)
        return self._judge_via_gateway(record, state, cache_scope)

    def _judge_via_callsite(
        self,
        record: ExtractionRecord,
        state: dict[str, Any],
        cache_scope: CacheScope | None,
    ) -> tuple[Verdict | None, Judgment | None, FallbackReason | None]:
        """Judge through the business call site (production path)."""
        assert self.service is not None
        grounded = callsites.verify_extraction_field(
            self.service,
            question_id=record.question_id,
            part_id=record.part_id,
            field_name=record.field_name,
            candidate_value=record.candidate_value,
            unit=record.unit,
            supplied_text=record.supplied_text or "",
            source_region=state["source_region"],
            scope=cache_scope or self._default_scope(),
        )
        judgment = Judgment(
            receipt_id=grounded.receipt_id,
            input_hash=grounded.input_hash,
            mode=grounded.mode,
        )
        if grounded.used_jev:
            verdict = _VERDICT_BY_VALUE.get(grounded.verdict)
            if verdict is None:
                return None, judgment, FallbackReason.JEV_INVALID_RESPONSE
            return verdict, judgment, None
        reason = _SERVICE_FALLBACKS.get(
            grounded.fallback_reason or "", FallbackReason.JEV_UNAVAILABLE
        )
        return None, judgment, reason

    def _judge_via_gateway(
        self,
        record: ExtractionRecord,
        state: dict[str, Any],
        cache_scope: CacheScope | None,
    ) -> tuple[Verdict | None, Judgment | None, FallbackReason | None]:
        """Judge through a caller-supplied gateway (tests, standalone pipelines)."""
        if self.gateway is None:
            return None, None, FallbackReason.NO_SERVICE

        definition = field_grounded_definition()
        request = DecisionRequest(
            definition=definition,
            state=state,
            caller_role="extraction",
            cache_scope=cache_scope or self._default_scope(),
            criteria=dict(FIELD_GROUNDED_CRITERIA),
            instructions=FIELD_GROUNDED_INSTRUCTIONS,
        )
        try:
            decision = self.gateway.evaluate(request)
        except JevRequestError:
            return None, None, FallbackReason.INPUT_TOO_LONG
        except JevError:
            return None, None, FallbackReason.JEV_UNAVAILABLE

        judgment = Judgment(
            receipt_id=decision.receipt_id,
            input_hash=decision.input_hash,
            mode=decision.mode,
        )
        if decision.mode == "on" and decision.outcome == "ok" and decision.suggestion is not None:
            choice = decision.suggestion.choice
            verdict = _VERDICT_BY_VALUE.get(choice) if choice is not None else None
            if verdict is None:
                return None, judgment, FallbackReason.JEV_INVALID_RESPONSE
            return verdict, judgment, None
        return None, judgment, self._fallback_for(decision)

    @staticmethod
    def _default_scope() -> CacheScope:
        return CacheScope(
            owner_scope_hash=owner_scope_hash(_EXTRACTION_OWNER, _EXTRACTION_SCOPE)
        )

    @staticmethod
    def _residue_state(record: ExtractionRecord) -> dict[str, Any]:
        """The exact residue Jev may see: one field + its bounded source region.

        A reference solution's state never carries student-answer fields because
        this projection is built from the record's own slot only.
        """
        return {
            "question_id": record.question_id,
            "part_id": record.part_id,
            "field_name": record.field_name,
            "candidate_value": record.candidate_value,
            "unit": record.unit,
            "supplied_text": record.supplied_text or "",
            "source_region": {
                "page": record.page,
                "region": record.region,
                "span": list(record.span) if record.span is not None else None,
            },
        }

    @staticmethod
    def _fallback_for(decision: Decision) -> FallbackReason:
        if decision.mode == "off":
            return FallbackReason.JEV_OFF
        if decision.mode == "shadow":
            return FallbackReason.JEV_SHADOW
        if decision.outcome == "timeout":
            return FallbackReason.JEV_TIMEOUT
        if decision.outcome == "not_configured":
            return FallbackReason.JEV_NOT_CONFIGURED
        if decision.outcome == "invalid_response":
            return FallbackReason.JEV_INVALID_RESPONSE
        return FallbackReason.JEV_UNAVAILABLE

    # ---------------------------------------------------------------- repair

    def _may_repair(self, record: ExtractionRecord) -> tuple[bool, FallbackReason | None]:
        if not self.repair_allowed:
            return False, FallbackReason.REPAIR_NOT_ALLOWED
        if self.repair_budget <= 0:
            return False, FallbackReason.REPAIR_BUDGET_EXHAUSTED
        if self._repairs_by_record.get(record.identity(), 0) >= MAX_REPAIR_STEPS_PER_RECORD:
            return False, FallbackReason.REPAIR_STEP_LIMIT
        return True, None

    def _spend_repair(self, record: ExtractionRecord) -> None:
        identity = record.identity()
        self._repairs_by_record[identity] = self._repairs_by_record.get(identity, 0) + 1
        if self.repair_budget > 0:
            self.repair_budget -= 1

    @staticmethod
    def _build_repair_request(
        record: ExtractionRecord, verdict: Verdict
    ) -> RepairRequest:
        kind = (
            "legibility"
            if record.role in _CHEATING_SENSITIVE_ROLES
            else "re_extract"
        )
        return RepairRequest(
            record_identity=record.identity(),
            field_name=record.field_name,
            question_id=record.question_id,
            source_region={
                "page": record.page,
                "region": record.region,
                "span": record.span,
            },
            kind=kind,
            reason=verdict.value,
        )

    @staticmethod
    def _repair_guard(
        original: ExtractionRecord,
        repaired: ExtractionRecord,
        *,
        repair_kind: str,
        correct_answer: Any,
    ) -> FallbackReason | None:
        """Refuse any repair that would help a student cheat."""
        if original.role not in _CHEATING_SENSITIVE_ROLES:
            return None
        if repair_kind != "legibility":
            return FallbackReason.STUDENT_REPAIR_NOT_LEGIBILITY
        if (
            correct_answer is not None
            and _normalized(repaired.candidate_value) == _normalized(correct_answer)
            and _normalized(original.candidate_value) != _normalized(correct_answer)
        ):
            return FallbackReason.STUDENT_ANSWER_REWRITE_REFUSED
        return None

    # --------------------------------------------------------------- results

    def _needs_review(
        self,
        record: ExtractionRecord,
        reason: FallbackReason,
        *,
        verdict: Verdict | None,
        judgment: Judgment | None = None,
    ) -> VerificationResult:
        return VerificationResult(
            status=Status.NEEDS_REVIEW,
            record=record.as_dict(),
            verdict=verdict,
            used_jev=False,
            jev_calls=1 if judgment is not None and judgment.mode != "off" else 0,
            deterministic_failures=(),
            repair_request=None,
            fallback_reason=reason,
            path=f"fallback:{reason.value}",
            receipt_id=judgment.receipt_id if judgment is not None else None,
            input_hash=judgment.input_hash if judgment is not None else None,
            repair_budget_remaining=self.repair_budget,
        )


def _normalized(value: Any) -> str:
    return str(value).strip()


__all__ = [
    "DEFAULT_MAX_STATE_CHARS",
    "DEFAULT_PART_NUMBER_PATTERN",
    "DEFAULT_QUESTION_NUMBER_PATTERN",
    "EXTRACTION_FIELD_GROUNDED_KEY",
    "EXTRACTION_FIELD_GROUNDED_VERSION",
    "DeterministicFailure",
    "DeterministicVerdict",
    "ExtractionRecord",
    "ExtractionVerifier",
    "FallbackReason",
    "FieldSpec",
    "FIELD_GROUNDED_CANDIDATES",
    "FIELD_GROUNDED_CRITERIA",
    "FIELD_GROUNDED_INSTRUCTIONS",
    "FIELD_GROUNDED_REQUIRED_STATE",
    "Judgment",
    "MAX_REPAIR_STEPS_PER_RECORD",
    "RecordRole",
    "RepairRequest",
    "SourceRegistry",
    "StaticSourceRegistry",
    "Status",
    "Verdict",
    "VerificationResult",
    "field_grounded_definition",
    "run_deterministic_checks",
]
