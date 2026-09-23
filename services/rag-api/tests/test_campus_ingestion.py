"""Task C3: what campus material may become a course, and how it is ingested without publishing it.

Two kinds of test live here, and they guard different things.

The **policy** tests are pure: they pin the three decisions and, more importantly, the false
positives a substring rule produces on the real inventory (`example` contains `exam`, so a naive
rule blocks `lec04-26-CSS-simple-example.html`; a blanket `solution` rule blocks every
`Tutorial_N_solutions.pdf`, which is the teaching material the library exists to hold).

The **ingestion** tests drive the real `IngestionService` against real files on disk in a
temporary database: documents, chunks, the duplicate rule, the unparseable case, a source file that
changed after the scan, and the promise that nothing is published.
"""

from __future__ import annotations

import pathlib
import sqlite3
from contextlib import ExitStack

import pytest

from app.campus_ingestion import (
    BLOCKED,
    DOWNLOAD_ONLY,
    INGESTABLE,
    REVIEW_NEEDS_OWNER,
    REVIEW_NEEDS_RIGHTS,
    REVIEW_NOT_FOR_PUBLICATION,
    CampusMaterialRepository,
    CoursePlan,
    InventoryRow,
    campus_course_id,
    decide,
    first_course_with_material,
    ingest_course,
    load_inventory,
    plan,
    review_list_rows,
)
from app.config import Settings
from app.db import Database
from app.errors import ApiError
from app.models import CourseCreate, PublicationStatus
from app.rag.embeddings import DeterministicEmbeddingProvider
from app.services.ingestion import IngestionService

CITYU = "https://canvas.cityu.edu.hk"

_STACKS: list[ExitStack] = []


def row(**overrides) -> InventoryRow:
    values = {
        "source_root": "D:\\Canvas",
        "institution_origin": CITYU,
        "course_id": "359",
        "course_code": "CS2611",
        "course_name": "Seminars on Contemporary Technology I",
        "term": "Semester B 2024_25",
        "summary_category": "",
        "relative_path": "Semester B 2024_25\\CS2611\\lecture.pdf",
        "filename": "lecture.pdf",
        "bytes_disk": 1024,
        "sha256": "a" * 64,
        "mime_guess": "application/pdf",
        "parse_class": "PARSEABLE",
        "classification": "ACADEMIC_TEACHING",
        "classification_reason": "academic",
        # The scanner's own token for "matches its manifest entry on size and hash". The first
        # version of the policy expected `OK`, which the scanner never writes, and every file in
        # the inventory was blocked until the planner was actually run on it.
        "disk_status": "PRESENT",
        "publication_basis": "OWNER_PLATFORM_IMPORT_INTENT_RIGHTS_UNVERIFIED",
        "review_status": "NEEDS_REVIEW",
    }
    values.update(overrides)
    return InventoryRow(**values)  # type: ignore[arg-type]


# ------------------------------------------------------------------------------------ the policy
def test_academic_parseable_material_is_ingestable_but_never_public() -> None:
    decision = decide(row())
    assert decision.status == INGESTABLE
    # Rights are unverified for every file in this inventory, so the material keeps its review
    # status and cannot be published by this path.
    assert decision.review_status == REVIEW_NEEDS_RIGHTS


def test_example_is_not_an_exam_and_tutorial_solutions_are_teaching_material() -> None:
    """The false positives a substring rule produces on the real inventory.

    `example` contains `exam`, and every `Tutorial_N_solutions.pdf` contains `solution`; a substring
    rule blocks both, which would block the teaching material the library exists to hold.
    """
    for filename in (
        "lec04-26-CSS-simple-example.html",
        "format example.pdf",
        "example_edges.csv",
        "P06_UsingFinal.java",
        "MA1200 Chapter 3 Polynomials_Solutions.pdf",
        "CS3334 Tutorial 1 Solutions.docx",
        "tutorial_09_solutions..pdf",
        "tutorial_2_slidesSolution.pdf",
    ):
        decision = decide(row(filename=filename))
        assert decision.status == INGESTABLE, f"{filename} must not be blocked: {decision.reason}"


