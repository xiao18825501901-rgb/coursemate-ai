"""The campus ingest CLI's refusals and its one happy path, driven end to end.

Until now `scripts/ingest_campus_course.py` was verified by *running* it against the real library
(rounds 71, 76, 78) and never by a test, so every guard in it — a private-only creation, the
staleness check, the refusal to write into a reviewed course — rested on my having watched it
happen. These tests drive `main(argv)` itself against a temporary plan, database and upload
directory, with the **real** planner (`plan_campus_ingestion.py`) writing the plan so the fixture
cannot drift from the format the CLI reads.

The distinctions that matter here are the ones a crash would hide: "refused with a reason and
exit 2" is a different outcome from "raised an exception", and "stored but unreadable" is different
from "indexed".
"""

from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import sqlite3
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ingest_campus_course as ingest_cli  # noqa: E402  (import after the path insert)
import plan_campus_ingestion as planner  # noqa: E402

CITYU = "https://canvas.cityu.edu.hk"
CITYU_DG = "https://cityu-dg.instructure.com"
COURSE_ID = "70579"
MARKDOWN = b"# Access control\n\nA capability is a transferable right to a resource.\n"
INVENTORY_FIELDS = (
    "source_root",
    "institution_origin",
    "course_id",
    "course_code",
    "course_name",
    "term",
    "summary_category",
    "relative_path",
    "filename",
    "bytes_disk",
    "sha256",
    "mime_guess",
    "parse_class",
    "classification",
    "classification_reason",
    "disk_status",
    "publication_basis",
    "review_status",
    "duplicate_group",
)


def material(
    root: pathlib.Path,
    relative: str,
    content: bytes,
    *,
    institution: str = CITYU,
    course_id: str = COURSE_ID,
    parse_class: str = "PARSEABLE",
    classification: str = "ACADEMIC_TEACHING",
    disk_status: str = "PRESENT",
) -> dict[str, str]:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {
        "source_root": str(root),
        "institution_origin": institution,
        "course_id": course_id,
        "course_code": "CS4394",
        "course_name": "Info Security and Mgt",
        "term": "2026 Summer",
        "summary_category": "Academic",
        "relative_path": relative,
        "filename": pathlib.PurePosixPath(relative).name,
        "bytes_disk": str(len(content)),
        "sha256": hashlib.sha256(content).hexdigest(),
        "mime_guess": "text/markdown",
        "parse_class": parse_class,
        "classification": classification,
        "classification_reason": "the scan says this is teaching material",
        "disk_status": disk_status,
        "publication_basis": "OWNER_PLATFORM_IMPORT_INTENT_RIGHTS_UNVERIFIED",
        "review_status": "NEEDS_REVIEW",
        "duplicate_group": "",
    }


