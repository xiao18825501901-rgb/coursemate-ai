"""Calibration mathematics for the Jev multilingual decision model (pure, no I/O).

This module is the measurement layer for the honesty rules in the Jev workstream:

* ``confidence`` is **distribution concentration** (``1 - normalized entropy``), never
  a probability of being correct. Nothing here maps it to ``p_correct`` and nothing
  treats it as an accuracy or a grade. :func:`normalized_entropy_confidence` exists
  only so the semantics can be asserted and documented, not consumed as a correctness
  signal.
* Jev's official service rounds probabilities to 4 decimals (see
  ``work/jev-recon/rl_agent_api.py``). Calibration must therefore run on the
  highest-precision values available; any 4-decimal value carries the stated
  precision limitation (``PRECISION_DECIMALS`` / ``PRECISION_LIMITATION_NOTE``).
* A fitted temperature is only applied when it is recorded (per
  primitive/language/option-count bucket), and applying a second temperature to an
  already temperature-scaled value is refused (:class:`DoubleTemperatureApplication`).

Nothing in this module performs I/O: it does not read or write files, does not
import the model, and does not call the network. Artifacts are plain dataclasses.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# ----------------------------------------------------------------------------- precision

# The official Jev service rounds every reported probability to this many decimals
# (``rl_agent_api.py``: ``round(float(v), 4)``). Calibration therefore sees at most
# this precision through the service boundary.
PRECISION_DECIMALS = 4

PRECISION_LIMITATION_NOTE = (
    "The Jev SDK reports probabilities rounded to 4 decimal places at the service boundary. "
    "All ECE/temperature figures computed from service probabilities are therefore "
    "bounded by that quantization; they are not exact logit-space values. Prefer "
    "un-rounded logits/probabilities from the model when a higher-precision source "
    "is available."
)

# Cardinality bands matching the official ``temp_bucket`` (``work/jev-recon/rl_common.py``):
# a 2-option noul and a 20-option choice need different temperature scaling.
_SIZE_BANDS: tuple[tuple[int, int | None, str], ...] = (
    (2, 2, "2"),
    (3, 5, "3-5"),
    (6, 10, "6-10"),
    (11, None, "11+"),
)


def _size_band(option_count: int) -> str:
    if option_count < 2:
        raise ValueError("option_count must be at least 2 for a Jev question.")
    for _lo, hi, label in _SIZE_BANDS:
        if hi is None or option_count <= hi:
            return label
    return "11+"  # unreachable, kept for type clarity


def temperature_bucket(primitive: str, language: str, option_count: int) -> str:
    """Canonical temperature bucket key: ``"{primitive}:{language}:{size}"``.

    ``primitive`` is one of ``choice`` / ``score`` / ``noul`` (lower-cased), ``language``
    is the ISO code used by the dataset (``en`` / ``zh``), and ``size`` is the option
    cardinality band. This is the key a fitted temperature is recorded under and later
    looked up by: a fitted temperature is only applied when its bucket is recorded.
    """
    primitive_norm = str(primitive).strip().lower()
    if primitive_norm not in {"choice", "score", "noul"}:
        raise ValueError(f"Unknown primitive {primitive!r}; expected choice/score/noul.")
    language_norm = str(language).strip().lower()
    if not language_norm:
        raise ValueError("language must be a non-empty string.")
    return f"{primitive_norm}:{language_norm}:{_size_band(int(option_count))}"


# ----------------------------------------------------------------------------- confidence

# ``confidence`` is 1 - normalized entropy (distribution concentration). It is NOT a
# probability of correctness and must never be treated as one. Exposed and tested only
# to pin the semantics, mirroring ``rl_common.confidence_from_probs``.
def normalized_entropy_confidence(probs: Sequence[float], option_count: int) -> float:
    """Return ``1 - H(p)/log(k)`` (concentration, not correctness probability)."""
    k = int(option_count)
    if k < 2:
        return 1.0
    probs = [float(p) for p in probs[:k]]
    entropy = -sum(p * math.log(p) for p in probs if p > 0)
    return float(1.0 - entropy / math.log(k))


# ----------------------------------------------------------------------------- probabilities


def quantize_probability(value: float, decimals: int = PRECISION_DECIMALS) -> float:
    """Round a probability to the service's reported precision (documents the limitation)."""
    return round(float(value), int(decimals))


def probs_to_logits(probs: Sequence[float]) -> list[float]:
    """Map probabilities back to (unnormalized) logits via ``log(p)``.

    This is an *approximation* when the probabilities were already rounded by the
    service: the rounding is a lossy projection that cannot recover the exact logits.
    """
    return [math.log(max(float(p), 1e-12)) for p in probs]