def test_the_assessment_rule_flags_rather_than_misses_and_says_so() -> None:
    """The deliberate bias: a flagged slide costs the owner one line, a missed final paper does not.

    `Topic03_P12_final_field.pptx` is a Java-keyword slide, not assessment material, and it is
    flagged. That is the accepted cost of catching `Final2023.pdf` and
    `cs3334_final_problem_set.pdf`, which a word-boundary rule misses (a digit or `_` is a word
    character). Nothing is published on the strength of this decision either way: a flagged file is
    blocked from ingestion and listed for the owner, exactly like the files this rule is for.
    """
    flagged = decide(row(filename="Topic03_P12_final_field.pptx"))
    assert flagged.status == BLOCKED
    assert flagged.review_status == REVIEW_NEEDS_OWNER
    assert "ASSESSMENT" in flagged.reason


def test_real_assessment_material_is_blocked_and_needs_a_decision() -> None:
    for filename in (
        "finalexam_coding.ipynb",
        "Final2023.pdf",
        "Final2023_Solutions.pdf",
        "CS2204-FinalExam.pdf",
        "CS2204-Quiz.pdf",
        "Midterm-1.pdf",
        "Midterm-marking-1.pdf",
        "midterm_2024A_sol.pdf",
        "cs3402_final mock exam_2026.pdf",
        "knowledge_list_updated_final_exam.docx",
        "202402_MA1201 Exam paper.pdf",
        "cs3334_final_problem_set.pdf",
        "Equations for PHY1201 exam-V2021.pdf",
        "思想道德与法治 期末回顾.pptx",
        "MA2185 答案.pdf",
    ):
        decision = decide(row(filename=filename))
        assert decision.status == BLOCKED, f"{filename} should not be ingested"
        assert decision.review_status == REVIEW_NEEDS_OWNER
        assert "ASSESSMENT" in decision.reason


def test_a_copy_from_a_shadow_library_is_blocked_rather_than_imported() -> None:
    """Found by running the planner on the real inventory: a book whose name names its source.

    Course 628's second file is a 1 MB book ending in `(z-library.sk, 1lib.sk, z-lib.sk)`. Its
    rights are not merely unverified — the file name states where the copy came from — so it is
    blocked and listed rather than ingested into a draft.
    """
    for filename in (
        "社会学方法的准则 (z-library.sk, 1lib.sk, z-lib.sk).pdf",
        "Some Book (libgen.is).pdf",
        "paper (sci-hub.se).pdf",
        "电子书下载-某书.pdf",
    ):
        decision = decide(row(filename=filename))
        assert decision.status == BLOCKED, filename
        assert "UNLICENSED_SOURCE" in decision.reason
        assert decision.review_status == REVIEW_NEEDS_OWNER

    # A legitimate copy of the same work is not caught by the rule.
    assert decide(row(filename="社会学方法的准则（商务印书馆）.pdf")).status == INGESTABLE


def test_personal_information_and_training_are_blocked_with_the_right_review_status() -> None:
    personal = decide(row(classification="PERSONAL_OR_RESTRICTED", filename="grades.xlsx"))
    assert personal.status == BLOCKED
    assert personal.review_status == REVIEW_NOT_FOR_PUBLICATION

    for classification in ("INFORMATION", "TRAINING"):
        decision = decide(row(classification=classification, filename="notice.pdf"))
        assert decision.status == BLOCKED
        assert decision.review_status == REVIEW_NOT_FOR_PUBLICATION

    unknown = decide(row(classification="UNKNOWN_REVIEW"))
    assert unknown.status == BLOCKED
    assert unknown.review_status == REVIEW_NEEDS_OWNER


def test_a_source_the_scan_could_not_verify_is_never_ingested() -> None:
    for status in ("MISSING_ON_DISK", "SIZE_MISMATCH", "NOT_IN_MANIFEST"):
        decision = decide(row(disk_status=status))
        assert decision.status == BLOCKED
        assert decision.review_status == REVIEW_NEEDS_OWNER
        assert status in decision.reason

    # The manifest file itself is a source record rather than course material, and is not a
    # course file in the first place; `plan()` drops rows without a course id.
    assert decide(row(disk_status="SOURCE_MANIFEST")).status == BLOCKED


def test_unparseable_academic_material_is_stored_but_not_learnable() -> None:
    video = decide(row(filename="lecture.mp4", parse_class="DOWNLOAD_ONLY"))
    assert video.status == DOWNLOAD_ONLY
    assert "never counted as learnable" in video.reason

    image = decide(row(filename="whiteboard.jpg", parse_class="UNKNOWN"))
    assert image.status == DOWNLOAD_ONLY


