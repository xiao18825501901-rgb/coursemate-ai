"""A/B/C/D Jev ablation harness: pure metrics, real wired code paths, honesty guards.

Why this exists: the frozen ablation plan
(``JEV_ABLATION_AND_PRODUCTION_ACCEPTANCE.md`` §3) needs exactly one command that
turns credentials + a labelled dataset into real numbers the moment they arrive,
while making it impossible to mistake an offline plumbing run for a quality result.
No credential, budget or labelled dataset exists in this environment, so this module
must not invent any number: it only wires the measurement.

Honesty contract (enforced in code, not prose):

* Every metric is computed from the case file's LABELS. A Jev ``Score``/``Noul``
  probability or confidence is never used as a label, a grade or an accuracy
  reference; the per-case results carry ``label_*`` fields sourced only from the
  dataset, and the metric functions never read a Jev confidence as a reference.
* Every run records ``transport`` in {``deterministic_fake``, ``live``}. A
  ``deterministic_fake`` run is tagged ``interpretation=NON_INTERPRETABLE_PLUMBING_ONLY``
  and :func:`compare_arms` refuses an improvement verdict — and raises ``ValueError``
  when a caller asks for a quality claim from a fake run.
* A live run is tagged ``INTERPRETABLE`` only when ``dataset_status`` is
  ``LABELLED_DATASET`` (never the ``EXAMPLE_NOT_LABELLED_FOR_RESULTS`` example file).
* The only side effect is Jev receipts in the supplied (or a throwaway) database; no
  learning/grade/coverage/permission state is ever written.

Metric -> the shipped code path it actually exercises:

* ``recall_at_k`` / ``mrr``    -> ``app.learning.retrieval_orchestrator.fuse_scoped_candidates``
  then ``app.jev.service.SemanticDecisionService.rerank_retrieval`` (``retrieval.support.v1``).
* ``locator_accuracy``         -> the same retrieval path; exact targets come from
  ``retrieval_orchestrator.exact_targets_from_query`` and keep their slot.
* ``citation_support_accuracy`` / ``unsupported_claim_rate``
                               -> ``SemanticDecisionService.noul("source.supports_claim.v1")``.
* ``mainline_recovery_rate``   -> ``SemanticDecisionService.next_action``
  (``intent.next_action.v1``) plus ``SemanticDecisionService.keep_segment``
  (``context.keep_segment.v1``).
* ``coverage_confusion``       -> ``SemanticDecisionService.choice``
  (``coverage.item_support.v1``; the same primitive ``item_support`` delegates to,
  kept at that level to retain ``used_jev``).
* ``criterion_error``          -> ``SemanticDecisionService.criterion_review``
  (``assessment.criterion_review.v1``).
* ``image_answer_accuracy``    -> an injected ``image_predictor`` (DeepSeek vision in a live run).
* ``latency_summary``          -> ``latency_ms`` rows from the Jev receipt ledger.
* ``cost_split``               -> measured Jev call count plus owner-supplied usage/prices.
* ``failure_rate``             -> ``outcome`` rows from the Jev receipt ledger.

``pedagogy.next_method.v1`` is armed by arms C/D per the frozen arm spec but has no
case family in this harness yet, so it contributes no observations; the same is true
of ``source.supports_claim.v1``, which no arm turns on, so citation predictions stay
on the deterministic (withholding) path until an arm arms that key.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.evaluation.model_benchmark import conservative_input_token_ceiling
from app.jev.catalog import Primitive, load_catalog
from app.jev.gateway import FakeTransport, JevGateway, ReceiptStore, Transport
from app.jev.models import JevAnswer, JevCall, JevResult
from app.jev.receipt_store import SqlReceiptStore
from app.jev.service import SemanticDecisionService
from app.learning.intent_commands import route_explicit_command
from app.learning.retrieval_orchestrator import (
    ScopedCandidates,
    exact_targets_from_query,
    fuse_scoped_candidates,
)

# --------------------------------------------------------------------------- arms

ARM_NAMES: tuple[str, ...] = ("A", "B", "C", "D")

# The specific keys each arm turns "on"; everything else in the catalog stays "off".
# The full key list is read from ``app.jev.catalog`` (never hand-copied here), and
# these arm-defining keys are validated against the live catalog in :func:`arm_modes`.
_ARM_ON_KEYS: dict[str, frozenset[str]] = {
    "A": frozenset(),
    "B": frozenset({"retrieval.support.v1"}),
    "C": frozenset(
        {
            "retrieval.support.v1",
            "context.keep_segment.v1",
            "intent.next_action.v1",
            "pedagogy.next_method.v1",
        }
    ),
    "D": frozenset(
        {
            "retrieval.support.v1",
            "context.keep_segment.v1",
            "intent.next_action.v1",
            "pedagogy.next_method.v1",
            "coverage.item_support.v1",
            "assessment.criterion_review.v1",
        }
    ),
}


def validate_arm_nesting() -> None:
    """Fail loudly if A ⊂ B ⊂ C ⊂ D no longer holds (strict subset on the "on" keys)."""
    a, b, c, d = (_ARM_ON_KEYS[name] for name in ARM_NAMES)
    if not (a < b < c < d):
        raise ValueError("Ablation arms must nest strictly: A ⊂ B ⊂ C ⊂ D.")


def arm_modes(arm: str) -> dict[str, str]:
    """Return the full per-key mode map for ``arm`` ("off" for every unarmed key).

    The key list comes from the real catalog; the arm-defining keys are validated
    against it so a future catalog edit cannot silently break an arm.
    """
    if arm not in ARM_NAMES:
        raise ValueError(f"Unknown ablation arm {arm!r}; expected one of {ARM_NAMES}.")
    validate_arm_nesting()
    definitions = load_catalog().definitions
    on_keys = _ARM_ON_KEYS[arm]
    unknown = sorted(on_keys - set(definitions))
    if unknown:
        raise ValueError(
            f"Arm {arm!r} references Jev keys absent from the catalog: {unknown}."
        )
    return {key: ("on" if key in on_keys else "off") for key in definitions}


# ------------------------------------------------------------------ dataset status

DATASET_STATUS_EXAMPLE = "EXAMPLE_NOT_LABELLED_FOR_RESULTS"
DATASET_STATUS_LABELLED = "LABELLED_DATASET"
_DATASET_STATUSES = frozenset({DATASET_STATUS_EXAMPLE, DATASET_STATUS_LABELLED})

TRANSPORT_FAKE = "deterministic_fake"
TRANSPORT_LIVE = "live"

INTERPRETATION_PLUMBING = "NON_INTERPRETABLE_PLUMBING_ONLY"
INTERPRETATION_INTERPRETABLE = "INTERPRETABLE"
INTERPRETATION_UNLABELLED = "NOT_INTERPRETABLE_UNLABELLED_DATASET"

FAILURE_OUTCOMES = frozenset({"timeout", "unavailable", "invalid_response", "not_configured"})


def transport_kind(transport: Transport) -> str:
    """Classify a transport as ``deterministic_fake`` or ``live`` for the run record."""
    return TRANSPORT_FAKE if isinstance(transport, FakeTransport) else TRANSPORT_LIVE


def interpretation_for(transport: str, dataset_status: str) -> str:
    """The run's interpretation tag, enforcing the honesty contract."""
    if transport == TRANSPORT_FAKE:
        return INTERPRETATION_PLUMBING
    if dataset_status == DATASET_STATUS_LABELLED:
        return INTERPRETATION_INTERPRETABLE
    return INTERPRETATION_UNLABELLED