def softmax_logits_temperature(logits: Sequence[float], temperature: float) -> list[float]:
    """Apply a single scalar temperature to logits and renormalize with a softmax."""
    t = float(temperature)
    if t <= 0:
        raise ValueError("temperature must be positive.")
    z = [float(value) / t for value in logits]
    z_max = max(z)
    exp = [math.exp(v - z_max) for v in z]
    total = sum(exp)
    return [e / total for e in exp]


def temperature_scale_probs(
    probs: Sequence[float], temperature: float, *, precision_decimals: int | None = None
) -> list[float]:
    """Rescale a reported probability vector by a temperature (probability-space form).

    Probabilities are mapped to logits, divided by ``temperature``, and renormalized.
    When ``precision_decimals`` is given the result is quantized to that many decimals,
    which is the precision the service would report (and the documented limitation).
    """
    scaled = softmax_logits_temperature(probs_to_logits(probs), temperature)
    if precision_decimals is not None:
        scaled = [quantize_probability(v, precision_decimals) for v in scaled]
    return scaled


def prob_of_correct(probs: Sequence[float], label_index: int) -> float:
    """Probability the model assigned to the labelled class (``probs[label_index]``)."""
    probs = [float(p) for p in probs]
    index = int(label_index)
    if not 0 <= index < len(probs):
        raise ValueError(f"label_index {index} out of range for {len(probs)} options.")
    return probs[index]


# ----------------------------------------------------------------------------- ECE


def expected_calibration_error(
    conf: Sequence[float], correct: Sequence[int], bins: int = 15
) -> float:
    """Expected calibration error (weighted by bin mass), matching ``rl_common.ece_score``.

    ``conf`` is the model's probability for the predicted (correct-or-not) class and
    ``correct`` is 1/0 whether the prediction was correct. Both come from LABELS, never
    from a model self-score. Empty input returns ``nan``. Bins are equal-width over
    ``[0, 1]``; a value falls in ``(lo, hi]`` so the top edge is inclusive and 0.0 is
    only counted in the first bin when the first edge is 0.
    """
    if bins < 2:
        raise ValueError("bins must be at least 2.")
    if len(conf) == 0:
        return float("nan")
    if len(conf) != len(correct):
        raise ValueError("conf and correct must have the same length.")
    edges = [i / bins for i in range(bins + 1)]
    ece = 0.0
    n = len(conf)
    for lo, hi in zip(edges[:-1], edges[1:], strict=False):
        selected = [
            (float(c), float(y))
            for c, y in zip(conf, correct, strict=False)
            if lo < float(c) <= hi
        ]
        if not selected:
            continue
        mass = len(selected) / n
        mean_conf = sum(c for c, _ in selected) / len(selected)
        mean_correct = sum(y for _, y in selected) / len(selected)
        ece += mass * abs(mean_conf - mean_correct)
    return float(ece)


def ece_from_predictions(
    probabilities: Sequence[Sequence[float]],
    label_indices: Sequence[int],
    *,
    bins: int = 15,
    temperature: float | None = None,
) -> float:
    """ECE over full probability vectors: score the labelled class, optionally rescale.

    ``temperature`` (when given) is applied to each probability vector before scoring,
    so ``ece_before`` and ``ece_after`` share one code path.
    """
    if len(probabilities) != len(label_indices):
        raise ValueError("probabilities and label_indices must have the same length.")
    conf: list[float] = []
    correct: list[int] = []
    for probs, label in zip(probabilities, label_indices, strict=False):
        scaled = temperature_scale_probs(probs, temperature) if temperature else list(probs)
        predicted = max(range(len(scaled)), key=lambda i: scaled[i])
        conf.append(prob_of_correct(scaled, label))
        correct.append(1 if predicted == label else 0)
    return expected_calibration_error(conf, correct, bins=bins)


# ----------------------------------------------------------------------------- fitting


# Deterministic log-spaced search grid (per README, temperatures are fitted per bucket
# on held-out data; the grid bounds mirror the plausible over/under-confidence range).
DEFAULT_TEMPERATURE_GRID: tuple[float, ...] = tuple(
    round(0.5 * (2.0 ** (i / 8)), 6) for i in range(17)
)  # 0.5 .. 2.0 in 16 log-steps


