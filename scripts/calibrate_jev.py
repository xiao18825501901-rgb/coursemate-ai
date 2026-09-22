"""Fit and write a Jev temperature-calibration artifact from a predictions file.

Reads a predictions file (model probability distributions/logits per sample), joins it
to the frozen split manifest, and fits one temperature per
(primitive, language, option-count) bucket **only on the held-out calibration split**.
Refuses to write when there is no held-out calibration split (the manifest defines
``train`` / ``calibration`` / ``test`` and the calibration split must be non-empty), so
a temperature can never be fitted on (or leaked from) the train/test rows.

No network and no model calls: the predictions file is the only model evidence.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAG_SERVICE = ROOT / "services" / "rag-api"
sys.path.insert(0, str(RAG_SERVICE))

from app.evaluation.jev_calibration import (
    PRECISION_LIMITATION_NOTE,
    fit_temperatures_by_bucket,
    probs_to_logits,
)
from app.evaluation.jev_semantic_ablation import (
    SPLIT_NAMES,
    judgments_from_dataset,
    validate_split_leakage,
)

DATASET_PATH = ROOT / "benchmarks" / "jev-judgments.dataset.json"
SPLIT_PATH = ROOT / "benchmarks" / "jev-calibration.split.json"
DEFAULT_OUT = ROOT / "work" / "current-change" / "jev-temperature-calibration.json"


def _write_json(path: Path, payload: dict) -> None:
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _load_predictions(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read predictions file {path}: {error}") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("predictions"), list):
        raise ValueError(  # noqa: TRY004 - malformed file, not a Python type error
            "Predictions file must be a JSON object with a 'predictions' list."
        )
    return payload


def _split_map(samples, manifest):
    assignment: dict[str, str] = {}
    for name in SPLIT_NAMES:
        for sample_id in manifest.get("splits", {}).get(name, {}).get("sample_ids", []):
            assignment[str(sample_id)] = name
    return assignment


def fit_and_write(
    predictions_path: Path,
    out: Path,
    *,
    dataset_path: Path | None = None,
    split_path: Path | None = None,
) -> dict:
    """Fit and write the artifact. ``dataset_path``/``split_path`` default to the frozen pair.

    They exist so a companion dataset (the round-31 module-judgment set) can be calibrated
    with the same maths and the same leakage validation instead of being unreachable: the
    contract is unchanged — fit only on the held-out calibration split, refuse when there
    is none, and refuse when a calibration row has no prediction.
    """
    dataset = json.loads((dataset_path or DATASET_PATH).read_text(encoding="utf-8"))
    manifest = json.loads((split_path or SPLIT_PATH).read_text(encoding="utf-8"))
    samples = judgments_from_dataset(dataset)
    validate_split_leakage(samples, manifest)
    assignment = _split_map(samples, manifest)

    predictions = _load_predictions(predictions_path)
    by_id = {str(p.get("sample_id")): p for p in predictions["predictions"]}
    label_by_id = {s.sample_id: s.label["q"] for s in samples}

    calibration_ids = {sid for sid, split in assignment.items() if split == "calibration"}
    if not calibration_ids:
        raise SystemExit(
            "Refusing to write: the split manifest has no held-out calibration split "
            "(calibration split is empty)."
        )

    records = []
    for sid in sorted(calibration_ids):
        pred = by_id.get(sid)
        if pred is None:
            raise SystemExit(
                f"Refusing to write: calibration sample {sid!r} has no entry in the "
                "predictions file; every calibration row must be predicted."
            )
        label = label_by_id.get(sid)
        if label is None:
            raise SystemExit(f"Refusing to write: unknown calibration sample {sid!r}.")
        primitive = str(pred.get("primitive") or _primitive_of(label)).lower()
        logits = pred.get("logits")
        if logits is None:
            probs = pred.get("probabilities")
            if probs is None:
                raise SystemExit(
                    f"prediction {sid!r} must carry 'logits' or 'probabilities'."
                )
            logits = probs_to_logits(probs)
        logits = [float(v) for v in logits]
        label_index = pred.get("label_index")
        if label_index is None:
            label_index = _label_index_of(label, primitive)
        label_index = int(label_index)
        records.append(
            {
                "primitive": primitive,
                "language": str(pred.get("language") or "en").lower(),
                "option_count": int(pred.get("option_count") or len(logits)),
                "logits": [logits],
                "label_indices": [label_index],
            }
        )
    if not records:
        raise SystemExit(
            "Refusing to write: no calibration-split predictions available."
        )

    source_dataset = dataset_path or DATASET_PATH
    source_split = split_path or SPLIT_PATH
    artifact = fit_temperatures_by_bucket(
        records,
        fitted_on_split="calibration",
        dataset_content_hash=manifest["content_hash"],
        # Provenance must name the files actually used: recording the frozen paths while
        # fitting a companion dataset would pin the artifact to a split it never saw.
        split_ref=str(source_split.name),
    )
    payload = artifact.to_dict()
    payload["dataset_path"] = str(source_dataset)
    payload["predictions_path"] = str(predictions_path)
    payload["n_calibration"] = len(records)
    payload["precision_note"] = PRECISION_LIMITATION_NOTE
    _write_json(out, payload)
    return payload


def _primitive_of(label: dict) -> str:
    if "noul" in label:
        return "noul"
    if "score_index" in label:
        return "score"
    return "choice"


def _label_index_of(label: dict, primitive: str) -> int:
    if primitive == "noul":
        return 1 if label.get("noul") else 0
    if primitive == "score":
        return int(label.get("score_index", 0))
    # choice labels are candidate ids; the predictions file must supply label_index.
    raise SystemExit("choice labels require an explicit 'label_index' in the prediction.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="dataset JSON (default: the frozen benchmarks/jev-judgments.dataset.json)",
    )
    parser.add_argument(
        "--split",
        type=Path,
        default=None,
        help="split manifest (default: the frozen benchmarks/jev-calibration.split.json)",
    )
    args = parser.parse_args()
    if args.out.exists() or args.out.with_name(f".{args.out.name}.partial").exists():
        print("Refusing to overwrite an existing calibration artifact or partial checkpoint.")
        return 2
    try:
        payload = fit_and_write(
            args.predictions, args.out, dataset_path=args.dataset, split_path=args.split
        )
    except ValueError as error:
        print(f"Calibration preflight failed: {error}")
        return 2
    ece_before = payload["ece_before"]
    ece_after = payload["ece_after"]
    print(
        f"Wrote {args.out}: ECE {_fmt(ece_before)} -> {_fmt(ece_after)} "
        f"({len(payload['buckets'])} buckets, {payload['n_calibration']} calibration rows)"
    )
    if not math.isfinite(ece_before) or not math.isfinite(ece_after):
        print("WARNING: ECE is NaN/Inf; too few calibration rows for a stable estimate.")
    return 0


def _fmt(value) -> str:
    return "nan" if value is None or not math.isfinite(float(value)) else f"{float(value):.4f}"


if __name__ == "__main__":
    raise SystemExit(main())