def test_the_plan_groups_by_offering_and_the_first_course_is_the_smallest(tmp_path) -> None:
    rows = [
        row(course_id="319", relative_path="a.ipynb", filename="finalexam_coding.ipynb"),
        row(course_id="359", relative_path="b.pdf", filename="dcc.pdf"),
        row(course_id="359", relative_path="c.pdf", filename="dns-maude.pdf"),
        row(course_id="548", relative_path="d.pdf", filename="notes.pdf"),
    ]
    plans = plan(rows)

    assert set(plans) == {(CITYU, "319"), (CITYU, "359"), (CITYU, "548")}
    # Course 319's single file is a final exam, so it has nothing to ingest and is not a candidate.
    assert plans[(CITYU, "319")].ingestable == []
    chosen = first_course_with_material(plans)
    # 548 has one ingestable file and 359 has two, so the smallest offering with material wins.
    assert chosen is not None and chosen.course_id == "548"
    assert len(chosen.ingestable) == 1
    assert plans[(CITYU, "359")].counts() == {INGESTABLE: 2, DOWNLOAD_ONLY: 0, BLOCKED: 0}


def test_a_manifest_row_without_a_course_is_not_course_material() -> None:
    plans = plan([row(course_id="", filename="_download_manifest.csv")])
    assert plans == {}


def test_load_inventory_reads_the_committed_columns(tmp_path) -> None:
    path = tmp_path / "inventory.csv"
    path.write_text(
        "source_root,institution_origin,course_id,course_code,course_name,term,summary_category,"
        "relative_path,filename,bytes_disk,bytes_manifest,sha256,mime_guess,parse_class,"
        "classification,classification_reason,duplicate_group,same_name_group,manifest_status,"
        "disk_status,publication_basis,review_status,notes\n"
        f"D:\\Canvas,{CITYU},359,CS2611,Seminars,B 2024_25,,b.pdf,dcc.pdf,716908,,{'b' * 64},"
        "application/pdf,PARSEABLE,ACADEMIC_TEACHING,academic,,,OK,OK,"
        "OWNER_PLATFORM_IMPORT_INTENT_RIGHTS_UNVERIFIED,NEEDS_REVIEW,\n",
        encoding="utf-8",
        newline="",
    )
    (loaded,) = load_inventory(path)
    assert loaded.course_id == "359"
    assert loaded.bytes_disk == 716908
    assert loaded.source_path == pathlib.Path("D:\\Canvas") / "b.pdf"
    assert loaded.key == (CITYU, "359", "b.pdf")


def test_the_campus_course_id_comes_from_the_external_key_only() -> None:
    first = campus_course_id(CITYU, "359")
    assert first == campus_course_id(CITYU, "359"), "stable"
    assert first != campus_course_id(CITYU, "360")
    assert first != campus_course_id("https://cityu-dg.instructure.com", "359")
    assert first.startswith("campus-")
    assert len(first) <= 50


# ---------------------------------------------------------------------------------- ingestion
def service(
    tmp_path: pathlib.Path, *, max_upload_bytes: int = 20 * 1024 * 1024
) -> tuple[IngestionService, Database, sqlite3.Connection]:
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        chunk_size=200,
        chunk_overlap=20,
        app_env="test",
        v3_enabled=True,
        rag_provider_mode="deterministic",
        ui_web_dir=tmp_path / "no-web-build",
        max_upload_bytes=max_upload_bytes,
    )
    database = Database(settings)
    database.initialize()
    stack = ExitStack()
    _STACKS.append(stack)
    connection = stack.enter_context(database.connect())
    connection.isolation_level = None
    return (
        IngestionService(database, settings, DeterministicEmbeddingProvider()),
        database,
        connection,
    )


def real_row(root: pathlib.Path, name: str, content: bytes, **overrides) -> InventoryRow:
    """An inventory row whose file really exists, so hash and size checks are exercised."""
    import hashlib

    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return row(
        source_root=str(root),
        relative_path=name,
        filename=pathlib.PurePosixPath(name).name,
        bytes_disk=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        **overrides,
    )


def plan_for(rows: list[InventoryRow]) -> CoursePlan:
    (course_plan,) = plan(rows).values()
    return course_plan


MARKDOWN = "# Clustering\n\nDBSCAN groups points by density and marks outliers as noise.\n"


