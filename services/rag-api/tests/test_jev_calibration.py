"""Trustworthiness tests for the Jev calibration mathematics (pure functions).

Covers hand-computed ECE and temperature-fitting values, the temperature-application
honesty rules (recorded-only + double-application refusal), the bucket key scheme, the
``confidence``-is-concentration semantics, and the 4-decimal precision limitation.
"""

from __future__ import annotations

import pytest

from app.evaluation.jev_calibration import (
    PRECISION_DECIMALS,
    DoubleTemperatureApplication,
    TemperatureArtifact,
    TemperatureBucket,
    TemperatureNotRecorded,
    apply_recorded_temperature,
    expected_calibration_error,
    fit_temperature,
    fit_temperatures_by_bucket,
    normalized_entropy_confidence,
    prob_of_correct,
    probs_to_logits,
    temperature_bucket,
    temperature_nll,
    temperature_scale_probs,
)

# ------------------------------------------------------------------ ECE


def test_ece_hand_computed() -> None:
    conf = [0.25, 0.75, 0.9]
    correct = [0, 1, 1]
    # bins=2 -> edges [0, 0.5, 1.0]
    # (0,0.5]: conf 0.25, correct 0 -> |0.25-0|=0.25, mass 1/3
    # (0.5,1.0]: conf 0.75+0.9 -> mean 0.825, correct 1.0 -> |0.825-1|=0.175, mass 2/3
    # ECE = 0.25/3 + 0.175*2/3 = 0.2
    assert expected_calibration_error(conf, correct, bins=2) == pytest.approx(0.2)


def test_ece_empty_and_mismatch() -> None:
    import math

    assert math.isnan(expected_calibration_error([], [], bins=15))
    with pytest.raises(ValueError, match="same length"):
        expected_calibration_error([0.5, 0.6], [1], bins=15)


def test_ece_requires_two_bins() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        expected_calibration_error([0.5], [1], bins=1)


# ------------------------------------------------------------------ temperature scaling


def test_temperature_scale_probs_hand_computed() -> None:
    # logits = [ln 0.9, ln 0.1]; /2; softmax -> [0.75, 0.25]
    scaled = temperature_scale_probs([0.9, 0.1], 2.0)
    assert scaled[0] == pytest.approx(0.75, abs=1e-4)
    assert scaled[1] == pytest.approx(0.25, abs=1e-4)


def test_temperature_scale_is_identity_at_one() -> None:
    scaled = temperature_scale_probs([0.6, 0.4], 1.0)
    assert scaled[0] == pytest.approx(0.6, abs=1e-4)
    assert scaled[1] == pytest.approx(0.4, abs=1e-4)


def test_temperature_scale_quantizes_to_precision() -> None:
    scaled = temperature_scale_probs([0.9, 0.1], 2.0, precision_decimals=4)
    assert scaled[0] == 0.75
    assert scaled[1] == 0.25


def test_probs_to_logits_and_prob_of_correct() -> None:
    logits = probs_to_logits([0.5, 0.5])
    assert logits[0] == pytest.approx(logits[1])
    assert prob_of_correct([0.1, 0.2, 0.7], 2) == pytest.approx(0.7)
    with pytest.raises(ValueError, match="out of range"):
        prob_of_correct([0.1, 0.9], 5)


# ------------------------------------------------------------------ temperature fitting


def test_fit_temperature_hand_computed() -> None:
    # Each row's correct logit is 1.0, the other 0.0; NLL(T) = log(1 + e^{-1/T}).
    # grid 0.5/1.0/2.0 -> NLL 0.1269/0.3133/0.4741, argmin = 0.5.
    logits = [[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]]
    labels = [0, 1, 0]
    assert fit_temperature(logits, labels, grid=[0.5, 1.0, 2.0]) == 0.5


def test_temperature_nll_matches_hand_value() -> None:
    nll = temperature_nll([[1.0, 0.0]], [0], 1.0)
    # softmax([1,0])[0] = e/(e+1); -log(e/(e+1)) = log(1 + 1/e) = log(1 + e^-1)
    import math

    assert nll == pytest.approx(math.log(1 + math.exp(-1)))


def test_fit_temperature_requires_rows_and_grid() -> None:
    with pytest.raises(ValueError, match="at least one row"):
        fit_temperature([], [], grid=[1.0])
    with pytest.raises(ValueError, match="non-empty"):
        fit_temperature([[1.0, 0.0]], [0], grid=[])


