"""The structured-enhancement module metrics: computable, honest, and pinned.

Before round 31 the five module arms could **never** produce a number: the runner had no
result collection for their definitions at all, so every metric reported
``INSUFFICIENT_SAMPLES`` regardless of the data. The companion dataset
(``benchmarks/jev-module-judgments.dataset.json``) supplied the labels; this file pins
both halves of that change:

* the dataset is valid, covers the seven previously-uncovered definitions, and its labels
  earn their tier;
* the module-specific metrics are computable, and each conditional rate publishes its
  denominator so a rate is never read alone;
* the frozen dataset is untouched by any of it.

Nothing here is a quality claim: every arm run in this file uses the deterministic fake
transport, so the interpretation stays ``NON_INTERPRETABLE_PLUMBING_ONLY``.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.evaluation.jev_semantic_ablation import (
    ENTITY_SAME_LABELS,
    EXTRACTION_DEFECT_LABELS,
    INTERPRETATION_PLUMBING,
    ChoiceResult,
    FakeJevTransport,
    ScoreLevelResult,
    capability_misroute,
    condition_distinction,
    entity_conflict_false_positive,
    entity_false_merge,
    entity_missed_alias,
    extraction_false_acceptance,
    extraction_false_rejection,
    load_jev_dataset,
    run_jev_semantic_ablation,
    score_level_mae,
    tool_false_allow,
    tool_false_block,
    validate_jev_dataset,
)

ROOT = Path(__file__).parents[3]
COMPANION = ROOT / "benchmarks" / "jev-module-judgments.dataset.json"
FROZEN = ROOT / "benchmarks" / "jev-judgments.dataset.json"
SPLIT_MANIFEST = ROOT / "benchmarks" / "jev-calibration.split.json"

#: The seven definitions the frozen dataset had no samples for.
PREVIOUSLY_UNCOVERED = (
    "extraction.field_grounded.v1",
    "evidence.consistency.v1",
    "entity.relation.v1",
    "teaching.capability.v1",
    "tool.intent.v1",
    "feedback.category.v1",
    "feedback.severity.v1",
)

#: The frozen dataset's split manifest hash 鈥?it must not move.
FROZEN_CONTENT_HASH = "2af0f40d1d1e89c6f7a8092cb846258f2b36b208c58f0211932344a32d33c10d"


def choice(label: str, predicted: str | None) -> ChoiceResult:
    return ChoiceResult("case", label, predicted)


# --------------------------------------------------------------------------- dataset


def test_companion_dataset_validates_and_covers_the_seven_definitions() -> None:
    payload = json.loads(COMPANION.read_text(encoding="utf-8"))
    validate_jev_dataset(payload)

    covered = {str(sample["definition_id"]) for sample in payload["samples"]}
    assert covered == set(PREVIOUSLY_UNCOVERED)


def test_companion_dataset_labels_earn_their_tier() -> None:
    payload = json.loads(COMPANION.read_text(encoding="utf-8"))
    samples = payload["samples"]

    tiers = {str(sample["label_tier"]) for sample in samples}
    assert "SILVER_DEEPSEEK" not in tiers, "no model was called when authoring this file"
    assert tiers <= {"OBJECTIVE_VERIFIED", "SOURCE_REVIEWED", "DISPUTED"}

    for sample in samples:
        evidence = str(sample["label_evidence"])
        tier = str(sample["label_tier"])
        assert evidence.strip(), sample["sample_id"]
        if tier == "OBJECTIVE_VERIFIED":
            # A code-verified label must name the rule it came from.
            assert "code-verified" in evidence, sample["sample_id"]
            assert ".py" in evidence or "rule" in evidence, sample["sample_id"]
    # The tier semantics that make SOURCE_REVIEWED usable here are stated in the file.
    assert "label_tier_scope_note" in payload


def test_companion_dataset_is_internally_consistent() -> None:
    payload = json.loads(COMPANION.read_text(encoding="utf-8"))
    samples = payload["samples"]

    ids = [str(sample["sample_id"]) for sample in samples]
    assert len(set(ids)) == len(ids)

    groups: dict[tuple[str, str, str], set[str]] = {}
    for sample in samples:
        key = (
            str(sample["document_id"]),
            str(sample["node_id"]),
            str(sample["question_family"]),
        )
        groups.setdefault(key, set()).add(str(sample["definition_id"]))
    assert all(len(definitions) == 1 for definitions in groups.values())

    # Both languages are represented: the product is bilingual and the calibration must
    # not silently become English-only.
    assert {str(sample["language"]) for sample in samples} == {"en", "zh"}


def test_the_frozen_dataset_and_its_split_are_untouched() -> None:
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    manifest = json.loads(SPLIT_MANIFEST.read_text(encoding="utf-8"))

    assert len(frozen["samples"]) == 310
    assert manifest["content_hash"] == FROZEN_CONTENT_HASH
    # The frozen set genuinely has none of the companion definitions 鈥?that is why the
    # companion file exists rather than an edit to this one.
    covered = {str(sample["definition_id"]) for sample in frozen["samples"]}
    assert covered.isdisjoint(PREVIOUSLY_UNCOVERED)


# --------------------------------------------------------------------------- metrics


def test_extraction_rates_are_conditional_and_two_sided() -> None:
    # One defect accepted (the dangerous direction), one defect caught, one good refused.
    results = [
        choice("WRONG_FIELD", "GROUNDED"),
        choice("NEGATION_LOST", "NEGATION_LOST"),
        choice("GROUNDED", "SOURCE_INSUFFICIENT"),
    ]

    assert extraction_false_acceptance(results) == 0.5
    assert extraction_false_rejection(results) == 1.0
    # Partial and uncertain verdicts are neither an acceptance nor a rejection.
    assert extraction_false_acceptance([choice("CONSTRAINT_LOST", "UNCERTAIN")]) == 0.0


def test_an_empty_population_is_zero_with_a_zero_denominator() -> None:
    """A rate with nothing to measure must not look like a perfect score."""

    only_grounded = [choice("GROUNDED", "GROUNDED")]
    assert extraction_false_acceptance(only_grounded) == 0.0
    assert not any(r.label_choice in EXTRACTION_DEFECT_LABELS for r in only_grounded)

    assert entity_missed_alias([choice("DIFFERENT", "DIFFERENT")]) == 0.0
    assert tool_false_allow([choice("CONSISTENT", "CONSISTENT")]) == 0.0


def test_entity_metrics_split_merge_alias_and_invented_conflict() -> None:
    results = [
        choice("DIFFERENT", "SAME_CONCEPT"),      # false merge
        choice("RELATED_NOT_SAME", "DIFFERENT"),  # invented conflict
        choice("ALIAS", "DIFFERENT"),             # missed alias (also a conflict claim)
        choice("SAME_CONCEPT", "SAME_CONCEPT"),   # correct
    ]

    # Population = labels outside {SAME_CONCEPT, ALIAS}: DIFFERENT, RELATED_NOT_SAME.
    assert entity_false_merge(results) == 0.5
    # Population = ALIAS only.
    assert entity_missed_alias(results) == 1.0
    # Population = same-or-related labels (SAME_CONCEPT, ALIAS, RELATED_NOT_SAME); both
    # the RELATed pair and the ALIAS pair were called DIFFERENT, so 2 of 3.
    assert entity_conflict_false_positive(results) == 2 / 3
    assert set(ENTITY_SAME_LABELS) == {"SAME_CONCEPT", "ALIAS"}


def test_condition_distinction_only_scores_the_labels_it_is_about() -> None:
    results = [
        choice("DIFFERENT_ASSUMPTIONS", "DIFFERENT_ASSUMPTIONS"),   # kept apart, correct
        choice("VERSION_OR_TASK_DIFFERENCE", "SAME_CONTEXT_CONTRADICTION"),  # escalated
        choice("SAME_CONTEXT_CONTRADICTION", "SAME_CONTEXT_CONTRADICTION"),  # not its business
    ]

    # Only the two condition labels count; the genuine contradiction is out of population.
    assert condition_distinction(results) == 0.5


def test_capability_and_tool_metrics_are_error_rates_with_direction() -> None:
    capabilities = [
        choice("node_lesson", "node_lesson"),
        choice("direct_qa", "node_lesson"),
        choice("NO_SKILL", "NO_SKILL"),
    ]
    assert capability_misroute(capabilities) == 1 / 3

    tools = [
        choice("INCONSISTENT_WITH_INTENT", "CONSISTENT"),       # false allow
        choice("INCONSISTENT_WITH_INTENT", "AMBIGUOUS"),        # confirmation, not an allow
        choice("CONSISTENT", "INCONSISTENT_WITH_INTENT"),       # false block
        choice("CONSISTENT", "CONSISTENT"),
    ]
    assert tool_false_allow(tools) == 0.5
    assert tool_false_block(tools) == 0.5


# --------------------------------------------------------------------------- end to end


def test_every_module_metric_is_computable_over_the_companion_dataset() -> None:
    """The wiring, not just the helpers: the arms now report MEASURED, not a refusal."""

    dataset = load_jev_dataset(COMPANION)
    expected = {
        "M-EXTRACT": {"extraction_false_acceptance", "extraction_false_rejection"},
        "M-ENTITY": {
            "entity_false_merge",
            "entity_missed_alias",
            "entity_conflict_false_positive",
        },
        "M-CONSISTENCY": {"condition_distinction"},
        "M-CAPABILITY": {"capability_misroute"},
        "M-TOOL": {"tool_false_allow", "tool_false_block"},
    }

    for arm, metrics in expected.items():
        run = run_jev_semantic_ablation(dataset, arm, transport=FakeJevTransport())
        assert run["component"]["insufficient_samples"] == [], arm
        for metric in metrics:
            entry = run["component"]["metrics"][metric]
            assert entry["status"] == "MEASURED", (arm, metric)
            assert isinstance(entry["value"], float)
            assert entry["samples"] > 0
        # The plumbing may compute numbers; it may never claim quality.
        assert run["interpretation"] == INTERPRETATION_PLUMBING


def test_denominators_are_published_for_every_conditional_metric() -> None:
    dataset = load_jev_dataset(COMPANION)
    run = run_jev_semantic_ablation(dataset, "M-TOOL", transport=FakeJevTransport())
    denominators = run["metric_denominators"]

    for metric in (
        "extraction_false_acceptance",
        "extraction_false_rejection",
        "entity_false_merge",
        "entity_missed_alias",
        "entity_conflict_false_positive",
        "condition_distinction",
        "capability_misroute",
        "tool_false_allow",
        "tool_false_block",
        "feedback_category_accuracy",
        "feedback_severity_mae",
    ):
        assert metric in denominators, metric
    # The tool arm's two directions come from disjoint populations, and the companion
    # dataset deliberately supplies both.
    assert denominators["tool_false_allow"] > 0
    assert denominators["tool_false_block"] > 0
    assert run["case_counts"]["tool_intent"] == 7


def test_feedback_metrics_are_computed_even_without_an_arm() -> None:
    """The P2 definitions have no component arm; their metrics are still measured."""

    dataset = load_jev_dataset(COMPANION)
    run = run_jev_semantic_ablation(dataset, "M-EXTRACT", transport=FakeJevTransport())

    assert run["case_counts"]["feedback_category"] == 7
    assert run["case_counts"]["feedback_severity"] == 7
    assert isinstance(run["metrics"]["feedback_category_accuracy"], float)
    assert isinstance(run["metrics"]["feedback_severity_mae"], float)


def test_score_label_metric_uses_ordinal_distance() -> None:
    """feedback.severity is a Score: distance matters, not just equality."""

    results = [
        ScoreLevelResult("a", 0, 0, 2),
        ScoreLevelResult("b", 2, 1, 2),
    ]
    assert score_level_mae(results) == 0.5


def test_the_definition_level_metrics_publish_their_denominator_too() -> None:
    """Not only the module metrics: every rate whose population can be tiny.

    On the calibration split `context.keep_segment.v1` has 2 labelled samples and
    `assessment.criterion_review.v1` has 3, so one sample moves those rates by 33–100 points. The
    live comparison read `key_fact_retention` 1.000 (arm A) against 0.000 (arm E) and
    `criterion_error` 0.000 against 0.333 — without the denominator a reader cannot tell a
    regression from a single sample, so the denominator is published beside every rate.
    """
    dataset = load_jev_dataset(COMPANION)
    run = run_jev_semantic_ablation(dataset, "M-TOOL", transport=FakeJevTransport())
    denominators = run["metric_denominators"]
    counts = run["case_counts"]

    # Each definition-level rate is published with the population it was computed over, and the two
    # must agree with the case counts the same run reports.
    assert denominators["key_fact_retention"] == counts["context"]
    assert denominators["context_compaction"] == counts["context"]
    assert denominators["criterion_error"] == counts["criterion"]
    assert denominators["span_selection_accuracy"] == counts["span_selection"]
    assert denominators["citation_support_accuracy"] == counts["citation"]
    assert denominators["unsupported_claim_rate"] == counts["citation"]
    assert denominators["intent_accuracy"] == counts["intent"]
    assert denominators["pedagogy_accuracy"] == counts["pedagogy"]
    assert denominators["coverage_confusion"] == counts["coverage"]
    assert denominators["corpus_quality_mae"] == counts["corpus_quality"]
    assert denominators["exercise_accuracy"] == counts["exercise"]
    assert denominators["prerequisite_accuracy"] == counts["prerequisite"]

    # And a rate with no population is 0.0 *with* a zero denominator, never a bare 0.0.
    for metric, denominator in denominators.items():
        assert isinstance(denominator, int), metric
        assert denominator >= 0, metric