def campus_course(ingestor: IngestionService, target: str) -> None:
    """Create the campus course the way the CLI does: administrator-owned and private.

    Not `pending`: migration 019 freezes a course that is pending or published, so a course under
    review cannot receive the documents an import writes. Campus material is private until a
    reviewer publishes it.
    """
    ingestor.create_course(
        CourseCreate(id=target, name=f"Campus {target}", description="Campus material"),
        is_admin=True,
        publication_status=PublicationStatus.PRIVATE,
    )


def unpublished(connection: sqlite3.Connection, target: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT course_type, visibility, publication_status, published_at FROM courses WHERE id=?",
        (target,),
    ).fetchone()
    assert row is not None
    return row


def test_ingesting_one_course_creates_real_documents_and_chunks(tmp_path) -> None:
    ingestor, _database, connection = service(tmp_path)
    source = tmp_path / "canvas"
    rows = [
        real_row(source, "b.pdf".replace(".pdf", ".md"), MARKDOWN.encode()),
        real_row(source, "notes.txt", b"Second file\n\nwith text.\n"),
    ]
    course_plan = plan_for(rows)
    target = campus_course_id(CITYU, course_plan.course_id)
    campus_course(ingestor, target)
    repository = CampusMaterialRepository(connection)

    report = ingest_course(
        course_plan, service=ingestor, repository=repository, target_course_id=target
    )

    assert report.indexed == 2
    assert report.chunks >= 2
    documents = connection.execute(
        "SELECT filename, chunk_count, course_id FROM documents ORDER BY filename"
    ).fetchall()
    assert [item["filename"] for item in documents] == ["b.md", "notes.txt"]
    assert all(int(item["chunk_count"]) > 0 for item in documents)
    assert {item["course_id"] for item in documents} == {target}

    records = connection.execute(
        "SELECT decision, review_status, document_id, usage_rights, publication_basis "
        "FROM campus_material_records ORDER BY relative_path"
    ).fetchall()
    assert len(records) == 2
    assert {item["decision"] for item in records} == {INGESTABLE}
    assert {item["review_status"] for item in records} == {REVIEW_NEEDS_RIGHTS}
    assert {item["usage_rights"] for item in records} == {"UNVERIFIED"}
    assert all(item["document_id"] for item in records)


def test_ingesting_the_same_course_twice_does_not_duplicate_documents(tmp_path) -> None:
    ingestor, _database, connection = service(tmp_path)
    source = tmp_path / "canvas"
    rows = [real_row(source, "notes.md", MARKDOWN.encode())]
    course_plan = plan_for(rows)
    target = campus_course_id(CITYU, course_plan.course_id)
    campus_course(ingestor, target)
    repository = CampusMaterialRepository(connection)

    first = ingest_course(
        course_plan, service=ingestor, repository=repository, target_course_id=target
    )
    second = ingest_course(
        course_plan, service=ingestor, repository=repository, target_course_id=target
    )

    assert first.indexed == 1
    assert second.outcomes[0].status == "SKIPPED_IDENTICAL"
    assert connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
    # The record still points at the one document that holds this content.
    stored = connection.execute("SELECT document_id FROM campus_material_records").fetchone()
    assert stored["document_id"] == second.outcomes[0].document_id


def test_a_file_that_changed_after_the_scan_is_blocked_not_ingested(tmp_path) -> None:
    ingestor, _database, connection = service(tmp_path)
    source = tmp_path / "canvas"
    existing = real_row(source, "notes.md", MARKDOWN.encode())
    changed = InventoryRow(**{**existing.__dict__, "sha256": "c" * 64, "bytes_disk": 999_999})
    course_plan = plan_for([changed])
    campus_course(ingestor, campus_course_id(CITYU, "359"))

    report = ingest_course(
        course_plan,
        service=ingestor,
        repository=CampusMaterialRepository(connection),
        target_course_id=campus_course_id(CITYU, "359"),
    )

    assert report.counts() == {BLOCKED: 1}
    assert "SOURCE_CHANGED" in report.outcomes[0].reason
    assert connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
    assert (
        connection.execute("SELECT review_status FROM campus_material_records").fetchone()[
            "review_status"
        ]
        == REVIEW_NEEDS_OWNER
    )


def test_a_missing_source_file_is_blocked(tmp_path) -> None:
    ingestor, _database, connection = service(tmp_path)
    missing = row(relative_path="gone.pdf", filename="gone.pdf")
    campus_course(ingestor, campus_course_id(CITYU, "359"))

    report = ingest_course(
        plan_for([missing]),
        service=ingestor,
        repository=CampusMaterialRepository(connection),
        target_course_id=campus_course_id(CITYU, "359"),
    )

    assert report.counts() == {BLOCKED: 1}
    assert report.outcomes[0].reason == "SOURCE_FILE_MISSING"


