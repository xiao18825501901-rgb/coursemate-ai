"""Trustworthiness tests for the A/B/C/D/E Jev ablation harness.

These prove (1) the arm nesting and the fake/live honesty guardrails, (2) the new
metric functions against hand-computed values, (3) the dataset's composition and
label-tier invariants, (4) the split-leakage protection (split by group, never by row),
and (5) that a full offline run produces the metric dict and is refused a verdict.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from app.evaluation.jev_semantic_ablation import (
    DATASET_STATUS_LABELLED,
    INTERPRETATION_PLUMBING,
    LABEL_TIER_DISPUTED,
    LABEL_TIER_SILVER,
    TRANSPORT_LIVE,
    ChoiceResult,
    FakeJevTransport,
    JevJudgment,
    KeyFactResult,
    ScoreLevelResult,
    arm_modes,
    assign_split,
    build_split_manifest,
    choice_accuracy,
    compare_jev_arms,
    context_compaction,
    deterministic_fake_jev_predictor,
    key_fact_retention,
    load_jev_dataset,
    ndcg,
    run_jev_semantic_ablation,
    score_level_mae,
    validate_arm_nesting,
    validate_jev_dataset,
    validate_split_leakage,
)

ROOT = Path(__file__).parents[3]
DATASET = ROOT / "benchmarks" / "jev-judgments.dataset.json"
SPLIT = ROOT / "benchmarks" / "jev-calibration.split.json"

EXPECTED_DEFINITIONS = {
    "intent.next_action.v1",
    "retrieval.support.v1",
    "source.supports_claim.v1",
    "source.select_span.v1",
    "context.keep_segment.v1",
    "pedagogy.next_method.v1",
    "coverage.item_support.v1",
    "assessment.criterion_review.v1",
    "template.match.v1",
    "exercise.prototype.v1",
    "graph.prerequisite.v1",
    "corpus.quality.v1",
}


# ------------------------------------------------------------------ arm nesting


def test_arm_nesting_is_strict() -> None:
    validate_arm_nesting()  # must not raise


def test_arm_modes_a_is_all_off_and_e_covers_the_armed_keys() -> None:
    a_on = {k for k, m in arm_modes("A").items() if m == "on"}
    e_on = {k for k, m in arm_modes("E").items() if m == "on"}
    assert a_on == set()
    assert e_on == {
        "retrieval.support.v1",
        "context.keep_segment.v1",
        "intent.next_action.v1",
        "pedagogy.next_method.v1",
        "coverage.item_support.v1",
        "assessment.criterion_review.v1",
        "source.supports_claim.v1",
        "source.select_span.v1",
    }


def test_arm_modes_unknown_arm_raises() -> None:
    with pytest.raises(ValueError, match="Unknown ablation arm"):
        arm_modes("Z")


# ------------------------------------------------------------------ new metrics


def test_ndcg_hand_computed() -> None:
    graded = {"a": 4, "b": 3, "c": 0}
    # NDCG@1: the top returned doc is the highest graded -> exactly 1.0.
    assert ndcg(["a", "b", "c"], graded, 1) == pytest.approx(1.0)
    # Ideal order a(4), b(3): NDCG@2 is exactly 1.0.
    assert ndcg(["a", "b"], graded, 2) == pytest.approx(1.0)
    # Suboptimal order b(3), a(4):
    #   DCG@2 = 7/log2(2) + 15/log2(3);  IDCG@2 = 15/log2(2) + 7/log2(3)
    dcg = 7 / math.log2(2) + 15 / math.log2(3)
    idcg = 15 / math.log2(2) + 7 / math.log2(3)
    assert ndcg(["b", "a"], graded, 2) == pytest.approx(dcg / idcg)
    assert 0.0 <= ndcg(["b", "a"], graded, 2) <= 1.0


def test_ndcg_empty_relevance_is_zero() -> None:
    assert ndcg(["a", "b"], {}, 2) == 0.0
    with pytest.raises(ValueError, match="positive"):
        ndcg(["a"], {"a": 4}, 0)


def test_choice_accuracy_counts_none_as_wrong() -> None:
    results = [
        ChoiceResult("c1", "A", "A"),
        ChoiceResult("c2", "B", "C"),
        ChoiceResult("c3", "A", None),
    ]
    assert choice_accuracy(results) == pytest.approx(1 / 3)
    assert choice_accuracy([]) == 0.0


def test_score_level_mae_counts_none_as_full_error() -> None:
    results = [
        ScoreLevelResult("s1", 2, 2, 3),
        ScoreLevelResult("s2", 0, 3, 3),
        ScoreLevelResult("s3", 1, None, 3),
    ]
    # errors: 0, 3, 3 -> mean 2.0
    assert score_level_mae(results) == pytest.approx(2.0)
    assert score_level_mae([]) == 0.0


def test_key_fact_retention_and_compaction() -> None:
    results = [
        KeyFactResult("k1", "seg1", True, True),
        KeyFactResult("k1", "seg2", True, False),
        KeyFactResult("k2", "seg3", False, False),
        KeyFactResult("k2", "seg4", False, True),
    ]
    assert key_fact_retention(results) == pytest.approx(0.5)
    assert context_compaction(results) == pytest.approx(0.5)


# ------------------------------------------------------------------ dataset


def test_dataset_loads_with_all_definitions_and_tiers() -> None:
    payload = load_jev_dataset(DATASET)
    samples = payload["samples"]
    assert len(samples) >= 300
    definitions = {s["definition_id"] for s in samples}
    assert definitions >= EXPECTED_DEFINITIONS
    tiers = {s["label_tier"] for s in samples}
    assert tiers == {"OBJECTIVE_VERIFIED", "SOURCE_REVIEWED", "SILVER_DEEPSEEK", "DISPUTED"}
    languages = {s["language"] for s in samples}
    assert {"en", "zh"} <= languages
    for sample in samples:
        assert sample["sample_id"].startswith("jev-")
        assert sample["label_tier"] in tiers
        assert sample["option_count"] >= 2


def test_label_tier_invariants_are_enforced() -> None:
    payload = load_jev_dataset(DATASET)
    # A SILVER sample whose evidence no longer says "unreviewed" must fail validation.
    bad = json.loads(json.dumps(payload))
    for sample in bad["samples"]:
        if sample["label_tier"] == LABEL_TIER_SILVER:
            sample["label_evidence"] = "just a plain label"
            break
    with pytest.raises(ValueError, match="unreviewed|DeepSeek suggestion"):
        validate_jev_dataset(bad)


def test_disputed_evidence_records_both_readings() -> None:
    payload = load_jev_dataset(DATASET)
    disputed = [s for s in payload["samples"] if s["label_tier"] == LABEL_TIER_DISPUTED]
    assert disputed, "dataset must contain at least one DISPUTED sample"
    for sample in disputed:
        evidence = sample["label_evidence"].lower()
        assert "reading a" in evidence and "reading b" in evidence


# ------------------------------------------------------------------ split leakage


def _manifest_samples(payload):
    return [
        JevJudgment(
            sample_id=s["sample_id"], definition_id=s["definition_id"],
            definition_version=s["definition_version"], language=s["language"],
            option_count=s["option_count"], document_id=s["document_id"],
            node_id=s["node_id"], question_family=s["question_family"],
            label_tier=s["label_tier"], label_evidence=s["label_evidence"],
            state=s["state"], questions=s["questions"], label=s["label"], split="",
        )
        for s in payload["samples"]
    ]


def test_split_leakage_validation_passes_on_frozen_manifest() -> None:
    payload = load_jev_dataset(DATASET)
    manifest = json.loads(SPLIT.read_text(encoding="utf-8"))
    validate_split_leakage(_manifest_samples(payload), manifest)  # must not raise


def test_split_leakage_rejects_a_group_split_across_splits() -> None:
    payload = load_jev_dataset(DATASET)
    manifest = json.loads(SPLIT.read_text(encoding="utf-8"))
    # Pick one group's sample_ids and move one of them to another split: leakage.
    group_ids = next(iter(manifest["group_keys"].values()))
    victim = group_ids[0]
    target = next(
        name
        for name in ("train", "calibration", "test")
        if victim not in manifest["splits"][name]["sample_ids"]
    )
    manifest["splits"][target]["sample_ids"].append(victim)
    with pytest.raises(ValueError, match="more than one split"):
        validate_split_leakage(_manifest_samples(payload), manifest)


def test_same_group_gets_the_same_split_and_manifest_matches() -> None:
    payload = load_jev_dataset(DATASET)
    samples = _manifest_samples(payload)
    manifest = build_split_manifest(samples)
    assert manifest["content_hash"] == json.loads(SPLIT.read_text(encoding="utf-8"))["content_hash"]
    # The same (document, node, family) group is atomic: identical split for all members.
    by_group: dict[tuple, set] = {}
    for sample in samples:
        split = assign_split(sample.group_key)
        by_group.setdefault(sample.group_key, set()).add(split)
    assert all(len(splits) == 1 for splits in by_group.values())


def test_split_manifest_is_group_keyed_never_row() -> None:
    manifest = json.loads(SPLIT.read_text(encoding="utf-8"))
    assert manifest["grouping"] == ["document_id", "node_id", "question_family"]
    for name in ("train", "calibration", "test"):
        assert manifest["splits"][name]["count"] > 0


# ------------------------------------------------------------------ offline run honesty


def _offline(arm: str) -> dict:
    dataset = load_jev_dataset(DATASET)
    return run_jev_semantic_ablation(
        dataset,
        arm,
        transport=FakeJevTransport(),
        jev_predictor=deterministic_fake_jev_predictor,
    )


@pytest.mark.parametrize("arm", ["A", "B", "C", "D", "E"])
def test_offline_run_is_plumbing_only_for_every_arm(arm: str) -> None:
    summary = _offline(arm)
    assert summary["transport"] == "deterministic_fake"
    assert summary["interpretation"] == INTERPRETATION_PLUMBING
    assert summary["interpretation"] != "INTERPRETABLE"
    assert set(summary["metrics"]) >= {
        "recall_at_k", "mrr", "ndcg_at_k", "locator_accuracy",
        "citation_support_accuracy", "unsupported_claim_rate", "key_fact_retention",
        "intent_accuracy", "coverage_confusion", "criterion_error",
        "mainline_recovery_rate", "image_answer_accuracy",
    }


def test_offline_run_has_placeholder_baselines() -> None:
    summary = _offline("A")
    assert summary["placeholder_baselines"], "arm A offline must name placeholder baselines"


def test_compare_refuses_improvement_from_fake_runs() -> None:
    runs = {arm: _offline(arm) for arm in ("A", "E")}
    verdict = compare_jev_arms(runs)
    assert verdict["verdict"] == "NOT_INTERPRETABLE"
    with pytest.raises(ValueError, match="deterministic fake transport"):
        compare_jev_arms(runs, request_quality=True)


def test_compare_labels_live_labelled_no_placeholders_as_interpretable() -> None:
    live = {
        arm: {
            "transport": TRANSPORT_LIVE,
            "dataset_status": DATASET_STATUS_LABELLED,
            "placeholder_baselines": [],
            "metrics": {},
            "deepseek_calls": 10 if arm == "A" else 5,
        }
        for arm in ("A", "E")
    }
    verdict = compare_jev_arms(live, request_quality=True)
    assert verdict["verdict"] == "INTERPRETABLE"
    assert verdict["deepseek_call_delta_vs_A"]["E"] == -5


def test_fake_predictor_is_non_informative_and_deterministic() -> None:
    dataset = load_jev_dataset(DATASET)
    sample = _manifest_samples(dataset)[0]
    first = deterministic_fake_jev_predictor(sample)
    second = deterministic_fake_jev_predictor(sample)
    assert first == second
