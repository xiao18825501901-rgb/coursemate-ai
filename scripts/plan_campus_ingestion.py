"""Turn the campus inventory into an ingestion plan, without ingesting anything.

    python scripts/plan_campus_ingestion.py \\
        --inventory docs/coursejesus/LOCAL_CAMPUS_INVENTORY.csv \\
        --full work/current-change/campus-inventory-full.csv \\
        --plan work/current-change/campus-ingestion-plan.json \\
        --review-list docs/coursejesus/CAMPUS_RIGHTS_REVIEW_LIST.csv

The committed inventory is the redacted one: personal filenames are replaced with
`REDACTED_PERSONAL_OR_RESTRICTED`, which is right for Git but useless for planning, because a plan
has to read the real files. The script therefore takes the **full** working copy for the plan and
writes the review list from the committed one, so what lands in the repository never contains a
personal name.

Exit codes: 0 when a plan was written, 2 when the inventory could not be read.
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys
from typing import Any

# Runnable from the repository root as the campus scripts document it: the service package has to
# be importable from here, or the first `app.*` import is a ModuleNotFoundError.
_SERVICE_ROOT = pathlib.Path(__file__).resolve().parents[1] / "services" / "rag-api"
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from app.campus_ingestion import (
    BLOCKED,
    DOWNLOAD_ONLY,
    INGESTABLE,
    first_course_with_material,
    load_inventory,
    plan,
)

CREDENTIAL_KEYS = ("usageRights", "licenseNote", "sourceNotice", "publicationBasis")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=pathlib.Path)
    parser.add_argument("--full", required=True, type=pathlib.Path)
    parser.add_argument("--plan", required=True, type=pathlib.Path)
    parser.add_argument("--review-list", required=True, type=pathlib.Path)
    parser.add_argument(
        "--course",
        default="",
        help="plan one Canvas course id only (default: every course in the inventory)",
    )
    return parser


def summarise(plans: dict[tuple[str, str], Any]) -> dict[str, Any]:
    totals = {INGESTABLE: 0, DOWNLOAD_ONLY: 0, BLOCKED: 0}
    for course in plans.values():
        for status, count in course.counts().items():
            totals[status] = totals.get(status, 0) + count
    courses_with_material = [item for item in plans.values() if item.ingestable]
    first = first_course_with_material(plans)
    return {
        "courses": len(plans),
        "coursesWithIngestableMaterial": len(courses_with_material),
        "files": sum(totals.values()),
        "byDecision": totals,
        "firstCourse": (
            None
            if first is None
            else {
                "courseId": first.course_id,
                "courseCode": first.course_code,
                "ingestable": len(first.ingestable),
            }
        ),
        "published": False,
        "note": (
            "Nothing here has been ingested or published. Every file keeps "
            "review_status=NEEDS_REVIEW and publication_basis=RIGHTS_UNVERIFIED until a person "
            "decides; the review list is the single list of what needs that decision."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.full.is_file():
        print(f"the full inventory is required for a plan: {args.full} is not a file", file=sys.stderr)
        return 2

    rows = load_inventory(args.full)
    plans = plan(rows)
    if args.course:
        plans = {key: value for key, value in plans.items() if key[1] == args.course}
        if not plans:
            print(f"no offering {args.course!r} in the inventory", file=sys.stderr)
            return 2

    payload = {
        "schemaVersion": 1,
        "source": str(args.full),
        "summary": summarise(plans),
        "courses": [item.as_dict() for _, item in sorted(plans.items())],
    }
    args.plan.parent.mkdir(parents=True, exist_ok=True)
    args.plan.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # The review list is written from the committed inventory, so no personal filename leaves the
    # machine, and it is limited to the files that need a decision.
    public_rows = {row.key: row for row in load_inventory(args.inventory)}
    decisions: list[dict[str, str]] = []
    for _, course in sorted(plans.items()):
        for row in course.rows:
            decision = course.decisions[row.key]
            safe = public_rows.get(row.key, row)
            decisions.append(
                {
                    "institution_origin": row.institution_origin,
                    "canvas_course_id": row.course_id,
                    "course_code": row.course_code,
                    "filename": safe.filename,
                    "sha256": row.sha256,
                    "bytes": str(row.bytes_disk),
                    "classification": row.classification,
                    "decision": decision.status,
                    "reason": decision.reason,
                    "review_status": decision.review_status,
                    "publication_basis": row.publication_basis,
                }
            )
    needs_decision = [
        item for item in decisions if item["review_status"] != "NOT_FOR_PUBLICATION"
    ]
    args.review_list.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "institution_origin",
        "canvas_course_id",
        "course_code",
        "filename",
        "sha256",
        "bytes",
        "classification",
        "decision",
        "reason",
        "review_status",
        "publication_basis",
    ]
    with args.review_list.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(needs_decision)

    summary = payload["summary"]
    print(
        f"courses={summary['courses']} files={summary['files']} "
        f"ingestable={summary['byDecision'][INGESTABLE]} "
        f"download_only={summary['byDecision'][DOWNLOAD_ONLY]} "
        f"blocked={summary['byDecision'][BLOCKED]}"
    )
    print(f"courses with ingestable material: {summary['coursesWithIngestableMaterial']}")
    if summary["firstCourse"]:
        first = summary["firstCourse"]
        print(
            f"first verification candidate: {first['courseId']} ({first['courseCode']}) "
            f"with {first['ingestable']} ingestable file(s)"
        )
    print(f"plan: {args.plan}")
    print(f"review list ({len(needs_decision)} rows): {args.review_list}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
