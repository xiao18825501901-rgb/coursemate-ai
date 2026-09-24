"""Ingest one Canvas offering's qualified material into a **non-public** campus course.

    python scripts/ingest_campus_course.py \\
        --plan work/current-change/campus-ingestion-plan.json \\
        --course 628 \\
        --database work/current-change/campus-ingest.sqlite3 \\
        --uploads work/current-change/campus-uploads \\
        --report work/current-change/campus-ingest-628.json

What it does, in order, and nothing more:

1. reads the plan and takes the offering's files and decisions;
2. creates the campus course **private** — an administrator course is published as it is created,
   and migration 019 freezes a course that is pending or published, so `private` is the only state
   that is both invisible to students and writable;
3. ingests the `INGESTABLE` files through the real `IngestionService` (documents, chunks, index),
   re-verifying each file's size and SHA-256 against the inventory first;
4. records one `campus_material_records` row per file with its decision, reason and rights
   metadata, and leaves `review_status = NEEDS_REVIEW`.

It does **not** publish anything, and it cannot: publication is a separate, human decision, and the
course is left private with its review list intact.

Exit codes: 0 with a report, 2 when the plan or the offering cannot be read.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

# The docstring's usage line runs this script from the repository root with no PYTHONPATH, so the
# service package has to be importable from here. Without it the first `app.*` import raises an
# ImportError, which would hide the growth-pause refusal behind an unrelated traceback.
_SERVICE_ROOT = pathlib.Path(__file__).resolve().parents[1] / "services" / "rag-api"
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from app.campus_growth import (
    CampusCatalogGrowthPaused,
    require_growth_open,
)
from app.campus_ingestion import (
    CampusMaterialRepository,
    InventoryRow,
    MaterialDecision,
    campus_course_id,
    ingest_course,
    plan,
)
from app.config import Settings
from app.db import Database
from app.models import CourseCreate, PublicationStatus
from app.rag.embeddings import DeterministicEmbeddingProvider
from app.services.ingestion import IngestionService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=pathlib.Path)
    parser.add_argument("--course", required=True, help="the Canvas course id to ingest")
    parser.add_argument("--database", required=True, type=pathlib.Path)
    parser.add_argument("--uploads", required=True, type=pathlib.Path)
    parser.add_argument("--report", required=True, type=pathlib.Path)
    parser.add_argument("--institution", default="", help="restrict to one institution origin")
    return parser


def row_from_plan(
    entry: dict[str, Any], course: dict[str, Any], root: str
) -> tuple[InventoryRow, MaterialDecision]:
    """Rebuild the row and decision **from the facts the plan recorded**, not from its verdict.

    The plan carries the classification, parse class and disk status each decision was made from,
    so re-running the policy here re-derives the same answer. Trusting the recorded status alone
    would let a plan written by an older policy be acted on by a newer one.
    """
    decision = MaterialDecision(
        status=str(entry["status"]),
        reason=str(entry["reason"]),
        review_status=str(entry["review_status"]),
    )
    row = InventoryRow(
        source_root=root,
        institution_origin=str(course["institutionOrigin"]),
        course_id=str(course["courseId"]),
        course_code=str(course["courseCode"]),
        course_name=str(course["courseName"]),
        term=str(course.get("term", "")),
        summary_category="",
        relative_path=str(entry["relativePath"]),
        filename=str(entry["filename"]),
        bytes_disk=int(entry["bytes"]),
        sha256=str(entry["sha256"]),
        mime_guess="",
        parse_class=str(entry.get("parseClass", "")),
        classification=str(entry.get("classification", "")),
        classification_reason="",
        disk_status=str(entry.get("diskStatus", "PRESENT")),
        publication_basis=str(
            entry.get("publicationBasis") or "OWNER_PLATFORM_IMPORT_INTENT_RIGHTS_UNVERIFIED"
        ),
        review_status="NEEDS_REVIEW",
    )
    return row, decision


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Growth is closed since the final batch was frozen (2026-09-24): refuse before reading the
    # plan, the source files or the database, so a paused invocation cannot half-create a course.
    try:
        require_growth_open(f"ingest Canvas offering {args.course!r} from the local source roots")
    except CampusCatalogGrowthPaused as paused:
        print(str(paused), file=sys.stderr)
        return 3
    if not args.plan.is_file():
        print(f"plan not found: {args.plan}", file=sys.stderr)
        return 2
    payload = json.loads(args.plan.read_text(encoding="utf-8"))
    courses = [
        item
        for item in payload.get("courses", [])
        if str(item.get("courseId")) == str(args.course)
        and (not args.institution or item.get("institutionOrigin") == args.institution)
    ]
    if not courses:
        print(f"offering {args.course!r} is not in the plan", file=sys.stderr)
        return 2
    if len(courses) > 1:
        # Two scan roots exist (`D:\Canvas` and `D:\Canvas-DG`) and the plan records each offering's
        # own `sourceRoot`, because the same relative path exists under both — so acting on the
        # wrong one would ingest another institution's file. Today's plan has no course id under two
        # institutions, so this cannot happen yet; taking the first match would make it happen
        # *silently* the day one appears, which is the failure this refuses instead.
        origins = ", ".join(sorted({str(item.get("institutionOrigin")) for item in courses}))
        print(
            f"offering {args.course!r} appears under more than one institution ({origins}); "
            "pass --institution to say which one, because the files come from a different root",
            file=sys.stderr,
        )
        return 2
    course = courses[0]

    # The plan records each course's scan root, because the same relative path exists under both
    # Canvas roots and acting on the wrong one would ingest the wrong file.
    source_root = str(course.get("sourceRoot") or "")
    if not source_root:
        print(
            "the plan does not record its source root; write the plan with "
            "scripts/plan_campus_ingestion.py against the scan output first",
            file=sys.stderr,
        )
        return 2

    # Everything that can refuse the plan is checked **before** anything is written, so a refused
    # run leaves no half-created course behind: the staleness check used to sit after the course was
    # created, which is how the CLI's own test found an empty private course left by a plan it had
    # just refused.
    rebuilt_rows = [row_from_plan(entry, course, source_root) for entry in course["files"]]
    rows = [row for row, _decision in rebuilt_rows]
    rebuilt = plan(rows)
    course_plan = rebuilt[(str(course["institutionOrigin"]), str(course["courseId"]))]
    # The policy is re-derived from the recorded facts; if it now disagrees with the plan's verdict,
    # the plan is stale and acting on it would ingest something the policy refuses.
    stale = [
        row.relative_path
        for row, decision in rebuilt_rows
        if course_plan.decisions[row.key].status != decision.status
    ]
    if stale:
        print(
            f"the plan is stale for {len(stale)} file(s); re-run plan_campus_ingestion.py "
            f"(first: {stale[0]})",
            file=sys.stderr,
        )
        return 2

    settings = Settings(
        database_path=args.database,
        upload_dir=args.uploads,
        app_env="test",
        v3_enabled=True,
        rag_provider_mode="deterministic",
        ui_web_dir=args.uploads.parent / "no-web-build",
    )
    database = Database(settings)
    database.initialize()
    service = IngestionService(database, settings, DeterministicEmbeddingProvider())

    target = campus_course_id(str(course["institutionOrigin"]), str(course["courseId"]))
    with database.connect() as connection:
        # Autocommit on this long-lived connection: the ingestion service writes on its own
        # connections, and a held implicit transaction here would block its BEGIN IMMEDIATE.
        connection.isolation_level = None
        repository = CampusMaterialRepository(connection)
        existing = connection.execute(
            "SELECT visibility, publication_status, published_at FROM courses WHERE id=?",
            (target,),
        ).fetchone()
        if existing is None:
            service.create_course(
                CourseCreate(
                    id=target,
                    name=str(course["courseCode"] or course["courseName"] or target)[:120],
                    description=(
                        f"由 {course['institutionOrigin']} 的 Canvas 课程 "
                        f"{course['courseId']} 导入；资料权限尚未核定，课程保持私有。"
                    ),
                ),
                is_admin=True,
                publication_status=PublicationStatus.PRIVATE,
            )
        elif existing["publication_status"] != "private":
            # A published or under-review course is a frozen, reviewed release (migration 019);
            # adding material to it would change an object a reviewer already approved.
            print(
                f"the campus course {target} is {existing['publication_status']}; "
                "new material needs a new revision, not an import into a frozen release",
                file=sys.stderr,
            )
            return 2
        report = ingest_course(
            course_plan, service=service, repository=repository, target_course_id=target
        )
        stored = connection.execute(
            "SELECT visibility, publication_status, published_at FROM courses WHERE id=?",
            (target,),
        ).fetchone()
        documents = connection.execute(
            "SELECT COUNT(*) AS documents, COALESCE(SUM(chunk_count), 0) AS chunks "
            "FROM documents WHERE course_id=?",
            (target,),
        ).fetchone()
        review = len(repository.review_list())

    outcome = {
        "courseId": course["courseId"],
        "courseCode": course["courseCode"],
        "institutionOrigin": course["institutionOrigin"],
        "targetCourseId": target,
        "courseState": {
            "visibility": stored["visibility"],
            "publicationStatus": stored["publication_status"],
            "publishedAt": stored["published_at"],
        },
        "documents": int(documents["documents"]),
        "chunks": int(documents["chunks"]),
        "reviewListRows": review,
        "published": False,
        "ingestion": report.as_dict(),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"course {outcome['courseId']} -> {target}: "
        f"indexed={report.indexed} chunks={report.chunks} "
        f"download_only={report.counts().get('DOWNLOAD_ONLY', 0)} "
        f"blocked={report.counts().get('BLOCKED', 0)}"
    )
    print(
        f"course state: visibility={stored['visibility']} "
        f"publication={stored['publication_status']} published_at={stored['published_at']}"
    )
    print(f"documents={outcome['documents']} chunks={outcome['chunks']} review rows={review}")
    print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
