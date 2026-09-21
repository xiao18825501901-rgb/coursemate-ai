"""Trustworthiness tests for the A/B/C/D Jev ablation harness.

These prove (1) every metric against hand-computed values, (2) the arm nesting and
the fake/live honesty guardrails, (3) that a full offline run produces the metric
dict for each arm, and (4) that the harness writes only Jev receipts and never
learning/grade/coverage state.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jev_fixtures import make_jev_database

from app.evaluation.jev_ablation import (
    DATASET_STATUS_EXAMPLE,
    DATASET_STATUS_LABELLED,
    INTERPRETATION_PLUMBING,
    AblationCaseSet,
    CitationResult,
    CoverageResult,
    CriterionResult,
    ImageResult,
    LocatorResult,
    RetrievalCandidate,
    RetrievalCase,
    TrajectoryResult,
    arm_modes,
    citation_support_accuracy,
    compare_arms,
    cost_split,
    coverage_confusion,
    criterion_error,
    deterministic_fake_responder,
    estimate_input_token_ceilings,
    failure_rate,
    image_answer_accuracy,
    latency_summary,
    load_ablation_cases,
    locator_accuracy,
    mainline_recovery_rate,
    mrr,
    recall_at_k,
    run_ablation,
    unsupported_claim_rate,
    validate_arm_nesting,
)
from app.evaluation.model_benchmark import calculate_cost_ceiling
from app.jev.gateway import FakeTransport
from app.jev.receipt_store import SqlReceiptStore

EXAMPLE = Path(__file__).parents[3] / "benchmarks" / "jev-ablation-cases.example.json"

METRIC_KEYS = {
    "recall_at_k",
    "mrr",
    "locator_accuracy",
    "citation_support_accuracy",
    "unsupported_claim_rate",
    "mainline_recovery_rate",
    "coverage_confusion",
    "criterion_error",
    "image_answer_accuracy",
    "latency_summary",
    "cost_split",
    "failure_rate",
}


# ------------------------------------------------------------------ arm nesting


def test_arm_nesting_is_strict_and_valid() -> None:
    validate_arm_nesting()  # must not raise


def test_arm_modes_a_is_all_off_and_matches_catalog() -> None:
    from app.jev.catalog import load_catalog

    modes = arm_modes("A")
    assert set(modes) == set(load_catalog().keys())
    assert all(mode == "off" for mode in modes.values())


def test_arm_modes_c_and_d_include_exactly_the_specified_keys() -> None:
    c_on = {key for key, mode in arm_modes("C").items() if mode == "on"}
    d_on = {key for key, mode in arm_modes("D").items() if mode == "on"}
    assert c_on == {
        "retrieval.support.v1",
        "context.keep_segment.v1",
        "intent.next_action.v1",
        "pedagogy.next_method.v1",
    }
    assert d_on == c_on | {"coverage.item_support.v1", "assessment.criterion_review.v1"}


def test_arm_modes_unknown_arm_raises() -> None:
    with pytest.raises(ValueError, match="Unknown ablation arm"):
        arm_modes("Z")


# ------------------------------------------------------------------ pure metrics


def test_recall_at_k_hand_computed() -> None:
    assert recall_at_k(["a", "b", "c"], ["b", "d"], 2) == 0.5
    assert recall_at_k(["a", "b", "c"], ["a", "b"], 2) == 1.0


def test_recall_at_k_edge_cases() -> None:
    assert recall_at_k([], ["a"], 3) == 0.0  # empty result list
    assert recall_at_k(["a", "b"], ["a", "b", "c"], 10) == pytest.approx(2 / 3)  # K > list
    assert recall_at_k(["a"], [], 1) == 1.0  # nothing to recall
    with pytest.raises(ValueError, match="k must be positive"):
        recall_at_k(["a"], ["a"], 0)


def test_mrr_hand_computed_and_ties() -> None:
    assert mrr(["a", "b", "c"], ["b", "d"]) == 0.5
    assert mrr(["a", "b"], ["c"]) == 0.0
    # Tie between two relevant ids resolves to the earlier position.
    assert mrr(["a", "b", "c"], ["b", "c"]) == 0.5
    assert mrr(["a"], []) == 0.0


def test_locator_accuracy_hand_computed() -> None:
    results = [
        LocatorResult("l1", "x", 0, ("x", "y")),  # hit
        LocatorResult("l2", "x", 1, ("y", "x")),  # hit
        LocatorResult("l3", "x", 0, ("y", "x")),  # miss at slot
        LocatorResult("l4", "x", 2, ("x", "y")),  # slot out of range
    ]
    assert locator_accuracy(results) == 0.5
    assert locator_accuracy([]) == 0.0


def test_citation_metrics_hand_computed() -> None:
    results = [
        CitationResult("c1", True, True),
        CitationResult("c2", False, False),
        CitationResult("c3", True, False),
        CitationResult("c4", True, None),
    ]
    assert citation_support_accuracy(results) == 0.5
    assert unsupported_claim_rate(results) == 0.75
    assert citation_support_accuracy([]) == 0.0
    assert unsupported_claim_rate([]) == 0.0


def test_mainline_recovery_rate_hand_computed() -> None:
    results = [
        TrajectoryResult("t1", "CONTINUE", "CONTINUE", True),
        TrajectoryResult("t2", "ANSWER_AND_RESUME", "OTHER", True),
        TrajectoryResult("t3", "CONTINUE", "CONTINUE", False),
    ]
    assert mainline_recovery_rate(results) == pytest.approx(1 / 3)
    assert mainline_recovery_rate([]) == 0.0


def test_coverage_confusion_hand_computed() -> None:
    results = [
        CoverageResult("o1", True, True),  # tp
        CoverageResult("o2", False, True),  # fp
        CoverageResult("o3", True, False),  # fn
        CoverageResult("o4", False, False),  # tn
        CoverageResult("o5", True, None),  # fn (withheld)
        CoverageResult("o6", False, None),  # tn (withheld)
    ]
    confusion = coverage_confusion(results)
    assert confusion["tp"] == 1
    assert confusion["fp"] == 1
    assert confusion["fn"] == 2
    assert confusion["tn"] == 2
    assert confusion["precision"] == 0.5
    assert confusion["recall"] == pytest.approx(1 / 3)


def test_criterion_error_hand_computed() -> None:
    results = [
        CriterionResult("a", "crit-1", 0, 0),  # 0
        CriterionResult("a", "crit-2", 1, 2),  # 1
        CriterionResult("b", "crit-1", 2, None),  # unresolved -> 1.0
        CriterionResult("c", "crit-1", 1, None),  # unresolved -> 1.0
    ]
    assert criterion_error(results) == 0.75
    assert criterion_error([]) == 0.0


def test_image_answer_accuracy_normalizes_and_counts_none_as_wrong() -> None:
    results = [
        ImageResult("i1", "42", "42"),
        ImageResult("i2", "Triangle", " triangle "),
        ImageResult("i3", "x", None),
        ImageResult("i4", "yes", "no"),
    ]
    assert image_answer_accuracy(results) == 0.5
    assert image_answer_accuracy([]) == 0.0


def test_latency_summary_percentiles_and_empty() -> None:
    assert latency_summary([10.0, 20.0, 30.0, 40.0, 100.0]) == {
        "p50": 30.0,
        "p95": 88.0,
    }
    assert latency_summary([]) == {"p50": None, "p95": None}


def test_cost_split_hand_computed() -> None:
    split = cost_split(
        deepseek_input_tokens=1_000,
        deepseek_output_tokens=500,
        jev_calls=10,
        embedding_tokens=2_000,
        deepseek_input_price_per_million=2.0,
        deepseek_output_price_per_million=8.0,
        jev_price_per_call=0.01,
        embedding_price_per_million=0.1,
    )
    assert split["deepseek"] == 0.006
    assert split["jev"] == 0.1
    assert split["embedding"] == 0.0002


def test_failure_rate_hand_computed() -> None:
    assert failure_rate(["ok", "ok", "timeout", "unavailable"]) == 0.5
    assert failure_rate(["ok", "cache_hit"]) == 0.0
    assert failure_rate([]) == 0.0


# ---------------------------------------------------------------------- loader


def test_example_file_loads_with_expected_shape() -> None:
    cases = load_ablation_cases(EXAMPLE)
    assert cases.dataset_status == DATASET_STATUS_EXAMPLE
    assert len(cases.retrieval) >= 2
    assert len(cases.locator) >= 2
    assert len(cases.citation) >= 2
    assert len(cases.trajectory) >= 2
    assert len(cases.coverage) >= 2
    assert len(cases.criterion) >= 2
    assert len(cases.image) >= 2


def test_loader_names_the_offending_entry(tmp_path: Path) -> None:
    payload = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    payload["cases"]["retrieval"][0]["relevant_ids"] = ["not-a-candidate"]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="retrieval case 'retrieval-01'"):
        load_ablation_cases(bad)


def test_loader_rejects_unknown_dataset_status(tmp_path: Path) -> None:
    payload = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    payload["dataset_status"] = "NOT_A_REAL_STATUS"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="dataset_status"):
        load_ablation_cases(bad)


# ---------------------------------------------------------------- full offline run


def _offline(arm: str, database) -> dict:
    cases = load_ablation_cases(EXAMPLE)
    return run_ablation(
        cases,
        arm,
        transport=FakeTransport(deterministic_fake_responder),
        receipt_store=SqlReceiptStore(database),
    )


@pytest.mark.parametrize("arm", ["A", "B", "C", "D"])
def test_full_offline_run_produces_metric_dict_for_each_arm(tmp_path: Path, arm: str) -> None:
    summary = _offline(arm, make_jev_database(tmp_path))
    assert summary["transport"] == "deterministic_fake"
    assert summary["interpretation"] == INTERPRETATION_PLUMBING
    assert set(summary["metrics"]) == METRIC_KEYS
    assert summary["modes"] == arm_modes(arm)


def test_offline_arm_a_makes_no_jev_calls(tmp_path: Path) -> None:
    summary = _offline("A", make_jev_database(tmp_path))
    assert summary["jev_calls"] == 0
    assert summary["metrics"]["failure_rate"] == 0.0


# -------------------------------------------------------------- honesty guardrails


def test_compare_arms_refuses_improvement_from_fake_runs(tmp_path: Path) -> None:
    runs = {
        arm: _offline(arm, make_jev_database(tmp_path)) for arm in ("A", "B")
    }
    verdict = compare_arms(runs)
    assert verdict["verdict"] == "NOT_INTERPRETABLE"
    with pytest.raises(ValueError, match="deterministic fake transport"):
        compare_arms(runs, request_quality=True)


def test_compare_arms_refuses_live_on_unlabelled_dataset() -> None:
    live_unlabelled = {
        "A": {"transport": "live", "dataset_status": DATASET_STATUS_EXAMPLE, "metrics": {}}
    }
    verdict = compare_arms(live_unlabelled)
    assert verdict["verdict"] == "NOT_INTERPRETABLE"
    with pytest.raises(ValueError, match="labelled dataset"):
        compare_arms(live_unlabelled, request_quality=True)


def test_compare_arms_labels_only_live_labelled_as_interpretable() -> None:
    live_labelled = {
        "A": {"transport": "live", "dataset_status": DATASET_STATUS_LABELLED, "metrics": {}},
        "B": {"transport": "live", "dataset_status": DATASET_STATUS_LABELLED, "metrics": {}},
    }
    verdict = compare_arms(live_labelled, request_quality=True)
    assert verdict["verdict"] == "INTERPRETABLE"
    assert "metrics_by_arm" in verdict


def test_compare_arms_requires_at_least_one_run() -> None:
    with pytest.raises(ValueError, match="at least one run"):
        compare_arms({})


# ------------------------------------------------------------------- no state writes


def test_no_learning_grade_or_coverage_rows_change(tmp_path: Path) -> None:
    database = make_jev_database(tmp_path)
    with database.connect() as connection:
        connection.executescript(
            """
            CREATE TABLE learning_journeys (id TEXT PRIMARY KEY, node_id TEXT, status TEXT);
            CREATE TABLE assessment_sessions (id TEXT PRIMARY KEY, raw_score REAL, status TEXT);
            CREATE TABLE learning_coverage (id TEXT PRIMARY KEY, journey_id TEXT, item_id TEXT);
            INSERT INTO learning_journeys VALUES('j1','n1','LEARNING');
            INSERT INTO assessment_sessions VALUES('s1',78.0,'GRADED');
            INSERT INTO learning_coverage VALUES('c1','j1','item-a');
            """
        )
    before = _state_counts(database)
    _offline("D", database)
    after = _state_counts(database)
    assert after == before
    # The only write is to the Jev receipt ledger.
    with database.connect() as connection:
        receipts = connection.execute(
            "SELECT COUNT(*) FROM jev_decision_receipts"
        ).fetchone()[0]
    assert receipts > 0


def _state_counts(database) -> dict[str, int]:
    with database.connect() as connection:
        journeys = connection.execute(
            "SELECT COUNT(*) FROM learning_journeys"
        ).fetchone()[0]
        sessions = connection.execute(
            "SELECT COUNT(*) FROM assessment_sessions"
        ).fetchone()[0]
        coverage = connection.execute(
            "SELECT COUNT(*) FROM learning_coverage"
        ).fetchone()[0]
        return {"journeys": journeys, "sessions": sessions, "coverage": coverage}


# ----------------------------------------------------------------- cost ceiling math


def test_cost_ceiling_math_for_a_live_run_is_pure() -> None:
    cases = AblationCaseSet(
        dataset_status=DATASET_STATUS_LABELLED,
        retrieval=(
            RetrievalCase(
                id="r1",
                query="explain eps",
                top_k=2,
                candidates=(
                    RetrievalCandidate(
                        "c1", "some evidence", "a.md", "page", "1", "s", "official", 1
                    ),
                    RetrievalCandidate(
                        "c2", "more evidence", "a.md", "page", "2", "s", "official", 2
                    ),
                ),
                relevant_ids=frozenset({"c1"}),
                graded_relevance={"c1": 4},
            ),
        ),
    )
    ceilings = estimate_input_token_ceilings(
        cases, "B", protocol_overhead_tokens=100
    )
    # Arm B arms retrieval.support.v1 -> one ceiling per candidate (2 candidates).
    assert len(ceilings) == 2
    assert ceilings[0] == len(b"") + len(b"explain eps\nsome evidence") + 100
    assert estimate_input_token_ceilings(cases, "A", protocol_overhead_tokens=100) == []

    ceiling = calculate_cost_ceiling(
        ceilings,
        max_output_tokens_per_case=256,
        input_price_per_million=2.0,
        output_price_per_million=8.0,
    )
    expected = (sum(ceilings) * 2.0 + 2 * 256 * 8.0) / 1_000_000
    assert ceiling == round(expected, 8)
