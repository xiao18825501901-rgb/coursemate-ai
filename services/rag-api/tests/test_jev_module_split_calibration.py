"""The companion dataset's split manifest, and calibration being able to consume it.

Round 31 added a companion dataset for the seven definitions the frozen set never covered.
It had no split manifest, which made it unreachable for the calibrator — whose contract is
"fit only on the held-out calibration split, refuse when there is none". This file pins the
manifest, the honest reporting of what a small dataset can and cannot support, and the fact
that the calibration path now runs over it end to end.

**Every prediction used here is synthetic** (uniform/hand-built probabilities written by the
test). Calibration *maths* is deterministic, so this proves the plumbing works; it is not a
statement about any model, and the artifact it produces is a test fixture, never a
committed calibration result.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]
COMPANION = ROOT / "benchmarks" / "jev-module-judgments.dataset.json"
COMPANION_SPLIT = ROOT / "benchmarks" / "jev-module-judgments.split.json"
FROZEN_SPLIT = ROOT / "benchmarks" / "jev-calibration.split.json"

sys.path.insert(0, str(ROOT / "scripts"))

import calibrate_jev  # noqa: E402

from app.evaluation.jev_semantic_ablation import (  # noqa: E402
    SPLIT_NAMES,
    assign_split,
    build_split_manifest,
    content_hash,
    judgments_from_dataset,
    load_jev_dataset,
    split_coverage,
    unevaluated_definitions,
    unfittable_definitions,
    validate_split_leakage,
)


def companion_samples():
    return judgments_from_dataset(load_jev_dataset(COMPANION))


# ----------------------------------------------------------------------- the manifest


def test_companion_manifest_pins_the_dataset_and_has_no_leakage() -> None:
    samples = companion_samples()
    manifest = json.loads(COMPANION_SPLIT.read_text(encoding="utf-8"))

    validate_split_leakage(samples, manifest)
    assert manifest["content_hash"] == content_hash(samples)
    assert manifest["grouping"] == ["document_id", "node_id", "question_family"]

    assigned = [
        sample_id
        for name in SPLIT_NAMES
        for sample_id in manifest["splits"][name]["sample_ids"]
    ]
    assert sorted(assigned) == sorted(sample.sample_id for sample in samples)
    assert len(assigned) == len(set(assigned)), "a sample may not be in two splits"


def test_companion_manifest_is_reproducible_not_hand_edited() -> None:
    """Rebuilding from the dataset must reproduce the committed file byte for byte."""

    rebuilt = build_split_manifest(companion_samples())
    committed = json.loads(COMPANION_SPLIT.read_text(encoding="utf-8"))
    assert rebuilt == committed


def synthetic_sample(sample_id: str, definition_id: str, group_key: tuple[str, str, str]):
    """One synthetic judgement in a chosen group, for tests about the split arithmetic."""
    from app.evaluation.jev_semantic_ablation import JevJudgment

    return JevJudgment(
        sample_id=sample_id,
        definition_id=definition_id,
        definition_version="1.0.0-design",
        language="en",
        option_count=2,
        document_id=group_key[0],
        node_id=group_key[1],
        question_family=group_key[2],
        label_tier="OBJECTIVE_VERIFIED",
        label_evidence="code-verified: synthetic fixture for the split arithmetic.",
        state={},
        questions={"q": {"type": "choice", "criteria": {"a": "a", "b": "b"}}},
        label={"q": {"choice": "a"}},
        split="",
    )


def test_assign_split_is_group_atomic_and_does_not_promise_per_definition_coverage() -> None:
    samples = companion_samples()

    by_group: dict[tuple[str, str, str], set[str]] = {}
    for sample in samples:
        by_group.setdefault(sample.group_key, set()).add(assign_split(sample.group_key))
    assert all(len(splits) == 1 for splits in by_group.values())

    # The point of the test: the hash does NOT guarantee that every definition reaches
    # every split. Round 95 gave the real companion dataset a calibration group for
    # `entity.relation.v1` (it had none, so no threshold could be fitted for it — see the
    # execution state), so the property is now demonstrated on a synthetic group instead of
    # on a gap that no longer exists. The behaviour under test is unchanged.
    group = next(
        key
        for key in (
            ("doc-synthetic", f"node-synthetic-{index}", "retrieval") for index in range(50)
        )
        if assign_split(key) != "calibration"
    )
    synthetic = [synthetic_sample("syn-0001", "retrieval.support.v1", group)]
    assert unfittable_definitions(synthetic) == ("retrieval.support.v1",)
    # And the real dataset now has no such definition at all.
    assert unfittable_definitions(samples) == ()


def test_coverage_reports_zeros_instead_of_hiding_definitions() -> None:
    coverage = split_coverage(companion_samples())

    assert len(coverage) == 7
    for definition_id, per_split in coverage.items():
        # Every split key is present for every definition, zero included: a missing key
        # would be indistinguishable from "not measured".
        assert set(per_split) == set(SPLIT_NAMES), definition_id

    # Round 95 closed both real gaps (entity had no calibration group, extraction had no
    # test group), so the zeros are now demonstrated where they are still reachable: on a
    # synthetic definition whose only group is not in the calibration split.
    group = next(
        key
        for key in (
            ("doc-synthetic", f"node-zero-{index}", "retrieval") for index in range(50)
        )
        if assign_split(key) != "calibration"
    )
    synthetic = [synthetic_sample("syn-0002", "retrieval.support.v1", group)]
    synthetic_coverage = split_coverage(synthetic)
    assert synthetic_coverage["retrieval.support.v1"]["calibration"] == 0
    assert set(synthetic_coverage["retrieval.support.v1"]) == set(SPLIT_NAMES)
    assert unfittable_definitions(synthetic) == ("retrieval.support.v1",)

    assert coverage["entity.relation.v1"]["calibration"] >= 1
    assert coverage["extraction.field_grounded.v1"]["test"] >= 1
    assert unevaluated_definitions(companion_samples()) == ()


def test_the_frozen_split_manifest_matches_the_dataset_it_pins() -> None:
    """The primary manifest is self-consistent, and its history is recorded.

    This used to assert the literal hash `2af0f40d…` and 47 calibration samples. Round 95
    added content so that `retrieval.support.v1` — the task's first promotion candidate —
    has a calibration population at all (it had 0, so nothing could be fitted for it), which
    changes the hash by construction. Recomputing the hash from the dataset is the stronger
    check the literal could only approximate: it cannot pass after a hand edit either.
    """
    frozen = ROOT / "benchmarks" / "jev-judgments.dataset.json"
    samples = judgments_from_dataset(load_jev_dataset(frozen))
    stuck = json.loads(FROZEN_SPLIT.read_text(encoding="utf-8"))

    assert stuck["content_hash"] == content_hash(samples)
    assert stuck["splits"]["calibration"]["count"] == 58
    assert len(samples) == 345
    # The history, kept rather than overwritten: the 310-sample set this manifest pinned
    # until round 95 hashed to 2af0f40d…, and every live ablation result recorded against
    # that hash refers to it.
    assert stuck["content_hash"] != (
        "2af0f40d1d1e89c6f7a8092cb846258f2b36b208c58f0211932344a32d33c10d"
    )


# -------------------------------------------------------------------- calibration path


def synthetic_predictions(samples, *, path: Path) -> Path:
    """Write a predictions file for exactly the calibration split, with flat probabilities.

    Flat probabilities are deliberate: the fitted temperature then has nothing to sharpen,
    so the test asserts the *plumbing* (rows joined, artifact pinned, ECE computed) rather
    than pretending to measure a model.
    """

    manifest = json.loads(COMPANION_SPLIT.read_text(encoding="utf-8"))
    calibration_ids = set(manifest["splits"]["calibration"]["sample_ids"])
    by_id = {sample.sample_id: sample for sample in samples}
    rows = []
    for sample_id in sorted(calibration_ids):
        sample = by_id[sample_id]
        primitive = "score" if "score_index" in sample.label["q"] else "choice"
        width = sample.option_count
        row = {
            "sample_id": sample_id,
            "probabilities": [1.0 / width] * width,
            "language": sample.language,
            "option_count": width,
        }
        if primitive == "choice":
            # Choice labels are candidate ids, so the file must state the index.
            row["label_index"] = 0
        rows.append(row)
    path.write_text(json.dumps({"predictions": rows}), encoding="utf-8")
    return path


def test_calibration_runs_over_the_companion_dataset(tmp_path: Path) -> None:
    samples = companion_samples()
    predictions = synthetic_predictions(samples, path=tmp_path / "predictions.json")
    out = tmp_path / "calibration.json"

    payload = calibrate_jev.fit_and_write(
        predictions, out, dataset_path=COMPANION, split_path=COMPANION_SPLIT
    )

    manifest = json.loads(COMPANION_SPLIT.read_text(encoding="utf-8"))
    assert out.is_file()
    # The calibration population is read from the manifest rather than hard-coded: round 95
    # added three calibration groups here (entity) so the fit has something to fit, and a
    # literal would have hidden that from a reader of this test.
    assert (
        payload["n_calibration"]
        == manifest["splits"]["calibration"]["count"]
        == 13
    )
    assert payload["artifact_version"]
    assert payload["applied"] == [], "a freshly fitted artifact has baked nothing in yet"
    # Provenance names the files actually used, not the frozen pair (a defect the
    # --dataset/--split flags exposed: the artifact claimed a split it never saw).
    assert payload["dataset_content_hash"] == manifest["content_hash"]
    assert payload["split_ref"] == COMPANION_SPLIT.name
    assert payload["dataset_path"] == str(COMPANION)
    # A synthetic flat distribution still has to produce finite numbers, not NaN.
    assert payload["ece_before"] is not None
    assert math.isfinite(float(payload["ece_before"]))
    # The artifact must say where its model evidence came from, and pin it: this file
    # is what a promotion decision would lean on, and before round 41 a synthetic
    # predictions file produced an artifact that read exactly like a fitted result.
    assert payload["predictions_sha256"] == hashlib.sha256(predictions.read_bytes()).hexdigest()
    assert payload["predictions_provenance"] == calibrate_jev.PREDICTIONS_PROVENANCE_UNSTATED


def test_calibration_records_a_stated_predictions_provenance(tmp_path: Path) -> None:
    """A named source is recorded verbatim, so an artifact can be traced to its run."""
    samples = companion_samples()
    predictions = synthetic_predictions(samples, path=tmp_path / "predictions.json")
    out = tmp_path / "calibration.json"

    payload = calibrate_jev.fit_and_write(
        predictions,
        out,
        dataset_path=COMPANION,
        split_path=COMPANION_SPLIT,
        predictions_provenance="unit-test fixture",
    )

    assert payload["predictions_provenance"] == "unit-test fixture"


def test_calibration_refuses_an_empty_calibration_split(tmp_path: Path) -> None:
    """The refusal is the contract: no held-out rows, no artifact.

    The manifest still assigns every sample (the leakage validator requires that), so the
    calibration rows are folded into train rather than dropped — the dataset is intact and
    only the held-out split is missing, which is exactly the case the guard exists for.
    """

    samples = companion_samples()
    manifest = json.loads(COMPANION_SPLIT.read_text(encoding="utf-8"))
    emptied = json.loads(json.dumps(manifest))
    folded = sorted(
        manifest["splits"]["train"]["sample_ids"]
        + manifest["splits"]["calibration"]["sample_ids"]
    )
    emptied["splits"]["train"] = {"count": len(folded), "sample_ids": folded}
    emptied["splits"]["calibration"] = {"count": 0, "sample_ids": []}
    split_path = tmp_path / "empty-calibration.split.json"
    split_path.write_text(json.dumps(emptied), encoding="utf-8")
    # The construction is honest: every sample is still assigned to exactly one split.
    validate_split_leakage(samples, emptied)

    predictions = synthetic_predictions(samples, path=tmp_path / "predictions.json")
    with pytest.raises(SystemExit, match="no held-out calibration split"):
        calibrate_jev.fit_and_write(
            predictions, tmp_path / "out.json", dataset_path=COMPANION, split_path=split_path
        )
    assert not (tmp_path / "out.json").exists()


def test_calibration_refuses_a_missing_calibration_prediction(tmp_path: Path) -> None:
    samples = companion_samples()
    predictions = synthetic_predictions(samples, path=tmp_path / "predictions.json")
    payload = json.loads(predictions.read_text(encoding="utf-8"))
    payload["predictions"] = payload["predictions"][:-1]
    predictions.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SystemExit, match="has no entry in the predictions file"):
        calibrate_jev.fit_and_write(
            predictions,
            tmp_path / "out.json",
            dataset_path=COMPANION,
            split_path=COMPANION_SPLIT,
        )
