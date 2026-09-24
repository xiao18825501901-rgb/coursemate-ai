"""A/B/C/D/E Jev ablation harness: pure metrics, honesty guards, offline plumbing.

The owner is replacing the TypeSafe Jev semantic layer with the self-hosted Jev
multilingual decision model. This module is the **measurement layer** for that
replacement: a real labelled dataset (``benchmarks/jev-judgments.dataset.json``),
a frozen split manifest (``benchmarks/jev-calibration.split.json``), and the
five-way ablation that stages Jev in over the shipped DeepSeek + deterministic
pipeline.

The 12 decision definitions and their authority rules are unchanged (the owner's
statement): the arm keys below reference the ids in
``app/jev/decision_catalog.json`` via ``app.jev.catalog.load_catalog``. This module
never hand-copies the definition list — it reads it live, exactly like
``app.evaluation.jev_ablation``.

Honesty contract (enforced in code, not prose — same semantics as the JeV harness):

* Metrics read LABELS only. A Jev ``confidence``/probability is never a label, a
  grade, or an accuracy reference; the per-case result dataclasses do not carry one.
* A fake transport run is tagged ``NON_INTERPRETABLE_PLUMBING_ONLY`` and
  :func:`compare_jev_arms` refuses an improvement verdict — and raises ``ValueError``
  when a caller asks for a quality claim from a fake run, an unlabelled dataset, or
  any family whose non-Jev baseline is a placeholder (abstention or a default
  constant) rather than the shipped deterministic path.
* The only truly interpretable verdict is ``INTERPRETABLE`` for a live run on a
  ``LABELLED_DATASET`` with real baselines injected. **That run has since happened** (rounds 91–92:
  248 live DeepSeek baseline calls over three runs, 53 live Jev decisions on the calibration split),
  and it is **unfavourable** — citation support improves while ``criterion_error`` and
  ``key_fact_retention`` regress, over 1–8 cases per metric. What this function still refuses is an
  improvement claim from a fake transport, an unlabelled dataset, or a placeholder baseline; the
  live-component arms (``--arm all-components``) remain ``NOT_RUN`` pending the budget decision in
  ``MINIMAL_OWNER_ACTION_CARD.md`` §1b. Reports: ``JEV_CALIBRATION_AND_ABLATION_REPORT.md`` §9,
  ``DEEPSEEK_LIVE_ACCEPTANCE.md`` §4.
* ``confidence`` is distribution concentration (see
  ``app.evaluation.jev_calibration``): it is never mapped to ``p_correct`` here.

Arms (versioned; the older A/B/C/D JeV report definitions are untouched):

* ``A`` = DeepSeek + deterministic fixes, **no Jev**.
* ``B`` = A + Jev retrieval rerank (``retrieval.support.v1``).
* ``C`` = B + Jev context/intent/pedagogy
  (``context.keep_segment.v1``, ``intent.next_action.v1``, ``pedagogy.next_method.v1``).
* ``D`` = C + Jev coverage/assessment criterion support
  (``coverage.item_support.v1``, ``assessment.criterion_review.v1``).
* ``E`` = D + Jev citation support / span selection
  (``source.supports_claim.v1``, ``source.select_span.v1``).

``template.match.v1``, ``exercise.prototype.v1``, ``graph.prerequisite.v1`` and
``corpus.quality.v1`` stay on the shipped DeepSeek/deterministic path in every arm
and are measured as separate families (classification, exercise, prerequisite,
corpus quality) — Jev never replaces them in this workstream.

Component arms (the six structured-enhancement modules, §10 of the task spec) are
separate on/off switches against the same arm-A baseline; they never replace or
redefine A–E and are **not** part of the strict nesting:

* ``M-EXTRACT``    = ExtractionVerification (``extraction.field_grounded.v1``)
* ``M-ENTITY``     = EntityResolution (``entity.relation.v1``)
* ``M-CONSISTENCY``= EvidenceConsistency (``evidence.consistency.v1``)
* ``M-CITATION``   = ClaimCitationAudit (``source.supports_claim.v1``,
  ``source.select_span.v1``)
* ``M-CAPABILITY`` = CapabilityRouter (``teaching.capability.v1``)
* ``M-TOOL``       = ToolIntentCheck (``tool.intent.v1``)

Each component arm reports, per module metric, either a reused A–E metric computed
from the labelled samples that exist for its decision definition, or the explicit
``INSUFFICIENT_SAMPLES`` marker when the dataset carries no such labels — it never
invents a number. Only ``M-CITATION`` has labelled samples in the frozen dataset
(``citation`` + ``span_selection`` families); the other five report
``INSUFFICIENT_SAMPLES`` for every module metric.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter as _perf_counter
from typing import Any

from app.evaluation.jev_ablation import (
    DATASET_STATUS_EXAMPLE,
    DATASET_STATUS_LABELLED,
    INTERPRETATION_INTERPRETABLE,
    INTERPRETATION_PLUMBING,
    INTERPRETATION_UNLABELLED,
    TRANSPORT_FAKE,
    TRANSPORT_LIVE,
    CitationResult,
    CoverageResult,
    CriterionResult,
    ImageResult,
    LocatorResult,
    RetrievalResult,
    TrajectoryResult,
    citation_support_accuracy,
    compare_arms,
    coverage_confusion,
    criterion_error,
    image_answer_accuracy,
    latency_summary,
    locator_accuracy,
    mainline_recovery_rate,
    mrr,
    recall_at_k,
    unsupported_claim_rate,
)
from app.jev.catalog import Primitive, load_catalog
from app.jev.models import JevCall, JevQuestion
from app.learning.intent_commands import route_explicit_command

# --------------------------------------------------------------------------- arms

ARM_NAMES: tuple[str, ...] = ("A", "B", "C", "D", "E")

# The six structured-enhancement component arms, measured against the same arm-A
# baseline. They are separate on/off switches and are deliberately NOT part of the
# A ⊂ B ⊂ C ⊂ D ⊂ E nesting: a component arm turns on exactly its own module's Jev
# decision definition key(s) and leaves every other key (including all eight A–E
# keys) off, so the historical arms are never redefined by adding a component arm.
COMPONENT_ARM_NAMES: tuple[str, ...] = (
    "M-EXTRACT",
    "M-ENTITY",
    "M-CONSISTENCY",
    "M-CITATION",
    "M-CAPABILITY",
    "M-TOOL",
)

# The full registry the CLI selects from: the historical arms plus the six components.
ALL_ARM_NAMES: tuple[str, ...] = ARM_NAMES + COMPONENT_ARM_NAMES

# Marker for a component metric whose decision definition has no labelled samples in
# the dataset. A component arm reports this instead of inventing a number.
INSUFFICIENT_SAMPLES = "INSUFFICIENT_SAMPLES"

# The specific Jev definition keys each arm turns "on"; everything else stays on the
# shipped DeepSeek/deterministic path. Validated against the live catalog in arm_modes.
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
    "E": frozenset(
        {
            "retrieval.support.v1",
            "context.keep_segment.v1",
            "intent.next_action.v1",
            "pedagogy.next_method.v1",
            "coverage.item_support.v1",
            "assessment.criterion_review.v1",
            "source.supports_claim.v1",
            "source.select_span.v1",
        }
    ),
}

# Definitions that stay on the DeepSeek/deterministic path in every arm (never Jev).
_NON_JEV_DEFINITIONS = frozenset(
    {
        "template.match.v1",
        "exercise.prototype.v1",
        "graph.prerequisite.v1",
        "corpus.quality.v1",
    }
)

# The decision definition key(s) each component module turns "on". Everything else
# stays off, so a component arm is the arm-A baseline plus exactly that module.
_COMPONENT_ARM_ON_KEYS: dict[str, frozenset[str]] = {
    "M-EXTRACT": frozenset({"extraction.field_grounded.v1"}),
    "M-ENTITY": frozenset({"entity.relation.v1"}),
    "M-CONSISTENCY": frozenset({"evidence.consistency.v1"}),
    "M-CITATION": frozenset({"source.supports_claim.v1", "source.select_span.v1"}),
    "M-CAPABILITY": frozenset({"teaching.capability.v1"}),
    "M-TOOL": frozenset({"tool.intent.v1"}),
}

# Human-readable module name behind each component arm (traceability only).
_COMPONENT_ARM_MODULES: dict[str, str] = {
    "M-EXTRACT": "ExtractionVerification",
    "M-ENTITY": "EntityResolution",
    "M-CONSISTENCY": "EvidenceConsistency",
    "M-CITATION": "ClaimCitationAudit",
    "M-CAPABILITY": "CapabilityRouter",
    "M-TOOL": "ToolIntentCheck",
}

# Each component metric is computed from the labelled samples of exactly one decision
# definition key. Metrics that reuse the shared A–E implementations keep the SAME
# metric keys the runner already emits (``citation_support_accuracy``,
# ``unsupported_claim_rate``, ``span_selection_accuracy``); the module-specific metrics
# are computed by the helpers below (added in round 31, when the companion dataset
# finally supplied their labels) and are still reported as ``INSUFFICIENT_SAMPLES`` if a
# dataset carries none of the relevant labels.
#
# Two of these metrics are CONDITIONAL on a label class (``extraction_false_acceptance``
# on defect-labelled samples, ``extraction_false_rejection`` on grounded ones,
# ``entity_false_merge``/``entity_missed_alias``/``entity_conflict_false_positive`` and
# ``tool_false_allow``/``tool_false_block`` likewise). A conditional rate with an empty
# denominator is reported as 0.0 for arithmetic safety, so every such metric also
# publishes its denominator in ``metric_denominators`` — read the pair, never the rate
# alone. The same reasoning is why ``condition_distinction`` is scored only over the
# labels it is about.
_COMPONENT_ARM_METRICS: dict[str, tuple[tuple[str, str], ...]] = {
    "M-EXTRACT": (
        ("extraction_false_acceptance", "extraction.field_grounded.v1"),
        ("extraction_false_rejection", "extraction.field_grounded.v1"),
    ),
    "M-ENTITY": (
        ("entity_false_merge", "entity.relation.v1"),
        ("entity_missed_alias", "entity.relation.v1"),
        ("entity_conflict_false_positive", "entity.relation.v1"),
    ),
    "M-CONSISTENCY": (
        ("condition_distinction", "evidence.consistency.v1"),
    ),
    "M-CITATION": (
        ("citation_support_accuracy", "source.supports_claim.v1"),
        ("unsupported_claim_rate", "source.supports_claim.v1"),
        ("span_selection_accuracy", "source.select_span.v1"),
    ),
    "M-CAPABILITY": (
        ("capability_misroute", "teaching.capability.v1"),
    ),
    "M-TOOL": (
        ("tool_false_allow", "tool.intent.v1"),
        ("tool_false_block", "tool.intent.v1"),
    ),
}


def validate_arm_nesting() -> None:
    """Fail loudly if A ⊂ B ⊂ C ⊂ D ⊂ E no longer holds (strict subset on the on keys)."""
    a, b, c, d, e = (_ARM_ON_KEYS[name] for name in ARM_NAMES)
    if not (a < b < c < d < e):
        raise ValueError("Ablation arms must nest strictly: A ⊂ B ⊂ C ⊂ D ⊂ E.")


def component_arm_metrics(arm: str) -> tuple[tuple[str, str], ...]:
    """The ``(metric, decision key)`` pairs one component arm publishes.

    Public because a runner has to answer a question the report cannot answer for it:
    *which* labelled samples a metric was computed from, and therefore which dataset a
    component run must read. The pairing was private, so a caller could only discover it by
    reading this module — and the runner that needed it printed an empty table instead.
    """
    if arm not in COMPONENT_ARM_NAMES:
        raise ValueError(
            f"{arm!r} is not a component arm; expected one of {list(COMPONENT_ARM_NAMES)}."
        )
    return _COMPONENT_ARM_METRICS[arm]


def arm_modes(arm: str) -> dict[str, str]:
    """Return the full per-key mode map for ``arm`` ("on" for Jev, "off" otherwise).

    The key list comes from the real catalog; the arm-defining keys are validated
    against it so a future catalog edit cannot silently break an arm. The A–E arms
    nest strictly (validated here); the six component arms are separate on/off
    switches that turn on exactly their own module key(s).
    """
    if arm in ARM_NAMES:
        validate_arm_nesting()
        on_keys = _ARM_ON_KEYS[arm]
    elif arm in COMPONENT_ARM_NAMES:
        on_keys = _COMPONENT_ARM_ON_KEYS[arm]
    else:
        raise ValueError(f"Unknown ablation arm {arm!r}; expected one of {ALL_ARM_NAMES}.")
    definitions = load_catalog().definitions
    unknown = sorted(on_keys - set(definitions))
    if unknown:
        raise ValueError(f"Arm {arm!r} references keys absent from the catalog: {unknown}.")
    return {key: ("on" if key in on_keys else "off") for key in definitions}


# ------------------------------------------------------------------ label tiers

LABEL_TIER_OBJECTIVE = "OBJECTIVE_VERIFIED"
LABEL_TIER_SOURCE = "SOURCE_REVIEWED"
LABEL_TIER_SILVER = "SILVER_DEEPSEEK"
LABEL_TIER_DISPUTED = "DISPUTED"
LABEL_TIERS = frozenset(
    {LABEL_TIER_OBJECTIVE, LABEL_TIER_SOURCE, LABEL_TIER_SILVER, LABEL_TIER_DISPUTED}
)

_LABEL_TIER_DEFINITIONS: dict[str, str] = {
    LABEL_TIER_OBJECTIVE: (
        "Label is verified by code: a rule, an ID, a sum or arithmetic check."
    ),
    LABEL_TIER_SOURCE: (
        "Label cites a course source (locator + review reason); reviewed, not machine gold."
    ),
    LABEL_TIER_SILVER: (
        "Label is an unreviewed DeepSeek suggestion; NOT human gold and must not be used "
        "as an accuracy reference for a quality claim."
    ),
    LABEL_TIER_DISPUTED: (
        "Genuinely ambiguous; both readings are recorded. Excluded from single-label metrics."
    ),
}

# A DISPUTED sample carries both readings and must be excluded from any single-label
# correctness metric (it has no single gold answer).
DISPUTED_MARKER = "disputed"

# ------------------------------------------------------------------ dataset schema

GROUPING_KEYS: tuple[str, ...] = ("document_id", "node_id", "question_family")
SPLIT_NAMES: tuple[str, ...] = ("train", "calibration", "test")

DATASET_VERSION = "1.0.0"
DEFINITION_VERSION = "1.0.0-design"

# Question families. Each maps to a definition and a metric family.
FAMILY_RETRIEVAL = "retrieval"
FAMILY_LOCATOR = "locator"
FAMILY_CONTEXT = "context"
FAMILY_INTENT = "intent"
FAMILY_PEDAGOGY = "pedagogy"
FAMILY_COVERAGE = "coverage"
FAMILY_CRITERION = "criterion"
FAMILY_CITATION = "citation"
FAMILY_SPAN_SELECTION = "span_selection"
FAMILY_CLASSIFICATION = "classification"
FAMILY_EXERCISE = "exercise"
FAMILY_PREREQUISITE = "prerequisite"
FAMILY_CORPUS_QUALITY = "corpus_quality"
FAMILY_TRAJECTORY = "trajectory"
FAMILY_IMAGE = "image"
# Structured-enhancement module families (round 31). The companion dataset
# (benchmarks/jev-module-judgments.dataset.json) supplies their labels, which is what
# lets the module-specific metrics below be computed at all.
FAMILY_EXTRACTION = "extraction"
FAMILY_CONSISTENCY = "consistency"
FAMILY_ENTITY = "entity_relation"
FAMILY_CAPABILITY = "capability"
FAMILY_TOOL_INTENT = "tool_intent"
FAMILY_FEEDBACK_CATEGORY = "feedback_category"
FAMILY_FEEDBACK_SEVERITY = "feedback_severity"

# Image transcription is not one of the 12 Jev/Jev definitions: it is DeepSeek vision,
# handled outside the semantic layer. It has its own (single) family and answer shape.
IMAGE_DEFINITION = "image_transcription.v1"

_FAMILY_DEFINITION: dict[str, str] = {
    FAMILY_RETRIEVAL: "retrieval.support.v1",
    FAMILY_LOCATOR: "retrieval.support.v1",
    FAMILY_CONTEXT: "context.keep_segment.v1",
    FAMILY_INTENT: "intent.next_action.v1",
    FAMILY_PEDAGOGY: "pedagogy.next_method.v1",
    FAMILY_COVERAGE: "coverage.item_support.v1",
    FAMILY_CRITERION: "assessment.criterion_review.v1",
    FAMILY_CITATION: "source.supports_claim.v1",
    FAMILY_SPAN_SELECTION: "source.select_span.v1",
    FAMILY_CLASSIFICATION: "template.match.v1",
    FAMILY_EXERCISE: "exercise.prototype.v1",
    FAMILY_PREREQUISITE: "graph.prerequisite.v1",
    FAMILY_CORPUS_QUALITY: "corpus.quality.v1",
    FAMILY_TRAJECTORY: "intent.next_action.v1",
    FAMILY_IMAGE: IMAGE_DEFINITION,
}

# relevance threshold above which a retrieval candidate counts as "relevant" for
# recall@k / MRR / NDCG (the graded relevance IS the labelled score_index, 0-4).
RETRIEVAL_RELEVANT_THRESHOLD = 3

QUESTION_KEY = "q"


@dataclass(frozen=True)
class JevJudgment:
    """One normalized judgement sample from the dataset."""

    sample_id: str
    definition_id: str
    definition_version: str
    language: str
    option_count: int
    document_id: str
    node_id: str
    question_family: str
    label_tier: str
    label_evidence: str
    state: dict[str, Any]
    questions: dict[str, dict[str, Any]]
    label: dict[str, dict[str, Any]]
    split: str

    @property
    def group_key(self) -> tuple[str, str, str]:
        return (self.document_id, self.node_id, self.question_family)

    @property
    def primitive(self) -> str:
        qtype = self.questions[QUESTION_KEY]["type"]
        return str(qtype).lower()

    def label_answer(self) -> dict[str, Any]:
        return self.label[QUESTION_KEY]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the dataset JSON shape (the split lives in the manifest)."""
        return {
            "sample_id": self.sample_id,
            "definition_id": self.definition_id,
            "definition_version": self.definition_version,
            "language": self.language,
            "option_count": self.option_count,
            "document_id": self.document_id,
            "node_id": self.node_id,
            "question_family": self.question_family,
            "label_tier": self.label_tier,
            "label_evidence": self.label_evidence,
            "state": self.state,
            "questions": self.questions,
            "label": self.label,
        }