def test_a_video_is_recorded_as_download_only_and_never_indexed(tmp_path) -> None:
    ingestor, _database, connection = service(tmp_path)
    source = tmp_path / "canvas"
    video = real_row(
        source,
        "lecture.mp4",
        b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64,
        parse_class="DOWNLOAD_ONLY",
        mime_guess="video/mp4",
    )
    campus_course(ingestor, campus_course_id(CITYU, "214"))

    report = ingest_course(
        plan_for([video]),
        service=ingestor,
        repository=CampusMaterialRepository(connection),
        target_course_id=campus_course_id(CITYU, "214"),
    )

    assert report.counts() == {DOWNLOAD_ONLY: 1}
    assert report.indexed == 0
    assert connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
    stored = connection.execute(
        "SELECT decision, document_id FROM campus_material_records"
    ).fetchone()
    assert stored["decision"] == DOWNLOAD_ONLY and stored["document_id"] is None


def test_a_file_whose_format_has_no_loader_is_download_only_even_when_parseable(tmp_path) -> None:
    ingestor, _database, connection = service(tmp_path)
    source = tmp_path / "canvas"
    # `.csv` is accepted by the upload validator but has no text loader, so the ingestion layer
    # marks the document ready with zero chunks; the campus path must not call that learnable.
    data = real_row(source, "dataset.csv", b"x,y\n1,2\n")
    campus_course(ingestor, campus_course_id(CITYU, "359"))

    report = ingest_course(
        plan_for([data]),
        service=ingestor,
        repository=CampusMaterialRepository(connection),
        target_course_id=campus_course_id(CITYU, "359"),
    )

    assert report.counts() == {DOWNLOAD_ONLY: 1}
    assert report.indexed == 0
    assert report.chunks == 0


def test_a_file_over_the_ingestion_limit_is_stored_not_failed(tmp_path) -> None:
    """Found by running a batch of six offerings: two large CS4182 lecture PDFs were recorded as
    FAILED, which reads as a broken import.

    A file too large for the configured limit is not a failure — the same rule the Canvas worker
    applies to `TOO_LARGE` — and 42 files in this plan are over it. The original stays where it is,
    the material becomes stored-but-not-learnable, and it never counts as coverage.
    """
    ingestor, _database, connection = service(tmp_path, max_upload_bytes=1024)
    source = tmp_path / "canvas"
    big = real_row(source, "lecture.pdf", b"%PDF-1.4\n" + b"x" * 4096)
    campus_course(ingestor, campus_course_id(CITYU, "359"))

    report = ingest_course(
        plan_for([big]),
        service=ingestor,
        repository=CampusMaterialRepository(connection),
        target_course_id=campus_course_id(CITYU, "359"),
    )

    assert report.counts() == {DOWNLOAD_ONLY: 1}, report.as_dict()
    assert report.indexed == 0
    assert connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
    stored = connection.execute(
        "SELECT decision, decision_reason, review_status FROM campus_material_records"
    ).fetchone()
    # The record says what happened, not what the plan hoped.
    assert stored["decision"] == DOWNLOAD_ONLY
    assert "ingestion limit" in stored["decision_reason"]
    assert stored["review_status"] == REVIEW_NEEDS_RIGHTS


def test_an_empty_file_is_download_only_rather_than_a_failure(tmp_path) -> None:
    ingestor, _database, connection = service(tmp_path)
    source = tmp_path / "canvas"
    empty = real_row(source, "nothing.md", b"")
    campus_course(ingestor, campus_course_id(CITYU, "359"))

    report = ingest_course(
        plan_for([empty]),
        service=ingestor,
        repository=CampusMaterialRepository(connection),
        target_course_id=campus_course_id(CITYU, "359"),
    )

    assert report.counts() == {DOWNLOAD_ONLY: 1}
    stored = connection.execute("SELECT decision FROM campus_material_records").fetchone()
    assert stored["decision"] == DOWNLOAD_ONLY


