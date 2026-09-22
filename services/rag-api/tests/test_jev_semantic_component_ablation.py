"""Trustworthiness tests for the six structured-enhancement component arms.

The A/B/C/D/E harness measures the semantic-decision layer; the six component arms
(``M-EXTRACT``, ``M-ENTITY``, ``M-CONSISTENCY``, ``M-CITATION``, ``M-CAPABILITY``,
``M-TOOL``) measure the six structured-enhancement modules against the same arm-A
baseline. These tests prove:

(a) A–E nesting is unchanged and still validated;
(b) each component arm is differentiated from the baseline at the plumbing level
    (and, for the one family that has labelled samples, at the metric level);
(c) a module with no labelled samples reports ``INSUFFICIENT_SAMPLES`` and no number;
(d) fake transport forces ``NON_INTERPRETABLE_PLUMBING_ONLY`` and a refused quality
    verdict — and so does a live component arm with ``INSUFFICIENT_SAMPLES``;
(e) the component arms do not change any A–E result.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.evaluation.jev_semantic_ablation import (
    ALL_ARM_NAMES,
    ARM_NAMES,
    COMPONENT_ARM_NAMES,
    DATASET_STATUS_LABELLED,
    INSUFFICIENT_SAMPLES,
    INTERPRETATION_PLUMBING,
    TRANSPORT_LIVE,
    FakeJevTransport,
    arm_modes,
    compare_jev_arms,
    deterministic_fake_jev_predictor,
    load_jev_dataset,
    run_jev_semantic_ablation,
    validate_arm_nesting,
)

ROOT = Path(__file__).parents[3]
DATASET = ROOT / "benchmarks" / "jev-judgments.dataset.json"

# The frozen A–E on-keys (the historical definitions must not change).
EXPECTED_E_ON_KEYS = {
    "retrieval.support.v1",
    "context.keep_segment.v1",
    "intent.next_action.v1",
    "pedagogy.next_method.v1",
    "coverage.item_support.v1",
    "assessment.criterion_review.v1",
    "source.supports_claim.v1",
    "source.select_span.v1",
}

# Each component arm turns on exactly its module's decision definition key(s).
EXPECTED_COMPONENT_ON_KEYS = {
    "M-EXTRACT": {"extraction.field_grounded.v1"},
    "M-ENTITY": {"entity.relation.v1"},
    "M-CONSISTENCY": {"evidence.consistency.v1"},
    "M-CITATION": {"source.supports_claim.v1", "source.select_span.v1"},
    "M-CAPABILITY": {"teaching.capability.v1"},
    "M-TOOL": {"tool.intent.v1"},
}

# The metric(s) each module owns, and the ones with no labelled samples in the frozen
# dataset (reported as INSUFFICIENT_SAMPLES, never a number).
EXPECTED_INSUFFICIENT = {
    "M-EXTRACT": ["extraction_false_acceptance", "extraction_false_rejection"],
    "M-ENTITY": ["entity_conflict_false_positive", "entity_false_merge", "entity_missed_alias"],
    "M-CONSISTENCY": ["condition_distinction"],
    "M-CAPABILITY": ["capability_misroute"],
    "M-TOOL": ["tool_false_allow", "tool_false_block"],
}

# The exact key set of a historical A–E summary (no component annotation leaks in).
EXPECTED_AE_KEYS = {
    "arm",
    "modes",
    "transport",
    "dataset_status",
    "interpretation",
    "case_counts",
    "jev_calls",
    "deepseek_calls",
    "deepseek_call_delta_from_A",
    "local_resource_use",
    "explicit_command_turns_no_model_call",
    "placeholder_baselines",
    "jev_unavailable",
    "metrics",
    "per_case",
    # Added in round 31, and the reason is stated rather than assumed: the module
    # metrics are conditional (rate + population), and a conditional rate read without
    # its denominator is how a metric starts lying. The denominators therefore belong
    # to the run's metric reporting for every arm, A–E included — this is the one key
    # the historical set grew by, not a component annotation leaking in.
    "metric_denominators",
}


def _offline(arm: str) -> dict:
    dataset = load_jev_dataset(DATASET)
    return run_jev_semantic_ablation(
        dataset,
        arm,
        transport=FakeJevTransport(),
        jev_predictor=deterministic_fake_jev_predictor,
    )


# ------------------------------------------------------------------ (a) A–E unchanged


def test_arm_registry_and_nesting_are_unchanged() -> None:
    assert ARM_NAMES == ("A", "B", "C", "D", "E")
    assert ALL_ARM_NAMES == ARM_NAMES + COMPONENT_ARM_NAMES
    assert len(set(ALL_ARM_NAMES)) == len(ALL_ARM_NAMES)  # distinct, no overlap
    validate_arm_nesting()  # must not raise


def test_a_e_modes_are_unchanged_by_component_arms() -> None:
    a_on = {k for k, mode in arm_modes("A").items() if mode == "on"}
    e_on = {k for k, mode in arm_modes("E").items() if mode == "on"}
    assert a_on == set()
    assert e_on == EXPECTED_E_ON_KEYS


# ------------------------------------------------------------------ (b) differentiated


def test_each_component_arm_turns_on_only_its_module_key() -> None:
    for arm, on_keys in EXPECTED_COMPONENT_ON_KEYS.items():
        modes = arm_modes(arm)
        turned_on = {k for k, mode in modes.items() if mode == "on"}
        # Exactly the module's own key(s), never anything else in the catalog.
        assert turned_on == on_keys
        # Plumbing-level difference vs the arm-A baseline is always visible.
        assert modes != arm_modes("A")


def test_m_citation_is_differentiated_from_the_a_baseline() -> None:
    a = _offline("A")
    m = _offline("M-CITATION")
    # On the fake transport the citation/span predictions change when the module's
    # two keys are armed, so the shared metric implementations see a real difference.
    assert m["metrics"]["citation_support_accuracy"] != a["metrics"]["citation_support_accuracy"]
    assert m["metrics"]["span_selection_accuracy"] != a["metrics"]["span_selection_accuracy"]
    # And the component annotation records it as measured, not insufficient.
    assert m["component"]["insufficient_samples"] == []


# ------------------------------------------------------------------ (c) insufficient


@pytest.mark.parametrize("arm", sorted(EXPECTED_INSUFFICIENT))
def test_module_without_labels_reports_insufficient_and_no_number(arm: str) -> None:
    summary = _offline(arm)
    component = summary["component"]
    assert component["insufficient_samples"] == EXPECTED_INSUFFICIENT[arm]
    for metric in EXPECTED_INSUFFICIENT[arm]:
        entry = component["metrics"][metric]
        assert entry["status"] == INSUFFICIENT_SAMPLES
        assert entry["samples"] == 0
        assert "value" not in entry  # no number, no zero, no placeholder


def test_m_citation_reports_measured_not_insufficient() -> None:
    summary = _offline("M-CITATION")
    component = summary["component"]
    assert component["insufficient_samples"] == []
    measured_metrics = (
        "citation_support_accuracy",
        "unsupported_claim_rate",
        "span_selection_accuracy",
    )
    for metric in measured_metrics:
        assert component["metrics"][metric]["status"] == "MEASURED"
        assert "value" in component["metrics"][metric]


# ------------------------------------------------------------------ (d) honesty refusals


def test_component_arms_offline_are_plumbing_only() -> None:
    for arm in COMPONENT_ARM_NAMES:
        summary = _offline(arm)
        assert summary["transport"] == "deterministic_fake"
        assert summary["interpretation"] == INTERPRETATION_PLUMBING


def test_compare_refuses_quality_from_fake_component_runs() -> None:
    runs = {arm: _offline(arm) for arm in COMPONENT_ARM_NAMES}
    verdict = compare_jev_arms(runs)
    assert verdict["verdict"] == "NOT_INTERPRETABLE"
    with pytest.raises(ValueError, match="deterministic fake transport"):
        compare_jev_arms(runs, request_quality=True)


def test_compare_refuses_quality_when_a_live_component_arm_is_insufficient() -> None:
    live_a = {
        "transport": TRANSPORT_LIVE,
        "dataset_status": DATASET_STATUS_LABELLED,
        "placeholder_baselines": [],
        "deepseek_calls": 10,
    }
    live_insufficient = {
        "transport": TRANSPORT_LIVE,
        "dataset_status": DATASET_STATUS_LABELLED,
        "placeholder_baselines": [],
        "deepseek_calls": 10,
        "component": {
            "insufficient_samples": ["extraction_false_acceptance", "extraction_false_rejection"],
        },
    }
    verdict = compare_jev_arms({"A": live_a, "M-EXTRACT": live_insufficient})
    assert verdict["verdict"] == "NOT_INTERPRETABLE"
    assert verdict["reason"] == "INSUFFICIENT_SAMPLES in component arm(s)"
    with pytest.raises(ValueError, match="INSUFFICIENT_SAMPLES"):
        compare_jev_arms({"A": live_a, "M-EXTRACT": live_insufficient}, request_quality=True)


# ------------------------------------------------------------------ (e) A–E unaffected


def test_component_arms_do_not_change_any_a_e_result() -> None:
    dataset = load_jev_dataset(DATASET)

    def run(arm: str) -> dict:
        return run_jev_semantic_ablation(
            dataset,
            arm,
            transport=FakeJevTransport(),
            jev_predictor=deterministic_fake_jev_predictor,
        )

    a_e = {arm: run(arm) for arm in ARM_NAMES}
    # Running the component arms alongside must not mutate any A–E summary: the harness
    # is pure, and the component arms never redefine the historical arms.
    for arm in COMPONENT_ARM_NAMES:
        run(arm)
    a_e_rechecked = {arm: run(arm) for arm in ARM_NAMES}
    assert a_e_rechecked == a_e
    # A–E summaries keep their historical key set (no component annotation leaks in).
    assert set(a_e["A"]) == EXPECTED_AE_KEYS
    assert set(a_e["E"]) == EXPECTED_AE_KEYS