# ------------------------------------------------------------------- case schema

_INTENT_ACTION_DEFINITION = "intent.next_action.v1"


def _intent_actions() -> frozenset[str]:
    definition = load_catalog().get(_INTENT_ACTION_DEFINITION)
    return frozenset(definition.criteria or {})


@dataclass(frozen=True)
class RetrievalCandidate:
    id: str
    text: str
    filename: str
    locator_type: str
    locator_value: str
    section: str
    scope: str
    rank: int


@dataclass(frozen=True)
class RetrievalCase:
    id: str
    query: str
    top_k: int
    candidates: tuple[RetrievalCandidate, ...]
    relevant_ids: frozenset[str]
    graded_relevance: dict[str, int]


@dataclass(frozen=True)
class LocatorCase:
    id: str
    query: str
    top_k: int
    candidates: tuple[RetrievalCandidate, ...]
    expected_id: str
    expected_slot: int


@dataclass(frozen=True)
class CitationCase:
    id: str
    claim: str
    source_span: str
    source_version: str
    task_scope: str
    label_supported: bool


@dataclass(frozen=True)
class TrajectoryTurn:
    message: str
    expected_action: str


@dataclass(frozen=True)
class TrajectoryCase:
    id: str
    anchor: str
    fixed_anchor: dict[str, Any]
    current_mode: str
    active_assessment: str | None
    current_task: str
    remaining_scope: str
    turns: tuple[TrajectoryTurn, ...]
    expected_action: str
    # Segments Jev is *allowed* to consider dropping: resolved follow-ups, duplicate
    # explanations, unrelated asides. The fixed anchor is never in this list — the
    # product keeps anchors unconditionally, so the harness must not ask.
    filterable_segments: tuple[str, ...] = ()


@dataclass(frozen=True)
class CoverageCase:
    id: str
    required_item: dict[str, Any]
    accepted_evidence: str
    spec_version: str
    label_supported: bool


@dataclass(frozen=True)
class CriterionItem:
    id: str
    criterion: dict[str, Any]
    label: str  # accurate | partially | not
    acceptable_alternatives: tuple[str, ...] = ()


@dataclass(frozen=True)
class CriterionCase:
    id: str
    frozen_question: dict[str, Any]
    reference_solution: str
    student_answer: str
    deterministic_verification: str
    criteria: tuple[CriterionItem, ...]


@dataclass(frozen=True)
class ImageCase:
    id: str
    prompt: str
    ground_truth_answer: str


@dataclass(frozen=True)
class AblationCaseSet:
    dataset_status: str
    retrieval: tuple[RetrievalCase, ...] = ()
    locator: tuple[LocatorCase, ...] = ()
    citation: tuple[CitationCase, ...] = ()
    trajectory: tuple[TrajectoryCase, ...] = ()
    coverage: tuple[CoverageCase, ...] = ()
    criterion: tuple[CriterionCase, ...] = ()
    image: tuple[ImageCase, ...] = ()


# ------------------------------------------------------------ per-case results

# Every ``label_*`` field below is sourced ONLY from the case file; a Jev
# probability/confidence never appears in these records, so no metric can
# accidentally use a model self-score as its reference.
@dataclass(frozen=True)
class RetrievalResult:
    case_id: str
    returned_ids: tuple[str, ...]
    relevant_ids: frozenset[str]
    k: int


@dataclass(frozen=True)
class LocatorResult:
    case_id: str
    expected_id: str
    expected_slot: int
    returned_ids: tuple[str, ...]


@dataclass(frozen=True)
class CitationResult:
    case_id: str
    label_supported: bool
    predicted_supported: bool | None


@dataclass(frozen=True)
class TrajectoryResult:
    case_id: str
    expected_action: str
    predicted_action: str | None
    anchor_preserved: bool


@dataclass(frozen=True)
class CoverageResult:
    case_id: str
    label_supported: bool
    predicted_supported: bool | None


@dataclass(frozen=True)
class CriterionResult:
    case_id: str
    criterion_id: str
    label_grade: int
    predicted_grade: int | None


@dataclass(frozen=True)
class ImageResult:
    case_id: str
    label_answer: str
    predicted_answer: str | None


# ------------------------------------------------------------------ pure metrics


def recall_at_k(
    returned_ids: Sequence[str], relevant_ids: Iterable[str], k: int
) -> float:
    """Fraction of the labelled relevant ids retrieved within the first ``k`` results.

    Computed from the case LABELS only. Empty ``relevant_ids`` is vacuously 1.0
    (nothing to recall), an empty ``returned_ids`` is 0.0, and ``k`` larger than the
    list is handled by clamping to the list length.

    Only ``returned_ids`` is order-sensitive (it is sliced to the top ``k``); the
    labelled ids are used purely as a membership set, which is why they are typed
    ``Iterable`` and the callers may pass the ``frozenset`` they store.
    """
    if k <= 0:
        raise ValueError("k must be positive.")
    relevant = frozenset(relevant_ids)
    if not relevant:
        return 1.0
    return len(relevant.intersection(returned_ids[:k])) / len(relevant)


def mrr(returned_ids: Sequence[str], relevant_ids: Iterable[str]) -> float:
    """Reciprocal rank of the first labelled-relevant id (ties resolve by position).

    As in ``recall_at_k``, the ranking comes from ``returned_ids`` (order-sensitive)
    while the labelled ids are only tested for membership.
    """
    relevant = frozenset(relevant_ids)
    for index, candidate_id in enumerate(returned_ids, start=1):
        if candidate_id in relevant:
            return 1.0 / index
    return 0.0


