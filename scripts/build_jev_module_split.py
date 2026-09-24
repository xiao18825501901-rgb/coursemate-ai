#!/usr/bin/env python
"""Build (or verify) the frozen split manifest for a companion Jev dataset.

The frozen primary dataset has a committed split manifest; the companion dataset added in
round 31 for the seven previously-uncovered definitions had none, which meant the
calibration CLI — whose whole contract is "fit only on the held-out calibration split,
refuse when there is none" — could not consume it at all. This tool produces the same
manifest shape from the same code (`build_split_manifest`), so both datasets are pinned
identically.

It is **idempotent**: running it against a dataset whose manifest already exists verifies
the manifest instead of overwriting it, and any difference is a hard error rather than a
silent rewrite of a pinned split. `--force` is the explicit way to regenerate.

Usage::

    python scripts/build_jev_module_split.py                       # companion dataset
    python scripts/build_jev_module_split.py --dataset P --split Q # any dataset
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_DATASET = ROOT / "benchmarks" / "jev-module-judgments.dataset.json"
DEFAULT_SPLIT = ROOT / "benchmarks" / "jev-module-judgments.split.json"


def _evaluation_api() -> Any:
    """Import the evaluation package after putting the service on ``sys.path``.

    Deferred on purpose: the sibling scripts insert the path at module level and carry
    ``noqa: E402`` for it, which is a lint finding under one config or the other. Doing it
    inside a function keeps this file clean under every config and avoids mutating
    ``sys.path`` merely by importing it.
    """
    service = str(ROOT / "services" / "rag-api")
    if service not in sys.path:
        sys.path.insert(0, service)
    from app.evaluation import jev_semantic_ablation

    return jev_semantic_ablation


def build(dataset_path: Path, split_path: Path, *, force: bool) -> dict:
    api = _evaluation_api()
    payload = api.load_jev_dataset(dataset_path)
    samples = api.judgments_from_dataset(payload)
    manifest = api.build_split_manifest(samples)
    # The manifest must satisfy the same leakage invariants the frozen one does: split by
    # group, never by row, one split per sample, no group across two splits.
    api.validate_split_leakage(samples, manifest)

    if split_path.exists() and not force:
        existing = json.loads(split_path.read_text(encoding="utf-8"))
        if existing != manifest:
            raise SystemExit(
                f"{split_path} exists and differs from the manifest built from "
                f"{dataset_path}. A pinned split is never rewritten silently; re-run with "
                "--force only if the dataset genuinely changed."
            )
        print(f"verified unchanged: {split_path}")
        return manifest

    split_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"wrote {split_path}")
    return manifest


def report(manifest: dict, samples: Any) -> None:
    api = _evaluation_api()
    print(f"content_hash: {manifest['content_hash']}")
    counts = {name: payload["count"] for name, payload in manifest["splits"].items()}
    print(f"splits: {counts}")
    print("\nper-definition split coverage:")
    for definition_id, per_split in sorted(api.split_coverage(samples).items()):
        flag = (
            "  <-- no calibration sample: thresholds cannot be fitted"
            if per_split["calibration"] == 0
            else ""
        )
        print(f"  {definition_id:32s} {per_split}{flag}")
    unfittable = api.unfittable_definitions(samples)
    unevaluated = api.unevaluated_definitions(samples)
    if unfittable:
        print(
            "\nDEFINITIONS WITHOUT A CALIBRATION SPLIT: "
            + ", ".join(unfittable)
            + "\n  (recorded, not hidden: these need more groups before a temperature can "
            "be fitted for them)"
        )
    if unevaluated:
        print(
            "\nDEFINITIONS WITHOUT A TEST SPLIT: "
            + ", ".join(unevaluated)
            + "\n  (recorded, not hidden: nothing is held out to evaluate these on yet)"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--split", type=Path, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    split_path = args.split or (
        DEFAULT_SPLIT
        if args.dataset == DEFAULT_DATASET
        else args.dataset.with_suffix(".split.json")
    )
    manifest = build(args.dataset, split_path, force=args.force)
    if not args.quiet:
        api = _evaluation_api()
        report(manifest, api.judgments_from_dataset(api.load_jev_dataset(args.dataset)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