# ------------------------------------------------------------------ buckets


def test_temperature_bucket_key_scheme() -> None:
    assert temperature_bucket("choice", "zh", 4) == "choice:zh:3-5"
    assert temperature_bucket("noul", "en", 2) == "noul:en:2"
    assert temperature_bucket("score", "en", 10) == "score:en:6-10"
    assert temperature_bucket("score", "en", 11) == "score:en:11+"


def test_temperature_bucket_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError, match="choice/score/noul"):
        temperature_bucket("bogus", "en", 2)
    with pytest.raises(ValueError, match="at least 2"):
        temperature_bucket("noul", "en", 1)


# ------------------------------------------------------------------ confidence semantics


def test_confidence_is_distribution_concentration_not_correctness() -> None:
    # uniform over 2 options -> 0 concentration; degenerate -> 1.0.
    assert normalized_entropy_confidence([0.5, 0.5], 2) == pytest.approx(0.0)
    assert normalized_entropy_confidence([1.0, 0.0], 2) == pytest.approx(1.0)
    # k < 2 -> 1.0 by construction.
    assert normalized_entropy_confidence([1.0], 1) == 1.0


# ------------------------------------------------------------------ application honesty rules


def _artifact(temperature: float = 1.5) -> TemperatureArtifact:
    bucket = TemperatureBucket(
        key="choice:en:3-5",
        primitive="choice",
        language="en",
        option_count=4,
        temperature=temperature,
        n=10,
        ece_before=0.2,
        ece_after=0.1,
        fitted_on_split="calibration",
    )
    return TemperatureArtifact(
        version="1",
        dataset_content_hash="hash",
        split_ref="split.json",
        buckets={"choice:en:3-5": bucket},
        applied=frozenset(),
        ece_before=0.2,
        ece_after=0.1,
    )


def test_apply_recorded_temperature_works_and_marks_applied() -> None:
    artifact = _artifact(temperature=2.0)
    scaled, new_artifact = apply_recorded_temperature(
        artifact, "choice:en:3-5", [0.9, 0.1, 0.0, 0.0]
    )
    assert scaled[0] == pytest.approx(0.75, abs=1e-4)
    assert "choice:en:3-5" in new_artifact.applied
    assert "choice:en:3-5" not in artifact.applied  # original unchanged


def test_apply_unrecorded_temperature_is_refused() -> None:
    artifact = _artifact()
    with pytest.raises(TemperatureNotRecorded, match="No recorded temperature"):
        apply_recorded_temperature(artifact, "score:en:3-5", [0.5, 0.5])


def test_double_temperature_application_is_refused() -> None:
    artifact = _artifact(temperature=2.0)
    _, applied = apply_recorded_temperature(artifact, "choice:en:3-5", [0.9, 0.1, 0.0, 0.0])
    with pytest.raises(DoubleTemperatureApplication, match="second temperature"):
        apply_recorded_temperature(applied, "choice:en:3-5", [0.75, 0.25, 0.0, 0.0])


# ------------------------------------------------------------------ fit_temperatures_by_bucket


def test_fit_temperatures_by_bucket_records_nothing_as_applied() -> None:
    records = [
        {
            "primitive": "noul",
            "language": "en",
            "option_count": 2,
            "logits": [[0.5, -0.5], [0.2, -0.2], [0.6, -0.6]],
            "label_indices": [1, 0, 1],
        }
    ]
    artifact = fit_temperatures_by_bucket(
        records,
        fitted_on_split="calibration",
        dataset_content_hash="h",
        split_ref="split.json",
    )
    assert "noul:en:2" in artifact.buckets
    assert artifact.applied == frozenset()
    assert artifact.buckets["noul:en:2"].fitted_on_split == "calibration"


def test_fit_temperatures_refuses_non_calibration_split() -> None:
    with pytest.raises(ValueError, match="calibration split"):
        fit_temperatures_by_bucket(
            [], fitted_on_split="train", dataset_content_hash="h", split_ref="split.json"
        )


# ------------------------------------------------------------------ precision


def test_precision_limitation_is_recorded() -> None:
    assert PRECISION_DECIMALS == 4
    artifact = _artifact().to_dict()
    assert artifact["precision"]["decimals"] == 4
    assert "4 decimal" in artifact["precision"]["note"]