def locator_accuracy(results: Sequence[LocatorResult]) -> float:
    """Fraction of locator cases whose expected exact target holds its expected slot.

    The label is the expected chunk id plus the 0-based slot it must occupy; exact
    targets keep their slot in the shipped retrieval path.
    """
    if not results:
        return 0.0
    hits = sum(
        1
        for result in results
        if 0 <= result.expected_slot < len(result.returned_ids)
        and result.returned_ids[result.expected_slot] == result.expected_id
    )
    return hits / len(results)


def citation_support_accuracy(results: Sequence[CitationResult]) -> float:
    """Fraction of citation cases where the support prediction matches the label.

    ``predicted_supported=None`` (unresolved / deterministic withholding) is never a
    correct prediction.
    """
    if not results:
        return 0.0
    correct = sum(
        1
        for result in results
        if result.predicted_supported is not None
        and result.predicted_supported == result.label_supported
    )
    return correct / len(results)


def unsupported_claim_rate(results: Sequence[CitationResult]) -> float:
    """Fraction of claims the harness does NOT cite as supported.

    Only ``predicted_supported is True`` counts as supported; False and None
    (withheld / unresolved) are conservative and counted as unsupported.
    """
    if not results:
        return 0.0
    return sum(1 for result in results if result.predicted_supported is not True) / len(
        results
    )


def mainline_recovery_rate(results: Sequence[TrajectoryResult]) -> float:
    """Fraction of trajectories that recover the labelled mainline action and anchor."""
    if not results:
        return 0.0
    recovered = sum(
        1
        for result in results
        if result.anchor_preserved and result.predicted_action == result.expected_action
    )
    return recovered / len(results)


def coverage_confusion(results: Sequence[CoverageResult]) -> dict[str, int | float]:
    """Binary confusion for coverage; positive = "supported".

    A ``None`` prediction (deterministic fallback) is treated as "not supported":
    the harness withholds a coverage claim, which can never be a false positive.
    """
    tp = fp = fn = tn = 0
    for result in results:
        predicted = result.predicted_supported is True
        if result.label_supported and predicted:
            tp += 1
        elif not result.label_supported and predicted:
            fp += 1
        elif result.label_supported and not predicted:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 8),
        "recall": round(recall, 8),
    }


def criterion_error(results: Sequence[CriterionResult]) -> float:
    """Mean absolute error across rubric criteria.

    Labels are graded 0 (accurate) / 1 (partially) / 2 (not). A predicted grade of
    ``None`` (NEEDS_REVIEW / deterministic fallback) contributes a full error of 1.0.
    """
    if not results:
        return 0.0
    errors = [
        abs(result.label_grade - result.predicted_grade)
        if result.predicted_grade is not None
        else 1.0
        for result in results
    ]
    return sum(errors) / len(errors)


def image_answer_accuracy(results: Sequence[ImageResult]) -> float:
    """Fraction of image cases whose predicted answer matches the ground-truth label.

    Comparison is case-insensitive with whitespace collapsed; a missing prediction
    (``None``) is wrong. The ground truth is the case LABEL, never a model confidence.
    """
    if not results:
        return 0.0
    correct = sum(
        1
        for result in results
        if result.predicted_answer is not None
        and _normalize_answer(result.predicted_answer) == _normalize_answer(result.label_answer)
    )
    return correct / len(results)


def latency_summary(values: Sequence[float]) -> dict[str, float | None]:
    """p50/p95 latency over a sample; both ``None`` when the sample is empty."""
    ordered = sorted(values)
    if not ordered:
        return {"p50": None, "p95": None}
    return {"p50": _percentile(ordered, 0.5), "p95": _percentile(ordered, 0.95)}


def cost_split(
    *,
    deepseek_input_tokens: int = 0,
    deepseek_output_tokens: int = 0,
    jev_calls: int = 0,
    embedding_tokens: int = 0,
    deepseek_input_price_per_million: float = 0.0,
    deepseek_output_price_per_million: float = 0.0,
    jev_price_per_call: float = 0.0,
    embedding_price_per_million: float = 0.0,
) -> dict[str, float]:
    """Split cost across DeepSeek / Jev / embedding from measured usage and prices."""
    deepseek = (
        deepseek_input_tokens * deepseek_input_price_per_million
        + deepseek_output_tokens * deepseek_output_price_per_million
    ) / 1_000_000
    jev = jev_calls * jev_price_per_call
    embedding = embedding_tokens * embedding_price_per_million / 1_000_000
    return {
        "deepseek": round(deepseek, 8),
        "jev": round(jev, 8),
        "embedding": round(embedding, 8),
    }


def failure_rate(outcomes: Sequence[str]) -> float:
    """Fraction of Jev receipt outcomes that are failures (empty -> 0.0)."""
    if not outcomes:
        return 0.0
    return sum(1 for outcome in outcomes if outcome in FAILURE_OUTCOMES) / len(outcomes)


def _percentile(ordered: Sequence[float], percentile: float) -> float:
    """Linear-interpolated percentile over an already-sorted, non-empty sample."""
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 3)


def _normalize_answer(text: str) -> str:
    return " ".join(text.casefold().split())


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


# ---------------------------------------------------------------------- loader