def test_a_refusal_the_file_is_responsible_for_is_download_only(tmp_path) -> None:
    """`INVALID_MEDIA_TYPE` is the file's own problem, so it joins the stored-but-unreadable set.

    This pins the allow-list itself. Without it, the only two codes with their own tests are
    `FILE_TOO_LARGE` and `EMPTY_FILE`, and the generic file-scoped branch could rot unnoticed.
    """
    ingestor, _database, connection = service(tmp_path)
    source = tmp_path / "canvas"
    item = real_row(source, "notes.md", MARKDOWN.encode())
    campus_course(ingestor, campus_course_id(CITYU, "359"))

    class WrongType:
        settings = ingestor.settings

        def queue_document(self, **kwargs):
            raise ApiError(415, "INVALID_MEDIA_TYPE", "text/markdown is not accepted here")

    report = ingest_course(
        plan_for([item]),
        service=WrongType(),  # type: ignore[arg-type]
        repository=CampusMaterialRepository(connection),
        target_course_id=campus_course_id(CITYU, "359"),
    )

    assert report.counts() == {DOWNLOAD_ONLY: 1}, report.as_dict()
    assert "INVALID_MEDIA_TYPE" in report.outcomes[0].reason


def test_a_server_side_failure_is_still_a_failure(tmp_path) -> None:
    """The negative control: the mapping must not turn every refusal into "stored, fine".

    If it did, a defect on our own side would look like unreadable material and nobody would
    investigate it.
    """
    ingestor, _database, connection = service(tmp_path)
    source = tmp_path / "canvas"
    item = real_row(source, "notes.md", MARKDOWN.encode())
    campus_course(ingestor, campus_course_id(CITYU, "359"))

    class Exploding:
        """Stands in for the ingestion layer failing on its own side, not the file's."""

        settings = ingestor.settings

        def queue_document(self, **kwargs):
            raise ApiError(500, "INTERNAL", "the ingestion layer broke")

    report = ingest_course(
        plan_for([item]),
        service=Exploding(),  # type: ignore[arg-type]
        repository=CampusMaterialRepository(connection),
        target_course_id=campus_course_id(CITYU, "359"),
    )

    assert report.counts() == {"FAILED": 1}, report.as_dict()
    assert "INTERNAL" in report.outcomes[0].reason


def test_a_course_level_quota_refusal_blocks_the_file_visibly(tmp_path) -> None:
    """A quota is not this file's fault, so it must not be downgraded and hidden per file."""
    ingestor, _database, connection = service(tmp_path)
    source = tmp_path / "canvas"
    item = real_row(source, "notes.md", MARKDOWN.encode())
    campus_course(ingestor, campus_course_id(CITYU, "359"))

    class Quota:
        settings = ingestor.settings

        def queue_document(self, **kwargs):
            raise ApiError(429, "COURSE_FILE_QUOTA_EXCEEDED", "quota reached")

    report = ingest_course(
        plan_for([item]),
        service=Quota(),  # type: ignore[arg-type]
        repository=CampusMaterialRepository(connection),
        target_course_id=campus_course_id(CITYU, "359"),
    )

    assert report.counts() == {BLOCKED: 1}
    stored = connection.execute(
        "SELECT decision, review_status FROM campus_material_records"
    ).fetchone()
    assert stored["decision"] == BLOCKED
    assert stored["review_status"] == REVIEW_NEEDS_OWNER


def test_the_review_list_contains_the_blocked_files_and_no_personal_names(tmp_path) -> None:
    ingestor, _database, connection = service(tmp_path)
    source = tmp_path / "canvas"
    rows = [
        real_row(source, "notes.md", MARKDOWN.encode()),
        real_row(source, "Final2023.pdf", b"%PDF-1.4\nfake\n"),
        real_row(source, "grades.xlsx", b"PK\x03\x04fake", classification="PERSONAL_OR_RESTRICTED"),
    ]
    repository = CampusMaterialRepository(connection)
    campus_course(ingestor, campus_course_id(CITYU, "359"))
    ingest_course(
        plan_for(rows),
        service=ingestor,
        repository=repository,
        target_course_id=campus_course_id(CITYU, "359"),
    )

    listed = review_list_rows(repository.review_list())

    # Everything awaiting a human decision is on the list: the blocked exam and the ingested
    # teaching material, whose rights nobody has verified yet.
    assert {item["filename"] for item in listed} == {"Final2023.pdf", "notes.md"}
    by_name = {item["filename"]: item for item in listed}
    assert by_name["Final2023.pdf"]["review_status"] == REVIEW_NEEDS_OWNER
    assert by_name["notes.md"]["review_status"] == REVIEW_NEEDS_RIGHTS
    assert all(item["publication_basis"].endswith("RIGHTS_UNVERIFIED") for item in listed)

    # The personal file is decided, not pending: it is recorded and kept off the owner's list, so
    # that the list stays short enough to act on.
    excluded = review_list_rows(repository.not_for_publication())
    assert [item["filename"] for item in excluded] == ["grades.xlsx"]
    assert {item["review_status"] for item in excluded} == {REVIEW_NOT_FOR_PUBLICATION}

    # The list carries only source facts and rights metadata: no credential, no owner identity.
    dumped = str(listed) + str(excluded)
    assert "grades.xlsx" in dumped
    for forbidden in ("access_token", "Bearer", "owner_user_id", "canvas_user_id"):
        assert forbidden not in dumped