# ------------------------------------------------------------------ dataset loading


def load_jev_dataset(path: Path) -> dict[str, Any]:
    """Load the dataset JSON, validate it, and return the payload."""
    payload = _read_json(path, "jev dataset")
    validate_jev_dataset(payload)
    return payload


def _read_json(path: Path, what: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read {what} {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{what} must be a JSON object.")
    return payload


def validate_jev_dataset(payload: Mapping[str, Any]) -> None:
    """Validate the dataset's schema and invariants; raise a clear error on failure."""
    samples_raw = payload.get("samples")
    if not isinstance(samples_raw, list) or not samples_raw:
        raise ValueError("Jev dataset must contain a non-empty 'samples' list.")

    definitions = load_catalog().definitions
    seen_ids: set[str] = set()
    groups: dict[tuple[str, str, str], str] = {}
    for index, raw in enumerate(samples_raw):
        where = f"sample #{index}"
        if not isinstance(raw, dict):
            raise ValueError(f"{where}: expected an object.")
        sample = _parse_judgment(raw, where)
        if sample.sample_id in seen_ids:
            raise ValueError(f"{where}: duplicate sample_id {sample.sample_id!r}.")
        seen_ids.add(sample.sample_id)

        if sample.definition_id == IMAGE_DEFINITION:
            _validate_image_sample(sample, where)
        else:
            definition = definitions.get(sample.definition_id)
            if definition is None:
                raise ValueError(
                    f"{where}: definition_id {sample.definition_id!r} is not in the catalog."
                )
            _validate_state_shape(sample, definition, where)
            _validate_label_shape(sample, definition, where)

        prior = groups.get(sample.group_key)
        if prior is not None and prior != sample.definition_id:
            raise ValueError(
                f"{where}: group {sample.group_key!r} spans definitions "
                f"{prior!r} and {sample.definition_id!r}."
            )
        groups[sample.group_key] = sample.definition_id


def _parse_judgment(raw: Mapping[str, Any], where: str) -> JevJudgment:
    def need_str(key: str) -> str:
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{where}: {key!r} must be a non-empty string.")
        return value

    def need_int(key: str, minimum: int) -> int:
        value = raw.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{where}: {key!r} must be an integer >= {minimum}.")
        return value

    label_tier = need_str("label_tier")
    if label_tier not in LABEL_TIERS:
        raise ValueError(f"{where}: label_tier {label_tier!r} not in {sorted(LABEL_TIERS)}.")
    _validate_label_tier(label_tier, need_str("label_evidence"), where)

    state = raw.get("state")
    if not isinstance(state, dict):
        raise ValueError(f"{where}: 'state' must be an object.")
    questions = raw.get("questions")
    if not isinstance(questions, dict) or QUESTION_KEY not in questions:
        raise ValueError(f"{where}: 'questions' must contain a {QUESTION_KEY!r} object.")
    label = raw.get("label")
    if not isinstance(label, dict) or QUESTION_KEY not in label:
        raise ValueError(f"{where}: 'label' must contain a {QUESTION_KEY!r} object.")

    return JevJudgment(
        sample_id=need_str("sample_id"),
        definition_id=need_str("definition_id"),
        definition_version=need_str("definition_version"),
        language=need_str("language").lower(),
        option_count=need_int("option_count", 2),
        document_id=need_str("document_id"),
        node_id=need_str("node_id"),
        question_family=need_str("question_family"),
        label_tier=label_tier,
        label_evidence=need_str("label_evidence"),
        state=dict(state),
        questions={str(k): dict(v) for k, v in questions.items()},
        label={str(k): dict(v) for k, v in label.items()},
        split="",  # assigned separately from the split manifest
    )


def _validate_label_tier(label_tier: str, label_evidence: str, where: str) -> None:
    """Enforce the label-tier honesty invariants in the evidence text.

    * ``SILVER_DEEPSEEK`` is an unreviewed suggestion, never human gold.
    * ``DISPUTED`` records both readings explicitly.
    """
    evidence = label_evidence.lower()
    if label_tier == LABEL_TIER_SILVER and (
        "unreviewed" not in evidence and "deepseek suggestion" not in evidence
    ):
        raise ValueError(
            f"{where}: SILVER_DEEPSEEK label_evidence must state it is an unreviewed "
            "DeepSeek suggestion."
        )
    if label_tier == LABEL_TIER_DISPUTED and (
        "reading a" not in evidence or "reading b" not in evidence
    ):
        raise ValueError(
            f"{where}: DISPUTED label_evidence must record both readings (reading A and reading B)."
        )


def _validate_state_shape(sample: JevJudgment, definition: Any, where: str) -> None:
    missing = [key for key in definition.required_state if key not in sample.state]
    if missing:
        raise ValueError(
            f"{where}: state for {sample.definition_id!r} is missing required_state "
            f"{missing}."
        )


def _validate_label_shape(sample: JevJudgment, definition: Any, where: str) -> None:
    answer = sample.label[QUESTION_KEY]
    primitive = definition.primitive.lower()
    if primitive == "choice":
        if "choice" not in answer:
            raise ValueError(f"{where}: choice label must contain a 'choice' key.")
        criteria = definition.criteria or {}
        if "dynamic" in criteria:
            # server-generated candidate ids (spans/templates/prototypes/nodes) are
            # valid; only require a non-empty selection.
            if not isinstance(answer["choice"], str) or not answer["choice"]:
                raise ValueError(f"{where}: dynamic choice label must be a non-empty string.")
        elif answer["choice"] not in criteria:
            raise ValueError(
                f"{where}: choice label {answer['choice']!r} is not a candidate of "
                f"{sample.definition_id!r}."
            )
    elif primitive == "score":
        if "score_index" not in answer:
            raise ValueError(f"{where}: score label must contain a 'score_index' key.")
        levels = definition.score_levels
        if not isinstance(answer["score_index"], int) or answer["score_index"] not in (
            range(len(levels)) if levels else range(sample.option_count)
        ):
            raise ValueError(
                f"{where}: score_index {answer['score_index']!r} is not a valid level."
            )
    elif primitive == "noul":
        if "noul" not in answer or not isinstance(answer["noul"], bool):
            raise ValueError(f"{where}: noul label must contain a boolean 'noul' key.")
    else:
        raise ValueError(f"{where}: unknown primitive {primitive!r}.")


def _validate_image_sample(sample: JevJudgment, where: str) -> None:
    answer = sample.label[QUESTION_KEY]
    if "answer" not in answer or not isinstance(answer["answer"], str):
        raise ValueError(f"{where}: image label must contain an 'answer' string.")


# ------------------------------------------------------------------ split + leakage

_SPLIT_TRAIN_FRACTION = 3
_SPLIT_CALIBRATION_FRACTION = 1
_SPLIT_TEST_FRACTION = 1
_SPLIT_PATTERN = ("train", "train", "train", "calibration", "test")


def assign_split(group_key: tuple[str, str, str]) -> str:
    """Deterministically assign a split for a group key (never per row).

    The assignment is a **hash** of the group key taken modulo the 3:1:1
    train/calibration/test pattern, so it is stable and independent of row order, and the
    whole (document, node, family) group always lands in one split — the same underlying
    question with different numbers cannot be split across two of them.

    It does **not** guarantee that every definition (or every language, or every family)
    contributes to every split. That guarantee is not available from a hash, and the
    earlier wording here claimed it: with few groups a definition can easily draw no
    calibration group at all, which makes its thresholds unfittable until more groups
    exist. Use :func:`split_coverage` to see that per definition instead of assuming it.
    """
    return _split_for_ordered_index(_ordered_group_index(group_key))


def judgments_from_dataset(payload: Mapping[str, Any]) -> list[JevJudgment]:
    """Parse a validated dataset payload into judgments (one per sample)."""
    return [
        _parse_judgment(raw, f"sample #{index}")
        for index, raw in enumerate(payload["samples"])
    ]


def split_coverage(samples: Sequence[JevJudgment]) -> dict[str, dict[str, int]]:
    """Per-definition sample counts per split, including the zeros.

    Report-only: it answers "can this definition's thresholds even be fitted?" before a
    calibration run is attempted. Every definition present in ``samples`` appears in the
    result with all three splits listed, so a missing calibration split shows up as an
    explicit ``0`` rather than as a definition that quietly vanishes from a table.
    """
    coverage: dict[str, dict[str, int]] = {}
    for sample in samples:
        per_split = coverage.setdefault(
            sample.definition_id, {name: 0 for name in SPLIT_NAMES}
        )
        per_split[assign_split(sample.group_key)] += 1
    return coverage


def unfittable_definitions(samples: Sequence[JevJudgment]) -> tuple[str, ...]:
    """Definitions with no calibration-split sample (their thresholds cannot be fitted)."""
    return tuple(
        sorted(
            definition_id
            for definition_id, per_split in split_coverage(samples).items()
            if per_split["calibration"] == 0
        )
    )


def unevaluated_definitions(samples: Sequence[JevJudgment]) -> tuple[str, ...]:
    """Definitions with no test-split sample (nothing held out to evaluate them on).

    The symmetric limitation to :func:`unfittable_definitions`: a definition with no
    calibration sample cannot have a threshold fitted, and one with no test sample cannot
    be reported against a held-out split — both are facts about the dataset, not about the
    model, and both are surfaced rather than left for a reader to notice.
    """
    return tuple(
        sorted(
            definition_id
            for definition_id, per_split in split_coverage(samples).items()
            if per_split["test"] == 0
        )
    )


def _ordered_group_index(group_key: tuple[str, str, str]) -> int:
    # A deterministic, collision-free ordinal per group, derived from its stable key.
    digest = hashlib.sha256("|".join(group_key).encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _split_for_ordered_index(index: int) -> str:
    return _SPLIT_PATTERN[index % len(_SPLIT_PATTERN)]


def validate_split_leakage(
    samples: Sequence[JevJudgment], split_manifest: Mapping[str, Any]
) -> None:
    """Assert the frozen split has no leakage: split by group, never by row.

    Raises ``ValueError`` if any invariant is broken:
    * every sample is assigned to exactly one of train/calibration/test;
    * no sample_id appears in more than one split;
    * samples sharing a (document_id, node_id, question_family) group are in the same
      split (the "same underlying question with different numbers" protection).
    """
    assignment: dict[str, str] = {}
    for name in SPLIT_NAMES:
        ids = split_manifest.get("splits", {}).get(name, {}).get("sample_ids", [])
        for sample_id in ids:
            if sample_id in assignment:
                raise ValueError(f"sample_id {sample_id!r} appears in more than one split.")
            assignment[str(sample_id)] = name

    by_id = {sample.sample_id: sample for sample in samples}
    missing = sorted(set(by_id) - set(assignment))
    if missing:
        raise ValueError(f"samples not assigned to any split: {missing}.")
    extra = sorted(set(assignment) - set(by_id))
    if extra:
        raise ValueError(f"split manifest references unknown sample_ids: {extra}.")

    group_splits: dict[tuple[str, str, str], str] = {}
    for sample_id, name in assignment.items():
        sample = by_id[sample_id]
        prior = group_splits.get(sample.group_key)
        if prior is not None and prior != name:
            raise ValueError(
                f"leakage: group {sample.group_key!r} is split across {prior!r} and "
                f"{name!r} (samples {sample.sample_id!r} vs earlier row)."
            )
        group_splits[sample.group_key] = name


def content_hash(samples: Sequence[JevJudgment]) -> str:
    """Deterministic content hash of the (labelled) samples, keyed by sample_id."""
    canonical = {
        sample.sample_id: {
            "definition_id": sample.definition_id,
            "language": sample.language,
            "option_count": sample.option_count,
            "state": sample.state,
            "questions": sample.questions,
            "label": sample.label,
        }
        for sample in samples
    }
    serialized = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_split_manifest(samples: Sequence[JevJudgment]) -> dict[str, Any]:
    """Build the frozen split manifest (grouping keys, per-split counts, content hash)."""
    assigned = [(sample, assign_split(sample.group_key)) for sample in samples]
    splits: dict[str, dict[str, Any]] = {
        name: {"count": 0, "sample_ids": []} for name in SPLIT_NAMES
    }
    for sample, split in assigned:
        splits[split]["count"] += 1
        splits[split]["sample_ids"].append(sample.sample_id)
    for name in SPLIT_NAMES:
        splits[name]["sample_ids"].sort()
    groups: dict[str, list[str]] = {}
    for sample, _split in assigned:
        groups.setdefault("|".join(sample.group_key), []).append(sample.sample_id)
    return {
        "split_version": "1",
        "grouping": list(GROUPING_KEYS),
        "splits": splits,
        "group_keys": {
            key: sorted(ids) for key, ids in sorted(groups.items())
        },
        "content_hash": content_hash(samples),
        "note": (
            "Splits are assigned by (document_id, node_id, question_family) group, never "
            "by row: the same underlying question with different numbers shares one group "
            "and therefore one split. A fitted temperature is only valid against this "
            "exact content_hash."
        ),
    }


# ------------------------------------------------------------------ pure metrics (new families)


@dataclass(frozen=True)
class ChoiceResult:
    case_id: str
    label_choice: str
    predicted_choice: str | None


@dataclass(frozen=True)
class ScoreLevelResult:
    case_id: str
    label_level: int
    predicted_level: int | None
    max_level: int


@dataclass(frozen=True)
class KeyFactResult:
    case_id: str
    segment_id: str
    label_keep: bool
    predicted_keep: bool | None


def choice_accuracy(results: Sequence[ChoiceResult]) -> float:
    """Fraction of choice predictions matching the label (None = abstention = wrong)."""
    if not results:
        return 0.0
    correct = sum(
        1
        for result in results
        if result.predicted_choice is not None
        and result.predicted_choice == result.label_choice
    )
    return correct / len(results)


# --------------------------------------------------------------------------- module
# metrics
#
# Each helper states its population and its definition, because a rate whose population
# is implicit is exactly how a metric starts lying. Every helper returns 0.0 for an
# empty population (arithmetic safety) and the caller publishes the denominators in
# ``metric_denominators`` so the rate is never read on its own.

#: Labels that say the extracted field is NOT trustworthy, i.e. the guard must not accept it.
EXTRACTION_DEFECT_LABELS = frozenset(
    {"WRONG_FIELD", "NEGATION_LOST", "CONSTRAINT_LOST", "SOURCE_INSUFFICIENT"}
)

#: Entity labels that mean "these two are the same thing under a different name".
ENTITY_SAME_LABELS = frozenset({"SAME_CONCEPT", "ALIAS"})

#: Entity labels that mean "do not merge these"; `DIFFERENT` is the hard separation.
ENTITY_DISTINCT_LABELS = frozenset({"DIFFERENT"})

#: The two evidence labels that are about a difference of condition/version, not a conflict.
CONDITION_DIFFERENCE_LABELS = frozenset(
    {"DIFFERENT_ASSUMPTIONS", "VERSION_OR_TASK_DIFFERENCE"}
)


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def extraction_false_acceptance(results: Sequence[ChoiceResult]) -> float:
    """Of the fields a reviewer flagged as defective, how many did we accept?

    Population: samples whose label is in :data:`EXTRACTION_DEFECT_LABELS`. Numerator:
    those where the prediction was ``GROUNDED``. A high value is the dangerous
    direction — a wrong field reaching teaching — so this is the metric that must be
    right before module A is allowed to act on anything.
    """
    population = [r for r in results if r.label_choice in EXTRACTION_DEFECT_LABELS]
    return _rate(
        sum(1 for r in population if r.predicted_choice == "GROUNDED"), len(population)
    )


def extraction_false_rejection(results: Sequence[ChoiceResult]) -> float:
    """Of the fields a reviewer confirmed, how many did we refuse to accept?

    Population: samples labelled ``GROUNDED``. Numerator: everything that is not
    ``GROUNDED`` (a defect verdict or an abstention). This is the annoyance direction:
    dropping a locator that was fine.
    """
    population = [r for r in results if r.label_choice == "GROUNDED"]
    return _rate(
        sum(1 for r in population if r.predicted_choice != "GROUNDED"), len(population)
    )


def entity_false_merge(results: Sequence[ChoiceResult]) -> float:
    """Of the pairs a reviewer said must NOT be merged, how many did we merge?

    Population: labels outside :data:`ENTITY_SAME_LABELS` (i.e. ``DIFFERENT``,
    ``RELATED_NOT_SAME``, ``QUESTION_VARIANT``, ``DOCUMENT_VERSION_RELATION``,
    ``UNCERTAIN``). Numerator: predictions in :data:`ENTITY_SAME_LABELS` — treating an
    alias or a same-concept verdict as identity when none was warranted.
    """
    population = [r for r in results if r.label_choice not in ENTITY_SAME_LABELS]
    return _rate(
        sum(1 for r in population if r.predicted_choice in ENTITY_SAME_LABELS),
        len(population),
    )


def entity_missed_alias(results: Sequence[ChoiceResult]) -> float:
    """Of the pairs a reviewer called an alias, how many did we fail to call an alias?

    Population: label ``ALIAS``. Numerator: anything else. A miss here costs recall on
    the "Chinese term reaches English material" behaviour, not correctness.
    """
    population = [r for r in results if r.label_choice == "ALIAS"]
    return _rate(
        sum(1 for r in population if r.predicted_choice != "ALIAS"), len(population)
    )


def entity_conflict_false_positive(results: Sequence[ChoiceResult]) -> float:
    """Of the pairs a reviewer said are the same or related, how many did we declare different?

    Population: labels in :data:`ENTITY_SAME_LABELS` plus ``RELATED_NOT_SAME``.
    Numerator: prediction ``DIFFERENT``. This is the "invented conflict" direction: the
    reader would be told two sources disagree when they do not.
    """
    population = [
        r
        for r in results
        if r.label_choice in ENTITY_SAME_LABELS or r.label_choice == "RELATED_NOT_SAME"
    ]
    return _rate(
        sum(1 for r in population if r.predicted_choice in ENTITY_DISTINCT_LABELS),
        len(population),
    )


def condition_distinction(results: Sequence[ChoiceResult]) -> float:
    """Of the pairs that differ by condition/version, how many did we place correctly?

    Population: labels in :data:`CONDITION_DIFFERENCE_LABELS`. This is deliberately NOT
    an accuracy over all pairs: the question the spec asks is whether a difference of
    assumption or of version is kept apart from a genuine contradiction and from
    ``COMPATIBLE``. Collapsing either way is a failure, and both count against this one
    number rather than being split into two rates nobody agreed on.
    """
    population = [r for r in results if r.label_choice in CONDITION_DIFFERENCE_LABELS]
    return _rate(
        sum(1 for r in population if r.predicted_choice == r.label_choice),
        len(population),
    )


def capability_misroute(results: Sequence[ChoiceResult]) -> float:
    """Fraction of capabilities dispatched that the label did not call for.

    Population: every labelled capability sample. Numerator: prediction != label,
    including an abstention. Every offered candidate is one this endpoint actually
    serves, so "misroute" here means choosing the wrong one of the legal options (or
    refusing to choose) rather than dispatching something that cannot run — for the
    latter the arm would have to be handed a catalog it is not allowed to offer.
    """
    return _rate(
        sum(1 for r in results if r.predicted_choice != r.label_choice), len(results)
    )


def tool_false_allow(results: Sequence[ChoiceResult]) -> float:
    """Of the writes the user did NOT authorise, how many did we let through?

    Population: label ``INCONSISTENT_WITH_INTENT``. Numerator: prediction
    ``CONSISTENT``. ``AMBIGUOUS`` is not counted as an allow: it is the confirmation
    path, not a pass. This is the safety-critical direction for module F.
    """
    population = [r for r in results if r.label_choice == "INCONSISTENT_WITH_INTENT"]
    return _rate(
        sum(1 for r in population if r.predicted_choice == "CONSISTENT"), len(population)
    )


def tool_false_block(results: Sequence[ChoiceResult]) -> float:
    """Of the writes the user DID authorise, how many did we refuse?

    Population: label ``CONSISTENT``. Numerator: prediction
    ``INCONSISTENT_WITH_INTENT``. Being blocked from a legitimate, explicit action is
    the cost of over-blocking, and the spec names it as its own metric.
    """
    population = [r for r in results if r.label_choice == "CONSISTENT"]
    return _rate(
        sum(1 for r in population if r.predicted_choice == "INCONSISTENT_WITH_INTENT"),
        len(population),
    )


def score_level_mae(results: Sequence[ScoreLevelResult]) -> float:
    """Mean absolute error over ordinal score levels; ``None`` prediction is full error."""
    if not results:
        return 0.0
    errors = [
        abs(result.label_level - result.predicted_level)
        if result.predicted_level is not None
        else float(result.max_level)
        for result in results
    ]
    return sum(errors) / len(errors)


def key_fact_retention(results: Sequence[KeyFactResult]) -> float:
    """Fraction of must-keep context segments that are kept (recall over label_keep=True).

    Only ``predicted_keep is True`` counts as kept; False/None (withheld) are losses.
    """
    must_keep = [result for result in results if result.label_keep]
    if not must_keep:
        return 1.0
    return sum(1 for result in must_keep if result.predicted_keep is True) / len(must_keep)


def context_compaction(results: Sequence[KeyFactResult]) -> float:
    """Fraction of drop-able context segments correctly dropped (precision of dropping)."""
    drop_able = [result for result in results if not result.label_keep]
    if not drop_able:
        return 1.0
    return sum(1 for result in drop_able if result.predicted_keep is False) / len(drop_able)


def ndcg(returned_ids: Sequence[str], graded_relevance: Mapping[str, int], k: int) -> float:
    """Normalized Discounted Cumulative Gain@k from label-graded relevance only."""
    if k <= 0:
        raise ValueError("k must be positive.")
    grades = [int(graded_relevance.get(str(cid), 0)) for cid in returned_ids[:k]]
    dcg = sum((2 ** g - 1) / math.log2(rank + 2) for rank, g in enumerate(grades))
    ideal = sorted((int(g) for g in graded_relevance.values()), reverse=True)[:k]
    idcg = sum((2 ** g - 1) / math.log2(rank + 2) for rank, g in enumerate(ideal))
    return dcg / idcg if idcg > 0 else 0.0


# ------------------------------------------------------------------ transport


class JevTransport:
    """Base class for the Jev transport; only its kind matters for interpretation."""


class FakeJevTransport(JevTransport):
    """A deterministic, deliberately non-informative responder for offline plumbing."""


def transport_kind(transport: JevTransport) -> str:
    return TRANSPORT_FAKE if isinstance(transport, FakeJevTransport) else TRANSPORT_LIVE


def interpretation_for(transport: str, dataset_status: str) -> str:
    if transport == TRANSPORT_FAKE:
        return INTERPRETATION_PLUMBING
    if dataset_status == DATASET_STATUS_LABELLED:
        return INTERPRETATION_INTERPRETABLE
    return INTERPRETATION_UNLABELLED


def deterministic_fake_jev_predictor(sample: JevJudgment) -> dict[str, Any]:
    """Fixed, non-informative predictions for offline plumbing runs.

    Returns the first Choice candidate, the lowest Score level, and ``noul=False``.
    Runs using this are tagged NON_INTERPRETABLE_PLUMBING_ONLY so these values can
    never be read as a quality signal.
    """
    question = sample.questions[QUESTION_KEY]
    qtype = str(question["type"]).lower()
    if qtype == "choice":
        criteria = question.get("criteria") or {}
        return {"choice": next(iter(criteria), None)}
    if qtype == "score":
        criteria = question.get("criteria") or {}
        return {"score_index": 0 if criteria else None}
    return {"noul": False}


def live_jev_predictor(
    transport: Any,
    *,
    timeout_seconds: float = 60.0,
    calls: list[dict[str, Any]] | None = None,
) -> Callable[[JevJudgment], dict[str, Any] | None]:
    """A predictor backed by the real Jev transport, for a labelled run.

    The dataset's own question shape is translated to the gateway's: ``choice`` keeps its
    ``id -> label`` criteria, ``score`` becomes the ordered list of level descriptions, and ``noul``
    carries instructions only. The answer comes back through the same typed validation every
    production call goes through, so a run cannot be more permissive than the product.

    Two mappings are applied to compare against a discrete label, and both are stated here rather
    than hidden, because each is a boundary the catalogue has not calibrated:

    * ``noul`` (a probability in ``[0, 1]``) becomes the boolean label at ``0.5``;
    * a live ``Score`` answer usually arrives as a decimal on the definition's scale, and becomes an
      index by rounding to the nearest declared level, clamped to the scale. A level key, when the
      model gives one, is used directly.

    Every call is appended to `calls` (sample id, primitive, raw answer fields, latency) so the
    evidence records what the model actually said next to the label it was compared with.
    """

    def predict(sample: JevJudgment) -> dict[str, Any] | None:
        definition = _catalog_definition(sample.definition_id)
        question = sample.questions[QUESTION_KEY]
        kind = str(question.get("type")).lower()
        criteria = question.get("criteria") or {}
        instructions = str(question.get("instructions") or "")
        if kind == "choice":
            jev_question = JevQuestion(
                key=QUESTION_KEY,
                primitive=Primitive.CHOICE,
                instructions=instructions,
                criteria=dict(criteria),
            )
        elif kind == "score":
            ordered = [criteria[key] for key in sorted(criteria, key=lambda item: int(item))]
            jev_question = JevQuestion(
                key=QUESTION_KEY,
                primitive=Primitive.SCORE,
                instructions=instructions,
                criteria=ordered,
            )
        else:
            jev_question = JevQuestion(
                key=QUESTION_KEY, primitive=Primitive.NOUL, instructions=instructions
            )
        call = JevCall(state=dict(sample.state), questions={QUESTION_KEY: jev_question})
        started = _perf_counter()
        result = transport.call(call, timeout_seconds=timeout_seconds)
        latency_ms = round((_perf_counter() - started) * 1000, 1)
        answer = result.answers.get(QUESTION_KEY)
        record: dict[str, Any] = {
            "sample_id": sample.sample_id,
            "definition_id": sample.definition_id,
            "question_type": kind,
            "latency_ms": latency_ms,
            "request_id": result.request_id,
            "model_version": result.model_version,
            "raw_choice": None if answer is None else answer.choice,
            "raw_noul": None if answer is None else answer.noul,
            "raw_score": None if answer is None else answer.score,
            "raw_score_value": None if answer is None else answer.score_value,
        }
        if answer is None:
            record["prediction"] = None
            if calls is not None:
                calls.append(record)
            return None
        if kind == "choice":
            prediction: dict[str, Any] = {"choice": answer.choice}
        elif kind == "score":
            prediction = {"score_index": _score_index(definition, answer)}
        else:
            prediction = {"noul": bool(answer.noul is not None and answer.noul >= 0.5)}
        record["prediction"] = prediction
        if calls is not None:
            calls.append(record)
        return prediction

    return predict


def _score_index(definition: Any, answer: Any) -> int | None:
    """The declared-level index a live Score answer corresponds to, or None.

    Nearest-level rounding is the comparison's discretisation, not a calibrated boundary: it is
    recorded here so the calibration work can replace it with measured boundaries.
    """
    levels = list(getattr(definition, "score_levels", ()) or ())
    if not levels:
        return None
    if answer.score is not None and str(answer.score) in levels:
        return levels.index(str(answer.score))
    if answer.score_value is None:
        return None
    # Nearest declared level, clamped to the scale. The catalogue's level keys are the ordered
    # `0..n` strings the scale is defined over, so the rounded value is the index.
    nearest = int(round(float(answer.score_value)))
    return max(0, min(len(levels) - 1, nearest))


def _catalog_definition(definition_id: str) -> Any:
    catalog = load_catalog()
    return catalog.get(definition_id)


# ------------------------------------------------------------------ runner


@dataclass(frozen=True)
class _RankedQuery:
    query_id: str
    candidates: tuple[tuple[str, int | None], ...]  # (candidate_id, predicted score)
    graded_relevance: dict[str, int]
    exact_target_id: str | None
    expected_slot: int | None
    top_k: int


def _component_report(
    arm: str, samples: Sequence[JevJudgment], metrics: Mapping[str, Any]
) -> dict[str, Any]:
    """Build the honest component-arm report: measured metrics vs INSUFFICIENT_SAMPLES.

    For every metric the module owns, count the labelled samples whose
    ``definition_id`` matches the metric's decision key. A metric with samples is
    reported ``MEASURED`` (its value is the shared runner's own metric when the key
    exists there); a metric with zero labelled samples is reported
    ``INSUFFICIENT_SAMPLES`` and carries no numeric value.
    """
    spec = _COMPONENT_ARM_METRICS[arm]
    counts: dict[str, int] = {metric: 0 for metric, _ in spec}
    for sample in samples:
        definition_id = sample.definition_id
        for metric, key in spec:
            if definition_id == key:
                counts[metric] += 1

    per_metric: dict[str, dict[str, Any]] = {}
    insufficient: list[str] = []
    for metric, _key in spec:
        count = counts[metric]
        if metric in metrics and count > 0:
            per_metric[metric] = {"status": "MEASURED", "samples": count, "value": metrics[metric]}
        else:
            per_metric[metric] = {"status": INSUFFICIENT_SAMPLES, "samples": count}
            insufficient.append(metric)

    return {
        "module": _COMPONENT_ARM_MODULES[arm],
        "on_keys": sorted(_COMPONENT_ARM_ON_KEYS[arm]),
        "metrics": per_metric,
        "insufficient_samples": sorted(insufficient),
    }


def run_jev_semantic_ablation(
    dataset: Mapping[str, Any],
    arm: str,
    *,
    transport: JevTransport,
    jev_predictor: Callable[[JevJudgment], dict[str, Any] | None] | None = None,
    deepseek_predictor: Callable[[JevJudgment], dict[str, Any] | None] | None = None,
    deterministic_predictor: Callable[[JevJudgment], dict[str, Any] | None] | None = None,
    image_predictor: Callable[[dict[str, Any]], str | None] | None = None,
) -> dict[str, Any]:
    """Execute one arm over the dataset through the shipped decision paths.

    ``jev_predictor`` answers questions whose definition the arm turns "on";
    ``deepseek_predictor`` / ``deterministic_predictor`` answer the non-Jev side
    (arm A's baseline). When a non-Jev baseline predictor is not injected for a
    family, that family's arm-A baseline is an **abstention** (a placeholder, not the
    shipped pipeline) and :func:`compare_jev_arms` refuses to call the comparison
    interpretable. Explicit commands are always routed by ``route_explicit_command``
    (the real deterministic behaviour) and spend no Jev/DeepSeek call.

    No learning/grade/coverage/permission state is written anywhere: this is a pure
    measurement harness.
    """
    modes = arm_modes(arm)
    dataset_status = str(dataset.get("dataset_status", DATASET_STATUS_EXAMPLE))
    samples = judgments_from_dataset(dataset)

    retrieval_results: list[RetrievalResult] = []
    locator_results: list[LocatorResult] = []
    citation_results: list[CitationResult] = []
    span_results: list[ChoiceResult] = []
    context_results: list[KeyFactResult] = []
    intent_results: list[ChoiceResult] = []
    pedagogy_results: list[ChoiceResult] = []
    coverage_results: list[CoverageResult] = []
    criterion_results: list[CriterionResult] = []
    classification_results: list[ChoiceResult] = []
    exercise_results: list[ChoiceResult] = []
    prerequisite_results: list[ChoiceResult] = []
    corpus_results: list[ScoreLevelResult] = []
    trajectory_results: list[TrajectoryResult] = []
    image_results: list[ImageResult] = []
    # Structured-enhancement module collections (round 31). The companion dataset
    # supplies these families; without it they stay empty and every metric below is
    # reported as INSUFFICIENT_SAMPLES by the component report.
    extraction_results: list[ChoiceResult] = []
    consistency_results: list[ChoiceResult] = []
    entity_results: list[ChoiceResult] = []
    capability_results: list[ChoiceResult] = []
    tool_intent_results: list[ChoiceResult] = []
    feedback_category_results: list[ChoiceResult] = []
    feedback_severity_results: list[ScoreLevelResult] = []

    # Placeholder tracking mirrors the JeV harness: a family whose non-Jev baseline
    # was not injected (so arm A falls back to abstention / a default constant) is a
    # placeholder and disqualifies any interpretable comparison.
    placeholder_baselines: list[str] = []
    jev_unavailable: list[str] = []
    deepseek_calls = 0
    jev_calls = 0
    explicit_command_turns = 0

    ranked_queries: dict[str, _RankedQuery] = {}

    for sample in samples:
        family = sample.question_family
        answer = sample.label_answer()
        armed = modes.get(sample.definition_id) == "on"

        if sample.label_tier == LABEL_TIER_DISPUTED:
            # No single gold answer: skip all single-label metrics for this sample.
            continue

        if family == FAMILY_TRAJECTORY:
            predicted_action = _predict_intent(
                sample, armed, jev_predictor, deepseek_predictor, deterministic_predictor
            )
            explicit = _explicit_action_for(sample)
            if explicit is not None:
                explicit_command_turns += 1
                predicted_action = explicit
            if predicted_action is None:
                _record_placeholder(family, armed, placeholder_baselines, jev_unavailable)
            anchor_preserved = _anchor_preserved(sample)
            trajectory_results.append(
                TrajectoryResult(
                    sample.sample_id,
                    str(answer.get("choice", "")),
                    predicted_action,
                    anchor_preserved,
                )
            )
            if armed and predicted_action is not None and explicit is None:
                jev_calls += 1
            elif not armed and predicted_action is not None and explicit is None:
                deepseek_calls += 1
            continue

        if family == FAMILY_IMAGE:
            # Deliberately NOT named ``predicted``: this branch carries an answer
            # *string* (``image_predictor`` returns ``str | None``) while every other
            # family carries a prediction *mapping* from ``_predict``. Sharing one
            # name pinned the variable to ``str | None`` for the whole function and
            # produced all 23 of this module's mypy errors (including the 6 that the
            # module-metric collectors added in round 31). Renaming is behaviour-free:
            # this branch appends and ``continue``s.
            predicted_answer = (
                image_predictor(sample.state) if image_predictor is not None else None
            )
            image_results.append(
                ImageResult(sample.sample_id, str(answer.get("answer", "")), predicted_answer)
            )
            continue

        if family in (FAMILY_RETRIEVAL, FAMILY_LOCATOR):
            predicted = _predict(
                sample, armed, jev_predictor, deepseek_predictor, deterministic_predictor
            )
            if predicted is None:
                _record_placeholder(family, armed, placeholder_baselines, jev_unavailable)
            if armed and predicted is not None:
                jev_calls += 1
            elif not armed and predicted is not None:
                deepseek_calls += 1
            score = predicted.get("score_index") if predicted else None
            candidate_id = str(sample.state.get("candidate_id", sample.sample_id))
            query = ranked_queries.setdefault(
                sample.node_id,
                _RankedQuery(
                    query_id=sample.node_id,
                    candidates=(),
                    graded_relevance={},
                    exact_target_id=None,
                    expected_slot=None,
                    top_k=int(sample.state.get("top_k", 3)),
                ),
            )
            ranked_queries[sample.node_id] = _RankedQuery(
                query_id=query.query_id,
                candidates=query.candidates + ((candidate_id, score),),
                graded_relevance={
                    **query.graded_relevance,
                    candidate_id: int(answer.get("score_index", 0)),
                },
                exact_target_id=(
                    str(sample.state["exact_target"])
                    if sample.state.get("exact_target")
                    else query.exact_target_id
                ),
                expected_slot=(
                    int(answer.get("expected_slot", 0))
                    if "expected_slot" in answer
                    else query.expected_slot
                ),
                top_k=int(sample.state.get("top_k", query.top_k)),
            )
            continue

        # Single-question judgement families (choice / score / noul).
        predicted = _predict(
            sample, armed, jev_predictor, deepseek_predictor, deterministic_predictor
        )
        if predicted is None:
            _record_placeholder(family, armed, placeholder_baselines, jev_unavailable)
        if armed and predicted is not None:
            jev_calls += 1
        elif not armed and predicted is not None:
            deepseek_calls += 1

        if family == FAMILY_CITATION:
            citation_results.append(
                CitationResult(
                    sample.sample_id,
                    bool(answer["noul"]),
                    _as_bool(predicted.get("noul") if predicted else None),
                )
            )
        elif family == FAMILY_SPAN_SELECTION:
            span_results.append(
                ChoiceResult(
                    sample.sample_id,
                    str(answer["choice"]),
                    _choice_prediction(predicted),
                )
            )
        elif family == FAMILY_CONTEXT:
            context_results.append(
                KeyFactResult(
                    sample.sample_id,
                    str(sample.state.get("segment_id", sample.sample_id)),
                    bool(answer["noul"]),
                    _as_bool(predicted.get("noul") if predicted else None),
                )
            )
        elif family == FAMILY_INTENT:
            intent_results.append(
                ChoiceResult(
                    sample.sample_id,
                    str(answer["choice"]),
                    _choice_prediction(predicted),
                )
            )
        elif family == FAMILY_PEDAGOGY:
            pedagogy_results.append(
                ChoiceResult(
                    sample.sample_id,
                    str(answer["choice"]),
                    _choice_prediction(predicted),
                )
            )
        elif family == FAMILY_COVERAGE:
            coverage_results.append(
                CoverageResult(
                    sample.sample_id,
                    bool(answer["choice"] == "SUPPORTED"),
                    _coverage_bool(predicted),
                )
            )
        elif family == FAMILY_CRITERION:
            criterion_results.append(
                CriterionResult(
                    sample.sample_id,
                    "criterion",
                    _criterion_grade_from_choice(answer.get("choice")),
                    _criterion_grade(predicted),
                )
            )
        elif family == FAMILY_CLASSIFICATION:
            classification_results.append(
                ChoiceResult(
                    sample.sample_id,
                    str(answer["choice"]),
                    _choice_prediction(predicted),
                )
            )
        elif family == FAMILY_EXERCISE:
            exercise_results.append(
                ChoiceResult(
                    sample.sample_id,
                    str(answer["choice"]),
                    _choice_prediction(predicted),
                )
            )
        elif family == FAMILY_PREREQUISITE:
            prerequisite_results.append(
                ChoiceResult(
                    sample.sample_id,
                    str(answer["choice"]),
                    _choice_prediction(predicted),
                )
            )
        elif family == FAMILY_CORPUS_QUALITY:
            corpus_results.append(
                ScoreLevelResult(
                    sample.sample_id,
                    int(answer["score_index"]),
                    predicted.get("score_index") if predicted else None,
                    sample.option_count - 1,
                )
            )
        elif family == FAMILY_EXTRACTION:
            extraction_results.append(
                ChoiceResult(
                    sample.sample_id,
                    str(answer["choice"]),
                    _choice_prediction(predicted),
                )
            )
        elif family == FAMILY_CONSISTENCY:
            consistency_results.append(
                ChoiceResult(
                    sample.sample_id,
                    str(answer["choice"]),
                    _choice_prediction(predicted),
                )
            )
        elif family == FAMILY_ENTITY:
            entity_results.append(
                ChoiceResult(
                    sample.sample_id,
                    str(answer["choice"]),
                    _choice_prediction(predicted),
                )
            )
        elif family == FAMILY_CAPABILITY:
            capability_results.append(
                ChoiceResult(
                    sample.sample_id,
                    str(answer["choice"]),
                    _choice_prediction(predicted),
                )
            )
        elif family == FAMILY_TOOL_INTENT:
            tool_intent_results.append(
                ChoiceResult(
                    sample.sample_id,
                    str(answer["choice"]),
                    _choice_prediction(predicted),
                )
            )
        elif family == FAMILY_FEEDBACK_CATEGORY:
            feedback_category_results.append(
                ChoiceResult(
                    sample.sample_id,
                    str(answer["choice"]),
                    _choice_prediction(predicted),
                )
            )
        elif family == FAMILY_FEEDBACK_SEVERITY:
            feedback_severity_results.append(
                ScoreLevelResult(
                    sample.sample_id,
                    int(answer["score_index"]),
                    predicted.get("score_index") if predicted else None,
                    sample.option_count - 1,
                )
            )

    # Build retrieval ranking results from the grouped per-candidate scores.
    for query in ranked_queries.values():
        ranked = sorted(
            query.candidates,
            key=lambda pair: (-(pair[1] if pair[1] is not None else -1), pair[0]),
        )
        returned_ids = [cid for cid, _ in ranked]
        relevant = {
            cid
            for cid, grade in query.graded_relevance.items()
            if grade >= RETRIEVAL_RELEVANT_THRESHOLD
        }
        top_k = max(1, min(query.top_k, len(returned_ids)))
        retrieval_results.append(
            RetrievalResult(query.query_id, tuple(returned_ids), frozenset(relevant), top_k)
        )
        if query.exact_target_id is not None:
            slot = query.expected_slot if query.expected_slot is not None else 0
            locator_results.append(
                LocatorResult(query.query_id, query.exact_target_id, slot, tuple(returned_ids))
            )

    kind = transport_kind(transport)
    metrics = {
        "recall_at_k": _mean(
            [recall_at_k(r.returned_ids, r.relevant_ids, r.k) for r in retrieval_results]
        ),
        "mrr": _mean([mrr(r.returned_ids[: r.k], r.relevant_ids) for r in retrieval_results]),
        "ndcg_at_k": _mean(
            [
                ndcg(r.returned_ids, _graded_of(ranked_queries, r.case_id), r.k)
                for r in retrieval_results
            ]
        ),
        "locator_accuracy": locator_accuracy(locator_results),
        "citation_support_accuracy": citation_support_accuracy(citation_results),
        "unsupported_claim_rate": unsupported_claim_rate(citation_results),
        "span_selection_accuracy": choice_accuracy(span_results),
        "key_fact_retention": key_fact_retention(context_results),
        "context_compaction": context_compaction(context_results),
        "intent_accuracy": choice_accuracy(intent_results),
        "pedagogy_accuracy": choice_accuracy(pedagogy_results),
        "classification_accuracy": choice_accuracy(classification_results),
        "exercise_accuracy": choice_accuracy(exercise_results),
        "prerequisite_accuracy": choice_accuracy(prerequisite_results),
        "coverage_confusion": coverage_confusion(coverage_results),
        "criterion_error": criterion_error(criterion_results),
        "corpus_quality_mae": score_level_mae(corpus_results),
        "mainline_recovery_rate": mainline_recovery_rate(trajectory_results),
        "image_answer_accuracy": image_answer_accuracy(image_results),
        # Structured-enhancement module metrics (round 31). Read each conditional rate
        # together with its denominator in ``metric_denominators`` below.
        "extraction_false_acceptance": extraction_false_acceptance(extraction_results),
        "extraction_false_rejection": extraction_false_rejection(extraction_results),
        "entity_false_merge": entity_false_merge(entity_results),
        "entity_missed_alias": entity_missed_alias(entity_results),
        "entity_conflict_false_positive": entity_conflict_false_positive(entity_results),
        "condition_distinction": condition_distinction(consistency_results),
        "capability_misroute": capability_misroute(capability_results),
        "tool_false_allow": tool_false_allow(tool_intent_results),
        "tool_false_block": tool_false_block(tool_intent_results),
        "feedback_category_accuracy": choice_accuracy(feedback_category_results),
        "feedback_severity_mae": score_level_mae(feedback_severity_results),
        "latency_summary": latency_summary([]),
    }
    # The population behind every conditional metric, published so a rate is never read
    # alone: 0.0 with a denominator of 0 means "nothing to measure", not "no errors".
    #
    # The non-module metrics are listed here too, and that is not bookkeeping: on the calibration
    # split several definitions have 1–3 labelled samples, so a single sample moves a rate by
    # 33–100 points. Without the denominator, `key_fact_retention` falling from 1.000 to 0.000 looks
    # like a regression when it is one sample, and a reader cannot tell the two apart.
    metric_denominators = {
        "recall_at_k": len(retrieval_results),
        "mrr": len(retrieval_results),
        "ndcg_at_k": len(retrieval_results),
        "locator_accuracy": len(locator_results),
        "citation_support_accuracy": len(citation_results),
        "unsupported_claim_rate": len(citation_results),
        "span_selection_accuracy": len(span_results),
        "key_fact_retention": len(context_results),
        "context_compaction": len(context_results),
        "intent_accuracy": len(intent_results),
        "pedagogy_accuracy": len(pedagogy_results),
        "classification_accuracy": len(classification_results),
        "exercise_accuracy": len(exercise_results),
        "prerequisite_accuracy": len(prerequisite_results),
        "coverage_confusion": len(coverage_results),
        "criterion_error": len(criterion_results),
        "corpus_quality_mae": len(corpus_results),
        "mainline_recovery_rate": len(trajectory_results),
        "image_answer_accuracy": len(image_results),
        "extraction_false_acceptance": sum(
            1 for r in extraction_results if r.label_choice in EXTRACTION_DEFECT_LABELS
        ),
        "extraction_false_rejection": sum(
            1 for r in extraction_results if r.label_choice == "GROUNDED"
        ),
        "entity_false_merge": sum(
            1 for r in entity_results if r.label_choice not in ENTITY_SAME_LABELS
        ),
        "entity_missed_alias": sum(
            1 for r in entity_results if r.label_choice == "ALIAS"
        ),
        "entity_conflict_false_positive": sum(
            1
            for r in entity_results
            if r.label_choice in ENTITY_SAME_LABELS or r.label_choice == "RELATED_NOT_SAME"
        ),
        "condition_distinction": sum(
            1 for r in consistency_results if r.label_choice in CONDITION_DIFFERENCE_LABELS
        ),
        "capability_misroute": len(capability_results),
        "tool_false_allow": sum(
            1
            for r in tool_intent_results
            if r.label_choice == "INCONSISTENT_WITH_INTENT"
        ),
        "tool_false_block": sum(
            1 for r in tool_intent_results if r.label_choice == "CONSISTENT"
        ),
        "feedback_category_accuracy": len(feedback_category_results),
        "feedback_severity_mae": len(feedback_severity_results),
    }
    result = {
        "arm": arm,
        "modes": modes,
        "transport": kind,
        "dataset_status": dataset_status,
        "interpretation": interpretation_for(kind, dataset_status),
        "case_counts": {
            "retrieval": len(retrieval_results),
            "locator": len(locator_results),
            "citation": len(citation_results),
            "span_selection": len(span_results),
            "context": len(context_results),
            "intent": len(intent_results),
            "pedagogy": len(pedagogy_results),
            "coverage": len(coverage_results),
            "criterion": len(criterion_results),
            "classification": len(classification_results),
            "exercise": len(exercise_results),
            "prerequisite": len(prerequisite_results),
            "corpus_quality": len(corpus_results),
            "trajectory": len(trajectory_results),
            "image": len(image_results),
            "extraction": len(extraction_results),
            "consistency": len(consistency_results),
            "entity_relation": len(entity_results),
            "capability": len(capability_results),
            "tool_intent": len(tool_intent_results),
            "feedback_category": len(feedback_category_results),
            "feedback_severity": len(feedback_severity_results),
        },
        "metric_denominators": metric_denominators,
        "jev_calls": jev_calls,
        "deepseek_calls": deepseek_calls,
        "deepseek_call_delta_from_A": None,  # filled by compare; A is the reference arm
        "local_resource_use": {
            "jev_calls": jev_calls,
            "note": (
                "Jev is self-hosted; local GPU/RAM was not measured in this environment."
            ),
        },
        "explicit_command_turns_no_model_call": explicit_command_turns,
        "placeholder_baselines": placeholder_baselines,
        "jev_unavailable": jev_unavailable,
        "metrics": metrics,
        "per_case": {
            "retrieval": [_retrieval_asdict(r) for r in retrieval_results],
            "citation": [_citation_asdict(r) for r in citation_results],
            "coverage": [_coverage_asdict(r) for r in coverage_results],
            "criterion": [_criterion_asdict(r) for r in criterion_results],
            "trajectory": [_trajectory_asdict(r) for r in trajectory_results],
            "image": [_image_asdict(r) for r in image_results],
            # The families whose rates are computed over a handful of samples, so a metric that
            # moves can be read against the cases themselves rather than only its value.
            "intent": [_choice_asdict(r) for r in intent_results],
            "pedagogy": [_choice_asdict(r) for r in pedagogy_results],
            "span_selection": [_choice_asdict(r) for r in span_results],
            "exercise": [_choice_asdict(r) for r in exercise_results],
            "prerequisite": [_choice_asdict(r) for r in prerequisite_results],
            "context": [_key_fact_asdict(r) for r in context_results],
        },
    }
    if arm in COMPONENT_ARM_NAMES:
        result["component"] = _component_report(arm, samples, metrics)
    return result


def _predict(
    sample: JevJudgment,
    armed: bool,
    jev_predictor: Callable[[JevJudgment], dict[str, Any] | None] | None,
    deepseek_predictor: Callable[[JevJudgment], dict[str, Any] | None] | None,
    deterministic_predictor: Callable[[JevJudgment], dict[str, Any] | None] | None,
) -> dict[str, Any] | None:
    if armed:
        return jev_predictor(sample) if jev_predictor is not None else None
    if deterministic_predictor is not None:
        result = deterministic_predictor(sample)
        if result is not None:
            return result
    if deepseek_predictor is not None:
        return deepseek_predictor(sample)
    return None


def _choice_prediction(predicted: dict[str, Any] | None) -> str | None:
    return str(predicted["choice"]) if predicted and predicted.get("choice") is not None else None


def _predict_intent(
    sample: JevJudgment,
    armed: bool,
    jev_predictor: Callable[[JevJudgment], dict[str, Any] | None] | None,
    deepseek_predictor: Callable[[JevJudgment], dict[str, Any] | None] | None,
    deterministic_predictor: Callable[[JevJudgment], dict[str, Any] | None] | None,
) -> str | None:
    explicit = _explicit_action_for(sample)
    if explicit is not None:
        return explicit
    predicted = _predict(sample, armed, jev_predictor, deepseek_predictor, deterministic_predictor)
    return _choice_prediction(predicted)


def _explicit_action_for(sample: JevJudgment) -> str | None:
    message = sample.state.get("message")
    if not isinstance(message, str):
        return None
    return route_explicit_command(
        message,
        current_mode=sample.state.get("current_mode"),
        active_assessment=sample.state.get("active_assessment"),
    )


def _anchor_preserved(sample: JevJudgment) -> bool:
    # Fixed anchors are preserved unconditionally by the product; the harness never
    # offers the anchor itself to a semantic decision, so it cannot be dropped.
    return True


def _record_placeholder(
    family: str, armed: bool, placeholders: list[str], jev_unavailable: list[str]
) -> None:
    if armed:
        jev_unavailable.append(f"{family}:jev-not-injected")
    else:
        placeholders.append(f"{family}:abstention")


def _graded_of(ranked_queries: dict[str, _RankedQuery], query_id: str) -> dict[str, int]:
    query = ranked_queries.get(query_id)
    return query.graded_relevance if query is not None else {}


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value >= 0.5)
    return None


def _coverage_bool(predicted: dict[str, Any] | None) -> bool | None:
    if predicted is None:
        return None
    choice = predicted.get("choice")
    if choice == "SUPPORTED":
        return True
    if choice in {"PARTIAL", "UNSUPPORTED", "UNCERTAIN"}:
        return False
    return None


def _criterion_grade_from_choice(choice: Any) -> int:
    return {"SATISFIED": 0, "PARTIAL": 1, "NOT_SATISFIED": 2}.get(choice, 2)


def _criterion_grade(predicted: dict[str, Any] | None) -> int | None:
    if predicted is None:
        return None
    if "grade" in predicted and predicted["grade"] is not None:
        return int(predicted["grade"])
    return _criterion_grade_from_choice(predicted.get("choice"))


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _retrieval_asdict(result: RetrievalResult) -> dict[str, Any]:
    return {
        "case_id": result.case_id,
        "returned_ids": list(result.returned_ids),
        "relevant_ids": sorted(result.relevant_ids),
        "k": result.k,
    }


def _choice_asdict(result: ChoiceResult) -> dict[str, Any]:
    """One choice decision: what was labelled, what was predicted, and whether they agree.

    Published for `intent`, `pedagogy`, `span_selection` and `exercise` so a metric that moves can
    be traced to the *cases* that moved it. That is not a convenience: on the calibration split
    `intent.next_action.v1` has six labelled samples, and the live comparison showed Jev scoring 4/6
    against the baseline's 6/6 — a difference of two samples that cannot be explained, or fixed,
    without seeing which two.
    """
    return {
        "case_id": result.case_id,
        "label": result.label_choice,
        "predicted": result.predicted_choice,
        "agrees": result.predicted_choice == result.label_choice,
    }


def _key_fact_asdict(result: KeyFactResult) -> dict[str, Any]:
    """One context segment: whether the label says keep and whether Jev said keep."""
    return {
        "case_id": result.case_id,
        "segment_id": result.segment_id,
        "label_keep": result.label_keep,
        "predicted_keep": result.predicted_keep,
        "agrees": result.predicted_keep == result.label_keep,
    }


def _citation_asdict(result: CitationResult) -> dict[str, Any]:
    return {
        "case_id": result.case_id,
        "label_supported": result.label_supported,
        "predicted_supported": result.predicted_supported,
    }


def _coverage_asdict(result: CoverageResult) -> dict[str, Any]:
    return {
        "case_id": result.case_id,
        "label_supported": result.label_supported,
        "predicted_supported": result.predicted_supported,
    }


def _criterion_asdict(result: CriterionResult) -> dict[str, Any]:
    return {
        "case_id": result.case_id,
        "criterion_id": result.criterion_id,
        "label_grade": result.label_grade,
        "predicted_grade": result.predicted_grade,
    }


def _trajectory_asdict(result: TrajectoryResult) -> dict[str, Any]:
    return {
        "case_id": result.case_id,
        "expected_action": result.expected_action,
        "predicted_action": result.predicted_action,
        "anchor_preserved": result.anchor_preserved,
    }


def _image_asdict(result: ImageResult) -> dict[str, Any]:
    return {
        "case_id": result.case_id,
        "label_answer": result.label_answer,
        "predicted_answer": result.predicted_answer,
    }


# ------------------------------------------------------------------ comparison


def compare_jev_arms(
    runs: Mapping[str, dict[str, Any]], *, request_quality: bool = False
) -> dict[str, Any]:
    """Compare arm run summaries, refusing any improvement verdict from fake/unlabelled runs.

    Reuses the JeV harness's refusal semantics exactly (``jev_ablation.compare_arms``):
    a fake transport, an unlabelled dataset, or any placeholder baseline forces
    ``NOT_INTERPRETABLE``, and ``request_quality=True`` raises. This wrapper adds the
    Jev-specific ``jev_unavailable`` refusals, refuses a quality verdict whenever a
    component arm reports ``INSUFFICIENT_SAMPLES`` for any of its module metrics, and
    computes the DeepSeek call delta against arm A when the comparison is interpretable.
    """
    verdict = compare_arms(runs, request_quality=request_quality)
    if verdict.get("verdict") != "INTERPRETABLE":
        return verdict

    # A component arm whose module-specific metric has no labelled samples must never
    # feed a quality verdict: INSUFFICIENT_SAMPLES is a refusal, exactly like a fake
    # transport or a placeholder baseline.
    insufficient = {
        arm: sorted(run.get("component", {}).get("insufficient_samples") or [])
        for arm, run in sorted(runs.items())
        if run.get("component", {}).get("insufficient_samples")
    }
    if insufficient:
        if request_quality:
            raise ValueError(
                "Refusing a quality claim: component arm(s) report INSUFFICIENT_SAMPLES "
                f"{insufficient}; no module-specific metric was measured."
            )
        return {
            "verdict": "NOT_INTERPRETABLE",
            "reason": "INSUFFICIENT_SAMPLES in component arm(s)",
            "insufficient_samples": insufficient,
            "arms": sorted(runs),
        }

    # Live + labelled + real baselines: attach the DeepSeek call delta vs arm A and the
    # Jev self-hosted resource delta, without making any improvement claim.
    a_calls = int(runs.get("A", {}).get("deepseek_calls", 0))
    verdict["deepseek_call_delta_vs_A"] = {
        arm: int(run.get("deepseek_calls", 0)) - a_calls
        for arm, run in sorted(runs.items())
    }
    return verdict