def write_inventory(path: pathlib.Path, rows: list[dict[str, str]]) -> pathlib.Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(INVENTORY_FIELDS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


class Fixture:
    """One temporary library, planned by the real planner and ready for the real CLI."""

    def __init__(self, tmp_path: pathlib.Path, rows: list[dict[str, str]]) -> None:
        self.root = tmp_path
        self.inventory = write_inventory(tmp_path / "inventory.csv", rows)
        self.plan = tmp_path / "plan.json"
        self.review_list = tmp_path / "review-list.csv"
        assert (
            planner.main(
                [
                    "--inventory",
                    str(self.inventory),
                    "--full",
                    str(self.inventory),
                    "--plan",
                    str(self.plan),
                    "--review-list",
                    str(self.review_list),
                ]
            )
            == 0
        )
        self.database = tmp_path / "campus.sqlite3"
        self.uploads = tmp_path / "uploads"
        self.report = tmp_path / "report.json"

    def argv(self, *, course: str = COURSE_ID, plan: pathlib.Path | None = None) -> list[str]:
        return [
            "--plan",
            str(plan or self.plan),
            "--course",
            course,
            "--database",
            str(self.database),
            "--uploads",
            str(self.uploads),
            "--report",
            str(self.report),
        ]

    def run(self, *, course: str = COURSE_ID, plan: pathlib.Path | None = None) -> int:
        return ingest_cli.main(self.argv(course=course, plan=plan))

    def rewritten_plan(self, mutate) -> pathlib.Path:  # type: ignore[no-untyped-def]
        payload = json.loads(self.plan.read_text(encoding="utf-8"))
        mutate(payload)
        target = self.root / "plan-mutated.json"
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def courses(self) -> list[sqlite3.Row]:
        connection = sqlite3.connect(f"file:{self.database}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            return list(connection.execute("SELECT * FROM courses ORDER BY id").fetchall())
        finally:
            connection.close()


def library(tmp_path: pathlib.Path) -> Fixture:
    """One offering with a readable file, an unreadable one and a personal one."""
    source = tmp_path / "canvas"
    rows = [
        material(source, "01_course/notes.md", MARKDOWN),
        material(
            source,
            "01_course/slides.zip",
            b"PK\x03\x04not really a zip",
            parse_class="DOWNLOAD_ONLY",
        ),
        material(
            source,
            "01_course/class-list.xlsx",
            b"PK\x03\x04fake",
            classification="PERSONAL_OR_RESTRICTED",
        ),
    ]
    return Fixture(tmp_path, rows)


def test_the_cli_ingests_one_offering_into_a_private_course(tmp_path) -> None:
    fixture = library(tmp_path)

    assert fixture.run() == 0

    report = json.loads(fixture.report.read_text(encoding="utf-8"))
    assert report["published"] is False
    assert report["courseState"] == {
        "visibility": "private",
        "publicationStatus": "private",
        "publishedAt": None,
    }
    assert report["ingestion"]["counts"]["INDEXED"] == 1
    # `counts()` only carries statuses that occurred, so the absences are asserted with a default.
    assert report["ingestion"]["counts"].get("SKIPPED_IDENTICAL", 0) == 0
    # The unreadable file is stored, not failed, and the personal one never enters the library.
    assert report["ingestion"]["counts"]["DOWNLOAD_ONLY"] == 1
    assert report["ingestion"]["counts"]["BLOCKED"] == 1
    assert report["ingestion"]["counts"].get("FAILED", 0) == 0
    assert report["documents"] == 1 and report["chunks"] > 0

    course = fixture.courses()[0]
    assert course["visibility"] == "private"
    assert course["publication_status"] == "private"
    assert course["published_at"] is None
    # Round 74's policy: a campus course carries the label and the verification gate.
    assert course["display_type"] == "campus"
    assert course["requires_student_verification"] == 1

    # The review list the owner has to decide excludes the personal row by review status.
    with fixture.review_list.open(encoding="utf-8", newline="") as handle:
        listed = list(csv.DictReader(handle))
    assert {row["review_status"] for row in listed} == {"NEEDS_REVIEW"}


def test_running_the_same_offering_twice_does_not_duplicate_the_document(tmp_path) -> None:
    """The re-run is the normal case: a batch is resumed, not restarted."""
    fixture = library(tmp_path)
    assert fixture.run() == 0
    first = json.loads(fixture.report.read_text(encoding="utf-8"))

    assert fixture.run() == 0
    second = json.loads(fixture.report.read_text(encoding="utf-8"))

    assert second["documents"] == first["documents"]
    assert second["ingestion"]["counts"]["SKIPPED_IDENTICAL"] == 1
    assert second["ingestion"]["counts"].get("INDEXED", 0) == 0


def test_an_offering_under_two_institutions_is_refused_instead_of_guessed(tmp_path, capsys) -> None:
    """The same Canvas course id under two institutions must not silently pick one.

    The two scan roots are different institutions with different files at the same relative paths,
    so the wrong choice ingests the wrong material. Today's plan has no such pair; this is the guard
    for the day one appears.
    """
    fixture = library(tmp_path)

    def duplicate(payload: dict) -> None:
        original = payload["courses"][0]
        clone = json.loads(json.dumps(original))
        clone["institutionOrigin"] = CITYU_DG
        clone["sourceRoot"] = str(fixture.root / "canvas-dg")
        payload["courses"].append(clone)

    ambiguous = fixture.rewritten_plan(duplicate)
    assert fixture.run(plan=ambiguous) == 2

    message = capsys.readouterr().err
    assert "--institution" in message
    assert CITYU in message and CITYU_DG in message
    assert not fixture.database.exists() or fixture.courses() == []


def test_an_offering_that_is_not_in_the_plan_is_refused(tmp_path, capsys) -> None:
    fixture = library(tmp_path)
    assert fixture.run(course="99999") == 2
    assert "is not in the plan" in capsys.readouterr().err


def test_a_missing_plan_is_refused(tmp_path, capsys) -> None:
    fixture = library(tmp_path)
    missing = fixture.root / "no-such-plan.json"
    assert fixture.run(plan=missing) == 2
    assert "plan not found" in capsys.readouterr().err


def test_a_plan_without_a_source_root_is_refused(tmp_path, capsys) -> None:
    """Without the scan root the CLI cannot know which of the two libraries a path means."""
    fixture = library(tmp_path)

    def strip(payload: dict) -> None:
        payload["courses"][0]["sourceRoot"] = ""

    assert fixture.run(plan=fixture.rewritten_plan(strip)) == 2
    assert "source root" in capsys.readouterr().err


def test_a_plan_whose_status_disagrees_with_the_policy_is_refused(tmp_path, capsys) -> None:
    """A plan written by an older policy must not be acted on by this one.

    The fixture flips the readable file's recorded verdict to `DOWNLOAD_ONLY` while leaving the
    facts that produced `INGESTABLE` in place — which is exactly what a stale plan looks like.
    """
    fixture = library(tmp_path)

    def flip(payload: dict) -> None:
        for entry in payload["courses"][0]["files"]:
            if entry["filename"] == "notes.md":
                entry["status"] = "DOWNLOAD_ONLY"

    assert fixture.run(plan=fixture.rewritten_plan(flip)) == 2
    assert "stale" in capsys.readouterr().err
    assert not fixture.database.exists() or fixture.courses() == []


def test_the_cli_refuses_to_add_material_to_a_published_course(tmp_path, capsys) -> None:
    """A published course is a reviewed release; new material is a new revision, not an import."""
    fixture = library(tmp_path)
    assert fixture.run() == 0

    connection = sqlite3.connect(fixture.database)
    try:
        connection.execute("UPDATE courses SET publication_status='published'")
        connection.commit()
    finally:
        connection.close()

    assert fixture.run() == 2
    assert "published" in capsys.readouterr().err


@pytest.mark.parametrize("relative", ["01_course/notes.md"])
def test_the_report_names_the_files_it_acted_on(tmp_path, relative: str) -> None:
    """A batch is judged from its report, so the report has to carry the per-file outcome."""
    fixture = library(tmp_path)
    assert fixture.run() == 0
    report = json.loads(fixture.report.read_text(encoding="utf-8"))
    outcomes = {item["relativePath"]: item for item in report["ingestion"]["outcomes"]}
    assert relative in outcomes
    assert outcomes[relative]["status"] == "INDEXED"
    assert outcomes[relative]["chunks"] > 0