def test_a_campus_course_can_be_created_unpublished_and_stays_invisible_to_students(
    tmp_path,
) -> None:
    """The service change that makes 'ingest without publishing' possible in one transaction."""
    ingestor, _database, connection = service(tmp_path)
    ingestor.create_course(
        CourseCreate(id="campus-359", name="CS2611 Seminars", description="Campus import"),
        is_admin=True,
        publication_status=PublicationStatus.PRIVATE,
    )

    stored = connection.execute(
        "SELECT course_type, visibility, publication_status, published_at FROM courses WHERE id=?",
        ("campus-359",),
    ).fetchone()
    assert stored["course_type"] == "official"
    assert stored["visibility"] == "private"
    assert stored["publication_status"] == "private"
    assert stored["published_at"] is None
    # Nothing is on a review queue and no snapshot exists: this course has not requested anything.
    assert connection.execute("SELECT COUNT(*) FROM course_publication_requests").fetchone()[0] == 0

    # The default for an administrator is unchanged: without the argument, a course is published.
    ingestor.create_course(CourseCreate(id="official-1", name="Official"), is_admin=True)
    default = connection.execute(
        "SELECT visibility, publication_status FROM courses WHERE id=?", ("official-1",)
    ).fetchone()
    assert (default["visibility"], default["publication_status"]) == ("public", "published")


def test_a_course_under_review_is_frozen_which_is_why_campus_material_is_private(tmp_path) -> None:
    """The trap this round hit, pinned so it cannot come back.

    Creating the campus course as `pending` looked like "awaiting review", but migration 019 makes
    that state a frozen release: the import's own document insert aborts with
    "Course content is locked by publication review". The private state is the one that is neither
    public nor frozen.
    """
    ingestor, _database, connection = service(tmp_path)
    ingestor.create_course(
        CourseCreate(id="frozen-1", name="Frozen", description="under review"),
        is_admin=True,
        publication_status=PublicationStatus.PENDING,
    )
    with pytest.raises(sqlite3.IntegrityError) as raised:
        ingestor.queue_document(
            course_id="frozen-1",
            filename="notes.md",
            media_type="text/markdown",
            content=MARKDOWN.encode(),
            is_admin=True,
        )
    assert "locked by publication review" in str(raised.value)

    ingestor.create_course(
        CourseCreate(id="writable-1", name="Writable", description="private"),
        is_admin=True,
        publication_status=PublicationStatus.PRIVATE,
    )
    accepted = ingestor.queue_document(
        course_id="writable-1",
        filename="notes.md",
        media_type="text/markdown",
        content=MARKDOWN.encode(),
        is_admin=True,
    )
    ingestor.process_document(accepted.document.id, accepted.job.id)
    assert ingestor.get_document(accepted.document.id).chunk_count > 0


def test_a_student_cannot_use_the_publication_override_to_publish(tmp_path) -> None:
    ingestor, _database, _connection = service(tmp_path)
    with pytest.raises(ApiError) as raised:
        ingestor.create_course(
            CourseCreate(id="mine", name="Mine"),
            owner_user_id="user-1",
            is_admin=False,
            publication_status=PublicationStatus.PUBLISHED,
        )
    assert raised.value.code == "PUBLICATION_NOT_ALLOWED"

    # A private request is the student's normal path and still works.
    course = ingestor.create_course(
        CourseCreate(id="mine", name="Mine"),
        owner_user_id="user-1",
        is_admin=False,
        publication_status=PublicationStatus.PRIVATE,
    )
    assert course.publication_status == PublicationStatus.PRIVATE
    assert course.visibility == "private"