def load_ablation_cases(path: Path) -> AblationCaseSet:
    """Load and validate the case file, raising a clear error naming the offending entry."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read ablation case file {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError("Ablation case file must be a JSON object.")
    status = payload.get("dataset_status")
    if status not in _DATASET_STATUSES:
        raise ValueError(
            f"dataset_status must be one of {sorted(_DATASET_STATUSES)}, got {status!r}."
        )
    cases_payload = payload.get("cases")
    if not isinstance(cases_payload, dict):
        raise ValueError("Ablation case file must contain a 'cases' object.")
    dataset = AblationCaseSet(
        dataset_status=str(status),
        retrieval=tuple(_parse_retrieval(cases_payload.get("retrieval") or [])),
        locator=tuple(_parse_locator(cases_payload.get("locator") or [])),
        citation=tuple(_parse_citation(cases_payload.get("citation") or [])),
        trajectory=tuple(_parse_trajectory(cases_payload.get("trajectory") or [])),
        coverage=tuple(_parse_coverage(cases_payload.get("coverage") or [])),
        criterion=tuple(_parse_criterion(cases_payload.get("criterion") or [])),
        image=tuple(_parse_image(cases_payload.get("image") or [])),
    )
    _validate_cross_family(dataset)
    return dataset


def _label(raw: Any, family: str, index: int) -> str:
    rid = raw.get("id") if isinstance(raw, dict) else None
    return f"{family} case {rid!r}" if rid else f"{family} case #{index}"


def _require_dict(raw: Any, where: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{where}: expected an object, got {type(raw).__name__}.")
    return raw


def _require_str(raw: dict[str, Any], key: str, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: field {key!r} must be a non-empty string.")
    return value


def _require_int(raw: dict[str, Any], key: str, where: str, *, minimum: int) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{where}: field {key!r} must be an integer >= {minimum}.")
    return value


def _require_bool(raw: dict[str, Any], key: str, where: str) -> bool:
    value = raw.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{where}: field {key!r} must be a boolean.")
    return value


def _parse_candidates(raw: Any, where: str) -> tuple[RetrievalCandidate, ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{where}: 'candidates' must be a non-empty list.")
    candidates: list[RetrievalCandidate] = []
    for index, entry in enumerate(raw):
        entry_where = f"{where}: candidates[{index}]"
        entry = _require_dict(entry, entry_where)
        candidates.append(
            RetrievalCandidate(
                id=_require_str(entry, "id", entry_where),
                text=_require_str(entry, "text", entry_where),
                filename=_require_str(entry, "filename", entry_where),
                locator_type=_require_str(entry, "locator_type", entry_where),
                locator_value=_require_str(entry, "locator_value", entry_where),
                section=str(entry.get("section") or ""),
                scope=str(entry.get("scope") or "official"),
                rank=_require_int(entry, "rank", entry_where, minimum=1),
            )
        )
    if len({candidate.id for candidate in candidates}) != len(candidates):
        raise ValueError(f"{where}: candidate ids must be unique.")
    if any(candidate.scope not in {"official", "mine"} for candidate in candidates):
        raise ValueError(f"{where}: candidate scope must be 'official' or 'mine'.")
    return tuple(candidates)


def _parse_retrieval(raw: Any) -> list[RetrievalCase]:
    if not isinstance(raw, list):
        raise ValueError("'cases.retrieval' must be a list.")
    cases: list[RetrievalCase] = []
    for index, entry in enumerate(raw):
        where = _label(entry, "retrieval", index)
        entry = _require_dict(entry, where)
        candidates = _parse_candidates(entry.get("candidates"), where)
        candidate_ids = {candidate.id for candidate in candidates}
        relevant_raw = entry.get("relevant_ids")
        if not isinstance(relevant_raw, list) or not relevant_raw:
            raise ValueError(f"{where}: 'relevant_ids' must be a non-empty list.")
        relevant_ids = frozenset(str(item) for item in relevant_raw)
        unknown_relevant = sorted(relevant_ids - candidate_ids)
        if unknown_relevant:
            raise ValueError(
                f"{where}: relevant_ids references unknown candidates {unknown_relevant}."
            )
        graded_raw = entry.get("graded_relevance") or {}
        if not isinstance(graded_raw, dict):
            raise ValueError(f"{where}: 'graded_relevance' must be an object.")
        graded_relevance = {
            str(key): int(value) for key, value in graded_raw.items()
        }
        unknown_graded = sorted(set(graded_relevance) - candidate_ids)
        if unknown_graded:
            raise ValueError(
                f"{where}: graded_relevance references unknown candidates {unknown_graded}."
            )
        cases.append(
            RetrievalCase(
                id=_require_str(entry, "id", where),
                query=_require_str(entry, "query", where),
                top_k=_require_int(entry, "top_k", where, minimum=1),
                candidates=candidates,
                relevant_ids=relevant_ids,
                graded_relevance=graded_relevance,
            )
        )
    _ensure_unique([case.id for case in cases], "retrieval")
    return cases


def _parse_locator(raw: Any) -> list[LocatorCase]:
    if not isinstance(raw, list):
        raise ValueError("'cases.locator' must be a list.")
    cases: list[LocatorCase] = []
    for index, entry in enumerate(raw):
        where = _label(entry, "locator", index)
        entry = _require_dict(entry, where)
        candidates = _parse_candidates(entry.get("candidates"), where)
        candidate_ids = {candidate.id for candidate in candidates}
        expected_id = _require_str(entry, "expected_id", where)
        if expected_id not in candidate_ids:
            raise ValueError(f"{where}: expected_id {expected_id!r} is not a candidate id.")
        top_k = _require_int(entry, "top_k", where, minimum=1)
        expected_slot = _require_int(entry, "expected_slot", where, minimum=0)
        if expected_slot >= top_k:
            raise ValueError(f"{where}: expected_slot must be < top_k ({top_k}).")
        cases.append(
            LocatorCase(
                id=_require_str(entry, "id", where),
                query=_require_str(entry, "query", where),
                top_k=top_k,
                candidates=candidates,
                expected_id=expected_id,
                expected_slot=expected_slot,
            )
        )
    _ensure_unique([case.id for case in cases], "locator")
    return cases


def _parse_citation(raw: Any) -> list[CitationCase]:
    if not isinstance(raw, list):
        raise ValueError("'cases.citation' must be a list.")
    cases: list[CitationCase] = []
    for index, entry in enumerate(raw):
        where = _label(entry, "citation", index)
        entry = _require_dict(entry, where)
        cases.append(
            CitationCase(
                id=_require_str(entry, "id", where),
                claim=_require_str(entry, "claim", where),
                source_span=_require_str(entry, "source_span", where),
                source_version=_require_str(entry, "source_version", where),
                task_scope=_require_str(entry, "task_scope", where),
                label_supported=_require_bool(entry, "label_supported", where),
            )
        )
    _ensure_unique([case.id for case in cases], "citation")
    return cases


def _parse_trajectory(raw: Any) -> list[TrajectoryCase]:
    if not isinstance(raw, list):
        raise ValueError("'cases.trajectory' must be a list.")
    actions = _intent_actions()
    cases: list[TrajectoryCase] = []
    for index, entry in enumerate(raw):
        where = _label(entry, "trajectory", index)
        entry = _require_dict(entry, where)
        fixed_anchor = entry.get("fixed_anchor")
        if not isinstance(fixed_anchor, dict):
            raise ValueError(f"{where}: 'fixed_anchor' must be an object.")
        turns_raw = entry.get("turns")
        if not isinstance(turns_raw, list) or not turns_raw:
            raise ValueError(f"{where}: 'turns' must be a non-empty list.")
        turns: list[TrajectoryTurn] = []
        for turn_index, turn_raw in enumerate(turns_raw):
            turn_where = f"{where}: turns[{turn_index}]"
            turn_raw = _require_dict(turn_raw, turn_where)
            expected = _require_str(turn_raw, "expected_action", turn_where)
            if expected not in actions:
                raise ValueError(
                    f"{turn_where}: expected_action {expected!r} not in {sorted(actions)}."
                )
            turns.append(
                TrajectoryTurn(
                    message=_require_str(turn_raw, "message", turn_where),
                    expected_action=expected,
                )
            )
        expected_action = _require_str(entry, "expected_action", where)
        if expected_action not in actions:
            raise ValueError(
                f"{where}: expected_action {expected_action!r} not in {sorted(actions)}."
            )
        active = entry.get("active_assessment")
        if active is not None and not isinstance(active, str):
            raise ValueError(f"{where}: 'active_assessment' must be a string or null.")
        filterable_raw = entry.get("filterable_segments", [])
        if not isinstance(filterable_raw, list) or not all(
            isinstance(item, str) for item in filterable_raw
        ):
            raise ValueError(f"{where}: 'filterable_segments' must be a list of strings.")
        cases.append(
            TrajectoryCase(
                id=_require_str(entry, "id", where),
                anchor=_require_str(entry, "anchor", where),
                fixed_anchor=fixed_anchor,
                current_mode=_require_str(entry, "current_mode", where),
                active_assessment=active,
                current_task=_require_str(entry, "current_task", where),
                remaining_scope=_require_str(entry, "remaining_scope", where),
                turns=tuple(turns),
                expected_action=expected_action,
                filterable_segments=tuple(filterable_raw),
            )
        )
    _ensure_unique([case.id for case in cases], "trajectory")
    return cases


def _parse_coverage(raw: Any) -> list[CoverageCase]:
    if not isinstance(raw, list):
        raise ValueError("'cases.coverage' must be a list.")
    cases: list[CoverageCase] = []
    for index, entry in enumerate(raw):
        where = _label(entry, "coverage", index)
        entry = _require_dict(entry, where)
        required_item = entry.get("required_item")
        if not isinstance(required_item, dict) or "item_id" not in required_item:
            raise ValueError(f"{where}: 'required_item' must be an object with 'item_id'.")
        cases.append(
            CoverageCase(
                id=_require_str(entry, "id", where),
                required_item=required_item,
                accepted_evidence=_require_str(entry, "accepted_evidence", where),
                spec_version=_require_str(entry, "spec_version", where),
                label_supported=_require_bool(entry, "label_supported", where),
            )
        )
    _ensure_unique([case.id for case in cases], "coverage")
    return cases


_CRITERION_LABEL_GRADES = {"accurate": 0, "partially": 1, "not": 2}


def _parse_criterion(raw: Any) -> list[CriterionCase]:
    if not isinstance(raw, list):
        raise ValueError("'cases.criterion' must be a list.")
    cases: list[CriterionCase] = []
    for index, entry in enumerate(raw):
        where = _label(entry, "criterion", index)
        entry = _require_dict(entry, where)
        frozen_question = entry.get("frozen_question")
        if not isinstance(frozen_question, dict):
            raise ValueError(f"{where}: 'frozen_question' must be an object.")
        criteria_raw = entry.get("criteria")
        if not isinstance(criteria_raw, list) or not criteria_raw:
            raise ValueError(f"{where}: 'criteria' must be a non-empty list.")
        criteria: list[CriterionItem] = []
        for item_index, item_raw in enumerate(criteria_raw):
            item_where = f"{where}: criteria[{item_index}]"
            item_raw = _require_dict(item_raw, item_where)
            criterion = item_raw.get("criterion")
            if not isinstance(criterion, dict):
                raise ValueError(f"{item_where}: 'criterion' must be an object.")
            label = _require_str(item_raw, "label", item_where)
            if label not in _CRITERION_LABEL_GRADES:
                raise ValueError(
                    f"{item_where}: label {label!r} not in {sorted(_CRITERION_LABEL_GRADES)}."
                )
            alternatives = item_raw.get("acceptable_alternatives") or []
            if not isinstance(alternatives, list) or any(
                not isinstance(item, str) for item in alternatives
            ):
                raise ValueError(
                    f"{item_where}: 'acceptable_alternatives' must be a list of strings."
                )
            criteria.append(
                CriterionItem(
                    id=_require_str(item_raw, "id", item_where),
                    criterion=criterion,
                    label=label,
                    acceptable_alternatives=tuple(alternatives),
                )
            )
        cases.append(
            CriterionCase(
                id=_require_str(entry, "id", where),
                frozen_question=frozen_question,
                reference_solution=_require_str(entry, "reference_solution", where),
                student_answer=_require_str(entry, "student_answer", where),
                deterministic_verification=_require_str(entry, "deterministic_verification", where),
                criteria=tuple(criteria),
            )
        )
    _ensure_unique([case.id for case in cases], "criterion")
    return cases


def _parse_image(raw: Any) -> list[ImageCase]:
    if not isinstance(raw, list):
        raise ValueError("'cases.image' must be a list.")
    cases: list[ImageCase] = []
    for index, entry in enumerate(raw):
        where = _label(entry, "image", index)
        entry = _require_dict(entry, where)
        cases.append(
            ImageCase(
                id=_require_str(entry, "id", where),
                prompt=_require_str(entry, "prompt", where),
                ground_truth_answer=_require_str(entry, "ground_truth_answer", where),
            )
        )
    _ensure_unique([case.id for case in cases], "image")
    return cases


def _ensure_unique(ids: list[str], family: str) -> None:
    if len(ids) != len(set(ids)):
        raise ValueError(f"{family} case ids must be unique.")


def _validate_cross_family(dataset: AblationCaseSet) -> None:
    # Nothing cross-family to validate today; kept as a single choke point so a
    # future rule (e.g. a global id namespace) lands in exactly one place.
    return None


# --------------------------------------------------------------- cost estimation


def estimate_input_token_ceilings(
    cases: AblationCaseSet,
    arm: str,
    *,
    protocol_overhead_tokens: int,
) -> list[int]:
    """Return a worst-case input-token ceiling per would-be Jev call for ``arm``.

    This is pure (no network, no transport): it walks the case families and, for
    every decision key the arm turns on, adds one conservative ceiling per call the
    runner would make, using the existing
    ``app.evaluation.model_benchmark.conservative_input_token_ceiling`` helper
    (one UTF-8 byte per token, plus protocol overhead).
    """
    on_keys = frozenset(key for key, mode in arm_modes(arm).items() if mode == "on")
    ceilings: list[int] = []

    def add(instructions: str, prompt: str) -> None:
        ceilings.append(
            conservative_input_token_ceiling(
                instructions, prompt, protocol_overhead_tokens=protocol_overhead_tokens
            )
        )

    if "retrieval.support.v1" in on_keys:
        retrieval_like: tuple[RetrievalCase | LocatorCase, ...] = (
            *cases.retrieval, *cases.locator,
        )
        for case in retrieval_like:
            for candidate in case.candidates:
                add("", f"{case.query}\n{candidate.text}")
    if "intent.next_action.v1" in on_keys:
        for trajectory_case in cases.trajectory:
            for turn in trajectory_case.turns:
                add("", turn.message)
    if "context.keep_segment.v1" in on_keys:
        for trajectory_case in cases.trajectory:
            add(
                "",
                f"{trajectory_case.anchor}\n{trajectory_case.current_task}"
                f"\n{trajectory_case.remaining_scope}",
            )
    if "coverage.item_support.v1" in on_keys:
        for coverage_case in cases.coverage:
            add("", coverage_case.accepted_evidence)
    if "assessment.criterion_review.v1" in on_keys:
        for criterion_case in cases.criterion:
            for _item in criterion_case.criteria:
                add("", f"{criterion_case.reference_solution}\n{criterion_case.student_answer}")
    return ceilings


# -------------------------------------------------------------------- transport


def deterministic_fake_responder(call: JevCall) -> JevResult:
    """A fixed, deliberately non-informative responder for offline plumbing runs.

    It returns the first authorized Choice candidate, the lowest Score level, and a
    ``noul`` probability of 0.0. Runs using it are tagged NON_INTERPRETABLE_PLUMBING_ONLY,
    so these values can never be read as a quality signal.
    """
    answers: dict[str, JevAnswer] = {}
    for key, question in call.questions.items():
        if question.primitive == Primitive.CHOICE:
            answers[key] = JevAnswer(choice=next(iter(question.criteria or {}), None))
        elif question.primitive == Primitive.SCORE:
            answers[key] = JevAnswer(score="0")
        else:
            answers[key] = JevAnswer(noul=0.0)
    return JevResult(answers=answers)


def make_temp_receipt_store() -> tuple[SqlReceiptStore, Any]:
    """Create a throwaway SQLite database holding ONLY the Jev receipt ledger."""
    from app.config import Settings
    from app.db import Database

    tmp_dir = Path(tempfile.mkdtemp(prefix="jev-ablation-"))
    settings = Settings(
        database_path=tmp_dir / "receipts.sqlite3",
        upload_dir=tmp_dir / "uploads",
        app_env="test",
        v3_enabled=True,
        rag_provider_mode="deterministic",
    )
    database = Database(settings)
    database.upload_dir.mkdir(parents=True, exist_ok=True)
    migration = Path(__file__).parents[2] / "migrations" / "028_jev_decision_receipts.sql"
    with database.connect() as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version INTEGER PRIMARY KEY, name TEXT NOT NULL)"
        )
        connection.executescript(migration.read_text(encoding="utf-8"))
    return SqlReceiptStore(database), database


# ---------------------------------------------------------------------- runner


@dataclass(frozen=True)
class _Hit:
    chunk_id: str
    document_id: str
    filename: str
    locator_type: str
    locator_value: str
    section: str
    content: str


def _hit_from(candidate: RetrievalCandidate) -> _Hit:
    return _Hit(
        chunk_id=candidate.id,
        document_id=candidate.id,
        filename=candidate.filename,
        locator_type=candidate.locator_type,
        locator_value=candidate.locator_value,
        section=candidate.section,
        content=candidate.text,
    )


def run_ablation(
    cases: AblationCaseSet,
    arm: str,
    *,
    transport: Transport,
    receipt_store: ReceiptStore | None = None,
    image_predictor: Callable[[ImageCase], str | None] | None = None,
    coverage_baseline: Callable[[CoverageCase], bool | None] | None = None,
    criterion_baseline: Callable[[CriterionCase, Any], int | None] | None = None,
    citation_baseline: Callable[[CitationCase], bool | None] | None = None,
    owner_user_id: str = "ablation-harness",
) -> dict[str, Any]:
    """Execute one arm over ``cases`` through the real wired code paths.

    The only side effect is Jev receipts in ``receipt_store`` (or a throwaway temp
    database when none is supplied); no learning/grade/coverage state is written.

    ``coverage_baseline`` / ``criterion_baseline`` / ``citation_baseline`` are the
    production predictors for the non-Jev side of those families (the existing
    reviewer, the existing grader, the existing citation check). When they are not
    injected, that family's non-Jev baseline is an **abstention**, which is not what
    the product ships — the run records it under ``placeholder_baselines`` and
    :func:`compare_arms` refuses to call such a comparison interpretable. Explicit
    commands are always routed by :func:`route_explicit_command`, which is the real
    deterministic behaviour and spends no Jev call.
    """
    modes = arm_modes(arm)
    if receipt_store is None:
        receipt_store, _ = make_temp_receipt_store()
    gateway = JevGateway(
        transport=transport,
        catalog=load_catalog(),
        modes=modes,
        receipt_store=receipt_store,
    )
    service = SemanticDecisionService(gateway)
    scope = service.scope(owner_user_id=owner_user_id, authorization_scope="ablation")

    retrieval_results: list[RetrievalResult] = []
    locator_results: list[LocatorResult] = []
    for retrieval_case in cases.retrieval:
        returned = _run_retrieval(retrieval_case, service, scope)
        retrieval_results.append(
            RetrievalResult(
                retrieval_case.id,
                tuple(returned),
                retrieval_case.relevant_ids,
                retrieval_case.top_k,
            )
        )
    for locator_case in cases.locator:
        returned = _run_retrieval(locator_case, service, scope)
        locator_results.append(
            LocatorResult(
                locator_case.id,
                locator_case.expected_id,
                locator_case.expected_slot,
                tuple(returned),
            )
        )

    citation_results: list[CitationResult] = []
    for citation_case in cases.citation:
        decision = service.noul(
            "source.supports_claim.v1",
            state={
                "claim": citation_case.claim,
                "source_span": citation_case.source_span,
                "source_version": citation_case.source_version,
                "task_scope": citation_case.task_scope,
            },
            caller_role="citation",
            cache_scope=scope,
        )
        predicted = (
            bool(decision.value >= 0.5)
            if decision.used_jev and isinstance(decision.value, (int, float))
            else (citation_baseline(citation_case) if citation_baseline is not None else None)
        )
        citation_results.append(
            CitationResult(citation_case.id, citation_case.label_supported, predicted)
        )

    trajectory_results: list[TrajectoryResult] = []
    filterable_kept = 0
    filterable_considered = 0
    for trajectory_case in cases.trajectory:
        final_action: str | None = None
        for turn in trajectory_case.turns:
            # Explicit commands ("继续" / "暂停" / "做一题" / "交卷" ...) are answered by
            # the deterministic router and never spend a Jev call. This is the shipped
            # behaviour, so arm A's baseline for them is real, not a placeholder.
            explicit = route_explicit_command(
                turn.message,
                current_mode=trajectory_case.current_mode,
                active_assessment=trajectory_case.active_assessment,
            )
            if explicit is not None:
                final_action = explicit
                continue
            decision = service.next_action(
                message=turn.message,
                fixed_anchor=trajectory_case.fixed_anchor,
                current_mode=trajectory_case.current_mode,
                active_assessment=trajectory_case.active_assessment,
                caller_role="intent",
                cache_scope=scope,
            )
            final_action = decision.value
        # The fixed anchor is preserved unconditionally: the product never lets any
        # semantic decision drop it, and neither may this harness. Jev is only asked
        # about the *filterable* class (resolved follow-ups, duplicate explanations,
        # unrelated asides) — see the module authority rules.
        anchor_preserved = True
        for segment in trajectory_case.filterable_segments:
            filterable_considered += 1
            if service.keep_segment(
                segment=segment,
                current_task=trajectory_case.current_task,
                fixed_anchor=trajectory_case.fixed_anchor,
                remaining_scope=trajectory_case.remaining_scope,
                caller_role="intent",
                cache_scope=scope,
            ):
                filterable_kept += 1
        trajectory_results.append(
            TrajectoryResult(
                trajectory_case.id,
                trajectory_case.expected_action,
                final_action,
                anchor_preserved,
            )
        )

    coverage_results: list[CoverageResult] = []
    for coverage_case in cases.coverage:
        decision = service.choice(
            "coverage.item_support.v1",
            candidate_ids=("SUPPORTED", "PARTIAL", "UNSUPPORTED", "UNCERTAIN"),
            state={
                "saved_delivery": coverage_case.accepted_evidence,
                "required_item": coverage_case.required_item,
                "valid_spans": [],
                "node_spec_version": coverage_case.spec_version,
            },
            caller_role="coverage",
            cache_scope=scope,
            deterministic="UNCERTAIN",
        )
        predicted = (
            decision.value == "SUPPORTED"
            if decision.used_jev
            else (coverage_baseline(coverage_case) if coverage_baseline is not None else None)
        )
        coverage_results.append(
            CoverageResult(coverage_case.id, coverage_case.label_supported, predicted)
        )

    criterion_results: list[CriterionResult] = []
    for criterion_case in cases.criterion:
        for item in criterion_case.criteria:
            decision = service.criterion_review(
                frozen_question=criterion_case.frozen_question,
                criterion=item.criterion,
                reference_solution=criterion_case.reference_solution,
                student_answer=criterion_case.student_answer,
                deterministic_verification=criterion_case.deterministic_verification,
                candidate_answer_spans=list(item.acceptable_alternatives),
                caller_role="assessment",
                cache_scope=scope,
            )
            predicted_grade = (
                _prediction_grades.get(decision.value)
                if decision.used_jev
                else (
                    criterion_baseline(criterion_case, item)
                    if criterion_baseline is not None
                    else None
                )
            )
            criterion_results.append(
                CriterionResult(
                    criterion_case.id, item.id, _CRITERION_LABEL_GRADES[item.label], predicted_grade
                )
            )

    image_results: list[ImageResult] = []
    for image_case in cases.image:
        predicted_answer = image_predictor(image_case) if image_predictor is not None else None
        image_results.append(
            ImageResult(image_case.id, image_case.ground_truth_answer, predicted_answer)
        )

    # Which families compare against a placeholder instead of the shipped pipeline?
    # Explicit commands are routed for real, so `trajectory` is only a placeholder when
    # a turn was NOT an explicit command (its baseline then falls back to the service
    # default). Recording this is what stops a comparison from looking interpretable
    # while arm A is not the product.
    placeholder_baselines: list[str] = []
    if coverage_baseline is None and coverage_results:
        placeholder_baselines.append("coverage:abstention")
    if criterion_baseline is None and criterion_results:
        placeholder_baselines.append("criterion:abstention")
    if citation_baseline is None and citation_results:
        placeholder_baselines.append("citation:abstention")
    non_explicit_turns = sum(
        1
        for case in cases.trajectory
        for turn in case.turns
        if route_explicit_command(
            turn.message,
            current_mode=case.current_mode,
            active_assessment=case.active_assessment,
        )
        is None
    )
    if non_explicit_turns:
        placeholder_baselines.append(f"trajectory:OTHER-default({non_explicit_turns} turns)")

    outcomes = _receipt_outcomes(receipt_store)
    latencies = _receipt_latencies(receipt_store)
    jev_calls = getattr(transport, "calls", None)
    jev_call_count = len(jev_calls) if jev_calls is not None else 0

    # Honesty invariant (reviewers look here): every metric below reads ONLY
    # label-bearing fields (``label_*`` / ``relevant_ids`` / ``expected_*``) from the
    # case file, or receipt-derived outcomes/latencies/call counts. A Jev Score/Noul
    # probability or confidence is never a label, a grade, or an accuracy reference
    # anywhere in this module — the ``Result`` dataclasses do not even carry one.
    kind = transport_kind(transport)
    metrics = {
        "recall_at_k": _mean(
            [recall_at_k(r.returned_ids, r.relevant_ids, r.k) for r in retrieval_results]
        ),
        "mrr": _mean([mrr(r.returned_ids, r.relevant_ids) for r in retrieval_results]),
        "locator_accuracy": locator_accuracy(locator_results),
        "citation_support_accuracy": citation_support_accuracy(citation_results),
        "unsupported_claim_rate": unsupported_claim_rate(citation_results),
        "mainline_recovery_rate": mainline_recovery_rate(trajectory_results),
        "coverage_confusion": coverage_confusion(coverage_results),
        "criterion_error": criterion_error(criterion_results),
        "image_answer_accuracy": image_answer_accuracy(image_results),
        "latency_summary": latency_summary(latencies),
        "cost_split": cost_split(jev_calls=jev_call_count),
        "failure_rate": failure_rate(outcomes),
    }
    return {
        "arm": arm,
        "modes": modes,
        "transport": kind,
        "dataset_status": cases.dataset_status,
        "interpretation": interpretation_for(kind, cases.dataset_status),
        "case_counts": {
            "retrieval": len(retrieval_results),
            "locator": len(locator_results),
            "citation": len(citation_results),
            "trajectory": len(trajectory_results),
            "coverage": len(coverage_results),
            "criterion": len(criterion_results),
            "image": len(image_results),
        },
        "jev_calls": jev_call_count,
        "placeholder_baselines": placeholder_baselines,
        "explicit_command_turns_no_jev_call": sum(
            1
            for case in cases.trajectory
            for turn in case.turns
            if route_explicit_command(
                turn.message,
                current_mode=case.current_mode,
                active_assessment=case.active_assessment,
            )
            is not None
        ),
        "filterable_segments": {
            "considered": filterable_considered,
            "kept": filterable_kept,
            "note": (
                "Informational only: fixed anchors are never offered to Jev, so this is "
                "not a quality metric."
            ),
        },
        "metrics": metrics,
        "per_case": {
            "retrieval": [_result_asdict(r) for r in retrieval_results],
            "locator": [_result_asdict(r) for r in locator_results],
            "citation": [_result_asdict(r) for r in citation_results],
            "trajectory": [_result_asdict(r) for r in trajectory_results],
            "coverage": [_result_asdict(r) for r in coverage_results],
            "criterion": [_result_asdict(r) for r in criterion_results],
            "image": [_result_asdict(r) for r in image_results],
        },
    }


_prediction_grades = {"SATISFIED": 0, "PARTIAL": 1, "NOT_SATISFIED": 2}


def _run_retrieval(
    case: RetrievalCase | LocatorCase,
    service: SemanticDecisionService,
    scope: Any,
) -> list[str]:
    by_scope: dict[str, list[RetrievalCandidate]] = {}
    for candidate in case.candidates:
        by_scope.setdefault(candidate.scope, []).append(candidate)
    groups = [
        ScopedCandidates(
            scope=scope_name,
            hits=[_hit_from(candidate) for candidate in sorted(cands, key=lambda c: c.rank)],
        )
        for scope_name, cands in by_scope.items()
    ]
    fused = fuse_scoped_candidates(
        groups,
        top_k=case.top_k,
        exact_targets=exact_targets_from_query(case.query),
        max_candidates=len(case.candidates),
    )
    fused = service.rerank_retrieval(
        fused, query=case.query, caller_role="retrieval", cache_scope=scope
    )
    return [entry.chunk_id for entry in fused]


def _receipt_outcomes(receipt_store: ReceiptStore) -> list[str]:
    database = getattr(receipt_store, "database", None)
    if database is None:
        return []
    with database.connect() as connection:
        rows = connection.execute("SELECT outcome FROM jev_decision_receipts").fetchall()
    return [str(row["outcome"]) for row in rows]


def _receipt_latencies(receipt_store: ReceiptStore) -> list[float]:
    database = getattr(receipt_store, "database", None)
    if database is None:
        return []
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT latency_ms FROM jev_decision_receipts WHERE latency_ms IS NOT NULL"
        ).fetchall()
    return [float(row["latency_ms"]) for row in rows]


def _result_asdict(result: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field_name in getattr(result, "__dataclass_fields__", {}):
        value = getattr(result, field_name)
        if isinstance(value, frozenset):
            value = sorted(value)
        elif isinstance(value, tuple):
            value = list(value)
        payload[field_name] = value
    return payload


# ------------------------------------------------------------------ comparison


def compare_arms(
    runs: Mapping[str, dict[str, Any]], *, request_quality: bool = False
) -> dict[str, Any]:
    """Compare arm run summaries, refusing any improvement verdict from fake/unlabelled runs.

    * any ``deterministic_fake`` run -> ``verdict="NOT_INTERPRETABLE"`` (no improvement
      verdict), and ``request_quality=True`` raises ``ValueError``.
    * live but unlabelled dataset -> ``verdict="NOT_INTERPRETABLE"`` (refuse to label it
      interpretable), and ``request_quality=True`` raises ``ValueError``.
    * any arm whose non-Jev baseline is a placeholder (abstention or the ``OTHER``
      default because no production baseline predictor was injected) ->
      ``verdict="NOT_INTERPRETABLE"``, because comparing Jev against a baseline that the
      product never ships would overstate the effect. Inject the real baselines to lift
      this refusal.
    * live + ``LABELLED_DATASET`` + real baselines -> ``verdict="INTERPRETABLE"`` with the
      factual metric comparison; no improvement claim is made here — non-inferiority is
      judged against the frozen gate, outside this module.
    """
    if not runs:
        raise ValueError("compare_arms requires at least one run.")
    transports = {str(run.get("transport")) for run in runs.values()}
    statuses = {str(run.get("dataset_status")) for run in runs.values()}
    has_fake = TRANSPORT_FAKE in transports
    if has_fake:
        if request_quality:
            raise ValueError(
                "Refusing a quality claim: at least one arm used the deterministic "
                "fake transport, which is plumbing-only and not interpretable."
            )
        return {
            "verdict": "NOT_INTERPRETABLE",
            "reason": "deterministic_fake transport",
            "arms": sorted(runs),
        }
    if statuses != {DATASET_STATUS_LABELLED}:
        if request_quality:
            raise ValueError(
                "Refusing a quality claim: a labelled dataset (not the example file) "
                "is required for an interpretable live comparison."
            )
        return {
            "verdict": "NOT_INTERPRETABLE",
            "reason": "unlabelled dataset",
            "arms": sorted(runs),
        }
    placeholders = {
        arm: sorted(run.get("placeholder_baselines") or [])
        for arm, run in sorted(runs.items())
        if run.get("placeholder_baselines")
    }
    if placeholders:
        if request_quality:
            raise ValueError(
                "Refusing a quality claim: some families still compare against a "
                f"placeholder baseline {placeholders}. Inject the production "
                "baseline predictors so arm A is the pipeline the product ships."
            )
        return {
            "verdict": "NOT_INTERPRETABLE",
            "reason": "placeholder baseline (no production predictor injected)",
            "placeholder_baselines": placeholders,
            "arms": sorted(runs),
        }
    return {
        "verdict": "INTERPRETABLE",
        "note": (
            "Non-inferiority is judged against the frozen gate; this module makes no "
            "improvement claim."
        ),
        "metrics_by_arm": {
            arm: dict(run.get("metrics") or {}) for arm, run in sorted(runs.items())
        },
        "arms": sorted(runs),
    }
