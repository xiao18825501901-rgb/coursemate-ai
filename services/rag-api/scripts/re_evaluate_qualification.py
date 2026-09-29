"""Re-evaluate a stored qualification artifact under the current gate.

The gate can change for reasons that have nothing to do with the reviewers -- a
floor is raised, a new condition is added -- and re-running the whole
qualification to discover that a stored measurement is now non-qualifying would
be wasteful.  The artifact already contains every row outcome, so the decision
can be recomputed exactly, offline, with no provider call.

Usage:

    python re_evaluate_qualification.py <artifact.json> [--min-negatives 8]
                                        [--min-independent-negatives 16]
                                        [--min-release-recall 0.5]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.learning.hybrid_qualification import RowOutcome, qualify  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact")
    parser.add_argument("--min-positives", type=int, default=3)
    parser.add_argument("--min-negatives", type=int, default=8)
    parser.add_argument("--min-independent-negatives", type=int, default=16)
    parser.add_argument("--min-release-recall", type=float, default=0.5)
    args = parser.parse_args()

    payload = json.loads(Path(args.artifact).read_text(encoding="utf-8"))
    outcomes = [
        RowOutcome(
            row_id=str(row["row_id"]),
            family_id=str(row["family_id"]),
            label=str(row["label"]),
            language=str(row["language"]),
            domain=str(row["domain"]),
            question_type=str(row["question_type"]),
            released=bool(row["released"]),
            case_outcomes=dict(row["case_outcomes"]),
            target_case=row.get("target_case"),
            defect=row.get("defect"),
            provenance=str(row.get("provenance") or ""),
            reasons=list(row.get("reasons") or []),
        )
        for row in payload["row_outcomes"]
    ]
    reviewer = payload.get("reviewer") or {}
    decision = qualify(
        outcomes,
        method_identity=str(reviewer.get("method_identity") or "0" * 64),
        observed_model_facts=payload.get("decision", {}).get("observed_model_facts", {}),
        min_positives_per_case=args.min_positives,
        min_negatives_per_case=args.min_negatives,
        min_independent_negatives=args.min_independent_negatives,
        min_release_recall=args.min_release_recall,
    )
    recorded = payload.get("decision", {}).get("status")
    print(
        json.dumps(
            {
                "artifact": args.artifact,
                "recorded_status": recorded,
                "re_evaluated_status": decision["status"],
                "cases": decision["cases"],
                "unmeasured_cases": decision["unmeasured_cases"],
                "release": decision["summary"]["release"],
                "independent_negative_families": decision["summary"][
                    "independent_negative_families"
                ],
                "zero_false_accept_upper_bound_95": decision["summary"][
                    "zero_false_accept_upper_bound_95"
                ],
                "sample_sufficient": decision["sample_sufficient"],
                "coverage_sufficient": decision["coverage_sufficient"],
                "min_release_recall": decision["min_release_recall"],
                "release_recall": decision["release_recall"],
                "per_case": {
                    case: {
                        "positives": entry["positives"],
                        "negatives": entry["negatives"],
                        "false_accept": entry["false_accept"],
                    }
                    for case, entry in decision["per_case_evidence"].items()
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