def temperature_nll(
    logits: Sequence[Sequence[float]], labels: Sequence[int], temperature: float
) -> float:
    """Mean negative log-likelihood of the labels under temperature-scaled logits."""
    if len(logits) != len(labels):
        raise ValueError("logits and labels must have the same length.")
    if float(temperature) <= 0:
        raise ValueError("temperature must be positive.")
    total = 0.0
    for row, label in zip(logits, labels, strict=False):
        probs = softmax_logits_temperature(row, temperature)
        total += -math.log(max(probs[int(label)], 1e-12))
    return total / len(logits) if logits else float("nan")


def fit_temperature(
    logits: Sequence[Sequence[float]],
    labels: Sequence[int],
    *,
    grid: Sequence[float] = DEFAULT_TEMPERATURE_GRID,
) -> float:
    """Fit a single scalar temperature minimizing mean NLL over ``grid``.

    Deterministic (no randomness, no data shuffling): the returned value is the grid
    point with the lowest mean NLL, ties resolving to the *smallest* temperature (the
    more conservative sharpening). ``labels`` are the correct class indices.
    """
    if not logits:
        raise ValueError("fit_temperature requires at least one row of logits.")
    if not grid:
        raise ValueError("grid must be non-empty.")
    best_t = None
    best_nll = None
    for t in grid:
        nll = temperature_nll(logits, labels, float(t))
        if best_nll is None or nll < best_nll - 1e-12 or (
            abs(nll - best_nll) <= 1e-12 and best_t is not None and float(t) < best_t
        ):
            best_t = float(t)
            best_nll = nll
    return float(best_t)


# ----------------------------------------------------------------------------- buckets


@dataclass(frozen=True)
class TemperatureBucket:
    """One recorded temperature for one (primitive, language, option-count) bucket."""

    key: str
    primitive: str
    language: str
    option_count: int
    temperature: float
    n: int
    ece_before: float
    ece_after: float
    fitted_on_split: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "primitive": self.primitive,
            "language": self.language,
            "option_count": self.option_count,
            "temperature": self.temperature,
            "n": self.n,
            "ece_before": self.ece_before,
            "ece_after": self.ece_after,
            "fitted_on_split": self.fitted_on_split,
        }


@dataclass(frozen=True)
class TemperatureArtifact:
    """An immutable calibration artifact: recorded temperatures + which were applied.

    ``applied`` tracks bucket keys whose temperature has already been baked in, so a
    second application to an already-scaled value is refused rather than silently
    double-scaled. ``dataset_content_hash`` and ``split_ref`` pin the artifact to the
    exact data it was fitted on.
    """

    version: str
    dataset_content_hash: str
    split_ref: str
    buckets: Mapping[str, TemperatureBucket]
    applied: frozenset[str] = field(default_factory=frozenset)
    ece_before: float = float("nan")
    ece_after: float = float("nan")

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_version": self.version,
            "dataset_content_hash": self.dataset_content_hash,
            "split_ref": self.split_ref,
            "ece_before": self.ece_before,
            "ece_after": self.ece_after,
            "precision": {
                "decimals": PRECISION_DECIMALS,
                "note": PRECISION_LIMITATION_NOTE,
            },
            "buckets": {key: bucket.to_dict() for key, bucket in sorted(self.buckets.items())},
            "applied": sorted(self.applied),
        }


class TemperatureNotRecorded(ValueError):
    """A temperature was requested for a bucket that has no recorded temperature."""


class DoubleTemperatureApplication(ValueError):
    """A second temperature was applied to an already temperature-scaled value."""


def fit_temperatures_by_bucket(
    records: Sequence[Mapping[str, Any]],
    *,
    fitted_on_split: str,
    dataset_content_hash: str,
    split_ref: str,
    grid: Sequence[float] = DEFAULT_TEMPERATURE_GRID,
    bins: int = 15,
) -> TemperatureArtifact:
    """Fit one temperature per (primitive, language, option-count) bucket.

    ``records`` are mappings with keys ``primitive``, ``language``, ``option_count``,
    ``logits`` (list of lists) and ``label_indices`` (list of ints) — already filtered
    to the held-out calibration split by the caller. Returns an artifact with every
    fitted temperature recorded and nothing applied yet.
    """
    if fitted_on_split != "calibration":
        raise ValueError(
            "Temperatures may only be fitted on the held-out calibration split."
        )
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        key = temperature_bucket(
            record["primitive"], record["language"], int(record["option_count"])
        )
        grouped.setdefault(key, []).append(record)

    buckets: dict[str, TemperatureBucket] = {}
    all_conf_before: list[float] = []
    all_correct_before: list[int] = []
    all_conf_after: list[float] = []
    all_correct_after: list[int] = []
    for key, group in sorted(grouped.items()):
        logits = [row for record in group for row in record["logits"]]
        labels = [label for record in group for label in record["label_indices"]]
        temperature = fit_temperature(logits, labels, grid=grid)
        ece_before = _ece_of_group(group, bins=bins, temperature=None)
        ece_after = _ece_of_group(group, bins=bins, temperature=temperature)
        buckets[key] = TemperatureBucket(
            key=key,
            primitive=str(group[0]["primitive"]).lower(),
            language=str(group[0]["language"]).lower(),
            option_count=int(group[0]["option_count"]),
            temperature=temperature,
            n=len(labels),
            ece_before=ece_before,
            ece_after=ece_after,
            fitted_on_split=fitted_on_split,
        )
        all_conf_before += _conf_of_group(group, temperature=None)
        all_correct_before += _correct_of_group(group, temperature=None)
        all_conf_after += _conf_of_group(group, temperature=temperature)
        all_correct_after += _correct_of_group(group, temperature=temperature)

    return TemperatureArtifact(
        version="1",
        dataset_content_hash=dataset_content_hash,
        split_ref=split_ref,
        buckets=buckets,
        applied=frozenset(),
        ece_before=expected_calibration_error(all_conf_before, all_correct_before, bins=bins),
        ece_after=expected_calibration_error(all_conf_after, all_correct_after, bins=bins),
    )


def _ece_of_group(
    group: Sequence[Mapping[str, Any]], *, bins: int, temperature: float | None
) -> float:
    return expected_calibration_error(
        _conf_of_group(group, temperature=temperature),
        _correct_of_group(group, temperature=temperature),
        bins=bins,
    )


def _conf_of_group(
    group: Sequence[Mapping[str, Any]], *, temperature: float | None
) -> list[float]:
    conf: list[float] = []
    for record in group:
        for probs, _label in zip(record["logits"], record["label_indices"], strict=False):
            scaled = (
                softmax_logits_temperature(probs, temperature)
                if temperature
                else softmax_logits_temperature(probs, 1.0)
            )
            predicted = max(range(len(scaled)), key=lambda i: scaled[i])
            conf.append(prob_of_correct(scaled, predicted))
    return conf


def _correct_of_group(
    group: Sequence[Mapping[str, Any]], *, temperature: float | None
) -> list[int]:
    correct: list[int] = []
    for record in group:
        for probs, label in zip(record["logits"], record["label_indices"], strict=False):
            scaled = (
                softmax_logits_temperature(probs, temperature)
                if temperature
                else softmax_logits_temperature(probs, 1.0)
            )
            predicted = max(range(len(scaled)), key=lambda i: scaled[i])
            correct.append(1 if predicted == label else 0)
    return correct


def apply_recorded_temperature(
    artifact: TemperatureArtifact,
    bucket_key: str,
    probs: Sequence[float],
    *,
    precision_decimals: int | None = PRECISION_DECIMALS,
) -> tuple[list[float], TemperatureArtifact]:
    """Apply a *recorded* temperature to one probability vector, refusing unsafe uses.

    * raises :class:`TemperatureNotRecorded` when ``bucket_key`` has no recorded
      temperature (a fitted temperature is only applied when it is recorded);
    * raises :class:`DoubleTemperatureApplication` when ``bucket_key`` is already in
      ``artifact.applied`` (a second temperature must not be applied to an
      already temperature-scaled value).
    Returns the rescaled probabilities and a new artifact with the bucket marked
    applied (the original artifact is immutable and unchanged).
    """
    bucket = artifact.buckets.get(bucket_key)
    if bucket is None:
        raise TemperatureNotRecorded(
            f"No recorded temperature for bucket {bucket_key!r}; fit it on the "
            "calibration split first and record it before applying."
        )
    if bucket_key in artifact.applied:
        raise DoubleTemperatureApplication(
            f"Bucket {bucket_key!r} already had its temperature applied; refusing to "
            "apply a second temperature to an already-scaled value."
        )
    scaled = temperature_scale_probs(
        probs, bucket.temperature, precision_decimals=precision_decimals
    )
    return scaled, TemperatureArtifact(
        version=artifact.version,
        dataset_content_hash=artifact.dataset_content_hash,
        split_ref=artifact.split_ref,
        buckets=artifact.buckets,
        applied=artifact.applied | {bucket_key},
        ece_before=artifact.ece_before,
        ece_after=artifact.ece_after,
    )
