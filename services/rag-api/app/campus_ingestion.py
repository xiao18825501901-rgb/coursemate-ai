"""Task C3: decide what campus material may become a course, and ingest it without publishing it.

The inventory (`docs/coursejesus/LOCAL_CAMPUS_INVENTORY.csv`, produced by
`scripts/scan_campus_inventory.py`) is a **review work list**, not a rights decision: every one of
its 1919 real files is recorded with `review_status = NEEDS_REVIEW` and
`publication_basis = OWNER_PLATFORM_IMPORT_INTENT_RIGHTS_UNVERIFIED`. This module turns that list
into three decisions per file, and nothing else:

* `INGESTABLE` — academic teaching material that is parseable, goes into the campus course as a
  **non-public draft** through the real `IngestionService`;
* `DOWNLOAD_ONLY` — academic material whose format no loader can read (video, archives, plain
  images). It is recorded and counted as *stored*, never as learnable material, exactly as the
  Canvas worker treats an unparseable download;
* `BLOCKED` — anything whose classification, missing source or assessment character means it must
  not enter the library at all. Blocking one file never blocks the others, and every blocked file
  appears on the consolidated review list the owner is asked to decide once
  (`docs/coursejesus/CAMPUS_RIGHTS_REVIEW_LIST.csv`).

Two rules are load-bearing and are implemented as word-boundary matches rather than substrings,
because the inventory shows what a substring rule does: `example` contains `exam`, so a substring
rule blocks `lec04-26-CSS-simple-example.html` and `format example.pdf`, and a blanket
`solution` rule blocks `MA1200 Chapter 3 ..._Solutions.pdf` and every `Tutorial_N_solutions.pdf` —
which are the teaching material the library exists to hold. The rule therefore blocks a narrow,
high-confidence set (a final paper, a midterm, a marking scheme, an explicit exam or quiz, a Chinese
exam-term filename) and leaves everything else as `NEEDS_REVIEW` for the human, who decides rights
anyway.

Nothing here publishes. A campus course is created in a non-public state, and its material keeps
`review_status = NEEDS_REVIEW` until a person publishes it; `ingest_course` cannot do that, on
purpose.
"""

from __future__ import annotations

import csv
import hashlib
import pathlib
import re
import sqlite3
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.errors import ApiError
from app.learning.uploads import MEDIA_TYPES
from app.services.ingestion import IngestionService

INGESTABLE = "INGESTABLE"
DOWNLOAD_ONLY = "DOWNLOAD_ONLY"
BLOCKED = "BLOCKED"

MATERIAL_STATUSES = (INGESTABLE, DOWNLOAD_ONLY, BLOCKED)

REVIEW_NEEDS_OWNER = "BLOCKED_NEEDS_OWNER_DECISION"
REVIEW_NEEDS_RIGHTS = "NEEDS_REVIEW"
REVIEW_NOT_FOR_PUBLICATION = "NOT_FOR_PUBLICATION"

# A narrow, high-confidence assessment rule. See the module docstring for why it is not a
# substring search and why tutorial solutions are deliberately not in it.
#
# The boundary is "no adjacent letter" rather than a word boundary, because real filenames join
# words with digits and underscores: `\bfinal\b` misses both `Final2023.pdf` and
# `cs3334_final_problem_set.pdf` (a digit or `_` is a word character), and those are exactly the
# papers this rule exists to catch. `example` still survives, because the letters after `exam` are
# what disqualify it.
ASSESSMENT_TOKENS = re.compile(
    r"(?<![A-Za-z])(finals?|midterms?|exams?|quiz|quizzes|marking)(?![A-Za-z])"
    r"|final[\s_-]*exam"
    r"|期末考试|期末试卷|期末|试卷|期中|答案|考试",
    re.IGNORECASE,
)


def _is_assessment_material(filename: str) -> bool:
    return bool(ASSESSMENT_TOKENS.search(filename))


# A copy whose filename names a shadow-library service is not "rights unclear": the record itself
# says where the copy came from. The campus scan found exactly this — a 1 MB book whose name ends
# with `(z-library.sk, 1lib.sk, z-lib.sk)` — and a policy that ingested it into a draft course
# would be building a library on a copy nobody can license.
UNLICENSED_SOURCE_MARKERS = re.compile(
    r"z-?library|z-?lib|1lib|libgen|sci-?hub|annas?-archive|library\.lol|bookfi|"
    r"电子书下载|免费下载",
    re.IGNORECASE,
)


def _is_unlicensed_copy(filename: str) -> bool:
    return bool(UNLICENSED_SOURCE_MARKERS.search(filename))


# The scan's own vocabulary (`scripts/scan_campus_inventory.py`), so this module never invents a
# token it hoped the scanner produced. `PRESENT` is a file that matched its manifest entry on both
# size and hash; `SOURCE_MANIFEST` is the manifest file itself; the rest are the ways a source can
# fail to match the record of it.
VERIFIED_ON_DISK = ("PRESENT",)
SOURCE_RECORD = ("SOURCE_MANIFEST",)
UNVERIFIED_ON_DISK = ("MISSING_ON_DISK", "SIZE_MISMATCH", "NOT_IN_MANIFEST")


@dataclass(frozen=True)
class InventoryRow:
    """One inventory line, as the scan wrote it."""

    source_root: str
    institution_origin: str
    course_id: str
    course_code: str
    course_name: str
    term: str
    summary_category: str
    relative_path: str
    filename: str
    bytes_disk: int
    sha256: str
    mime_guess: str
    parse_class: str
    classification: str
    classification_reason: str
    disk_status: str
    publication_basis: str
    review_status: str
    duplicate_group: str = ""

    @property
    def source_path(self) -> pathlib.Path:
        return pathlib.Path(self.source_root) / self.relative_path

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.institution_origin, self.course_id, self.relative_path)

    @property
    def offering(self) -> tuple[str, str]:
        return (self.institution_origin, self.course_id)


@dataclass(frozen=True)
class MaterialDecision:
    status: str
    reason: str
    review_status: str

    def as_dict(self) -> dict[str, str]:
        return {"status": self.status, "reason": self.reason, "review_status": self.review_status}


@dataclass
class CoursePlan:
    """One Canvas offering's material, decided file by file."""

    institution_origin: str
    course_id: str
    course_code: str
    course_name: str
    term: str
    decisions: dict[tuple[str, str, str], MaterialDecision] = field(default_factory=dict)
    rows: list[InventoryRow] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, str]:
        return (self.institution_origin, self.course_id)

    def counts(self) -> dict[str, int]:
        counts = {status: 0 for status in MATERIAL_STATUSES}
        for decision in self.decisions.values():
            counts[decision.status] = counts.get(decision.status, 0) + 1
        return counts

    @property
    def ingestable(self) -> list[InventoryRow]:
        return [row for row in self.rows if self.decisions[row.key].status == INGESTABLE]

    def as_dict(self) -> dict[str, Any]:
        return {
            "institutionOrigin": self.institution_origin,
            "courseId": self.course_id,
            "courseCode": self.course_code,
            "courseName": self.course_name,
            "term": self.term,
            # The scan root this course's relative paths are relative to. Without it a plan cannot
            # be acted on, because the same relative path exists under both Canvas roots.
            "sourceRoot": self.rows[0].source_root if self.rows else "",
            "counts": self.counts(),
            "files": [
                {
                    "filename": row.filename,
                    "relativePath": row.relative_path,
                    "sha256": row.sha256,
                    "bytes": row.bytes_disk,
                    # The facts the decision was made from, so a later run re-derives the same
                    # decision from the record instead of trusting a status that may have been
                    # written by an older policy.
                    "classification": row.classification,
                    "parseClass": row.parse_class,
                    "diskStatus": row.disk_status,
                    "publicationBasis": row.publication_basis,
                    **self.decisions[row.key].as_dict(),
                }
                for row in self.rows
            ],
        }


# ---------------------------------------------------------------------------------- the policy
def decide(row: InventoryRow) -> MaterialDecision:
    """What may happen to one file. The order of the rules is the policy."""
    if row.disk_status not in VERIFIED_ON_DISK:
        # The scan records a file that no longer matches the manifest, or that the manifest never
        # listed; nothing may be ingested from a source we cannot re-verify.
        return MaterialDecision(BLOCKED, f"SOURCE_{row.disk_status}", REVIEW_NEEDS_OWNER)
    if row.classification == "PERSONAL_OR_RESTRICTED":
        return MaterialDecision(
            BLOCKED,
            "PERSONAL_OR_RESTRICTED: personal or restricted material never enters the library",
            REVIEW_NOT_FOR_PUBLICATION,
        )
    if row.classification in ("INFORMATION", "TRAINING"):
        # Announcements, scholarships and training material are not a campus course.
        return MaterialDecision(
            BLOCKED, f"NOT_COURSE_MATERIAL: {row.classification}", REVIEW_NOT_FOR_PUBLICATION
        )
    if row.classification == "UNKNOWN_REVIEW":
        return MaterialDecision(
            BLOCKED, "UNCLASSIFIED: the scan could not classify this file", REVIEW_NEEDS_OWNER
        )
    if _is_assessment_material(row.filename):
        return MaterialDecision(
            BLOCKED,
            "ASSESSMENT_MATERIAL: an exam, quiz or marking document needs the owner's decision",
            REVIEW_NEEDS_OWNER,
        )
    if _is_unlicensed_copy(row.filename):
        return MaterialDecision(
            BLOCKED,
            "UNLICENSED_SOURCE: the file name identifies a shadow-library copy, which cannot be "
            "the basis of a campus library",
            REVIEW_NEEDS_OWNER,
        )
    if row.parse_class == "PARSEABLE":
        return MaterialDecision(INGESTABLE, "academic teaching material", REVIEW_NEEDS_RIGHTS)
    if row.parse_class == "DOWNLOAD_ONLY":
        return MaterialDecision(
            DOWNLOAD_ONLY,
            "no loader can read this format: stored, never counted as learnable material",
            REVIEW_NEEDS_RIGHTS,
        )
    return MaterialDecision(
        DOWNLOAD_ONLY,
        "unknown format: stored, never counted as learnable material",
        REVIEW_NEEDS_RIGHTS,
    )


def load_inventory(path: pathlib.Path | str) -> list[InventoryRow]:
    rows: list[InventoryRow] = []
    with pathlib.Path(path).open(encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            rows.append(
                InventoryRow(
                    source_root=raw.get("source_root", ""),
                    institution_origin=raw.get("institution_origin", ""),
                    course_id=raw.get("course_id", ""),
                    course_code=raw.get("course_code", ""),
                    course_name=raw.get("course_name", ""),
                    term=raw.get("term", ""),
                    summary_category=raw.get("summary_category", ""),
                    relative_path=raw.get("relative_path", ""),
                    filename=raw.get("filename", ""),
                    bytes_disk=int(raw.get("bytes_disk") or 0),
                    sha256=raw.get("sha256", ""),
                    mime_guess=raw.get("mime_guess", ""),
                    parse_class=raw.get("parse_class", ""),
                    classification=raw.get("classification", ""),
                    classification_reason=raw.get("classification_reason", ""),
                    disk_status=raw.get("disk_status", ""),
                    publication_basis=raw.get("publication_basis", ""),
                    review_status=raw.get("review_status", ""),
                    duplicate_group=raw.get("duplicate_group", ""),
                )
            )
    return rows


def plan(rows: Iterable[InventoryRow]) -> dict[tuple[str, str], CoursePlan]:
    """Group the inventory by offering and decide every file."""
    plans: dict[tuple[str, str], CoursePlan] = {}
    for row in rows:
        if not row.course_id:
            # The manifests' own files and anything outside a course folder are source records,
            # not course material.
            continue
        offering = plans.setdefault(
            row.offering,
            CoursePlan(
                institution_origin=row.institution_origin,
                course_id=row.course_id,
                course_code=row.course_code,
                course_name=row.course_name,
                term=row.term,
            ),
        )
        offering.rows.append(row)
        offering.decisions[row.key] = decide(row)
    return plans


def first_course_with_material(plans: dict[tuple[str, str], CoursePlan]) -> CoursePlan | None:
    """The smallest offering that has material worth ingesting, for a first verification.

    Smallest *by ingestable count*, and ties are broken by course id so the choice is stable and
    reproducible rather than dependent on dictionary order.
    """
    candidates = [item for item in plans.values() if item.ingestable]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (len(item.ingestable), item.course_id))[0]


# --------------------------------------------------------------------------- material records
class CampusMaterialRepository:
    """Persistence for per-file campus material facts and their rights metadata."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._connection.row_factory = sqlite3.Row

    def upsert(
        self,
        row: InventoryRow,
        decision: MaterialDecision,
        *,
        target_course_id: str | None = None,
        document_id: str | None = None,
        license_note: str = "",
        source_notice: str = "",
    ) -> str:
        existing = self._connection.execute(
            "SELECT id FROM campus_material_records WHERE institution_origin=? AND "
            "canvas_course_id=? AND relative_path=?",
            (row.institution_origin, row.course_id, row.relative_path),
        ).fetchone()
        if existing is not None:
            self._connection.execute(
                "UPDATE campus_material_records SET sha256=?, bytes_disk=?, parse_class=?, "
                "classification=?, decision=?, decision_reason=?, publication_basis=?, "
                "review_status=?, target_course_id=COALESCE(?, target_course_id), "
                "document_id=COALESCE(?, document_id), license_note=?, source_notice=?, "
                "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (
                    row.sha256,
                    row.bytes_disk,
                    row.parse_class,
                    row.classification,
                    decision.status,
                    decision.reason,
                    row.publication_basis,
                    decision.review_status,
                    target_course_id,
                    document_id,
                    license_note,
                    source_notice,
                    existing["id"],
                ),
            )
            return str(existing["id"])
        record_id = uuid.uuid4().hex
        self._connection.execute(
            "INSERT INTO campus_material_records(id, institution_origin, canvas_course_id, "
            "course_code, source_root, relative_path, filename, sha256, bytes_disk, parse_class, "
            "classification, decision, decision_reason, usage_rights, license_note, source_notice, "
            "publication_basis, review_status, target_course_id, document_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                record_id,
                row.institution_origin,
                row.course_id,
                row.course_code,
                row.source_root,
                row.relative_path,
                row.filename,
                row.sha256,
                row.bytes_disk,
                row.parse_class,
                row.classification,
                decision.status,
                decision.reason,
                "UNVERIFIED",
                license_note,
                source_notice,
                row.publication_basis,
                decision.review_status,
                target_course_id,
                document_id,
            ),
        )
        return record_id

    def review_list(self) -> list[sqlite3.Row]:
        """The rows that need a *decision* from the owner.

        Personal and restricted material is deliberately absent: that decision has already been
        taken (never published), so asking about it again would turn a short list into a long one
        and hide the files that really are waiting on a person.
        """
        return self._connection.execute(
            "SELECT * FROM campus_material_records WHERE review_status != ? "
            "ORDER BY canvas_course_id, relative_path",
            (REVIEW_NOT_FOR_PUBLICATION,),
        ).fetchall()

    def not_for_publication(self) -> list[sqlite3.Row]:
        """The rows that are decided: personal, restricted, announcements and training material."""
        return self._connection.execute(
            "SELECT * FROM campus_material_records WHERE review_status = ? "
            "ORDER BY canvas_course_id, relative_path",
            (REVIEW_NOT_FOR_PUBLICATION,),
        ).fetchall()


# ------------------------------------------------------------------------------- the executor
@dataclass
class IngestionOutcome:
    relative_path: str
    status: str
    reason: str
    document_id: str = ""
    chunks: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "relativePath": self.relative_path,
            "status": self.status,
            "reason": self.reason,
            "documentId": self.document_id,
            "chunks": self.chunks,
        }


@dataclass
class CourseIngestionReport:
    course_id: str
    target_course_id: str
    outcomes: list[IngestionOutcome] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for outcome in self.outcomes:
            counts[outcome.status] = counts.get(outcome.status, 0) + 1
        return counts

    @property
    def indexed(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == "INDEXED")

    @property
    def chunks(self) -> int:
        return sum(outcome.chunks for outcome in self.outcomes)

    def as_dict(self) -> dict[str, Any]:
        return {
            "courseId": self.course_id,
            "targetCourseId": self.target_course_id,
            "counts": self.counts(),
            "indexed": self.indexed,
            "chunks": self.chunks,
            "outcomes": [outcome.as_dict() for outcome in self.outcomes],
        }


def _hash_file(path: pathlib.Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    written = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            written += len(block)
    return digest.hexdigest(), written


def _media_type(extension: str) -> str | None:
    allowed = MEDIA_TYPES.get(extension.casefold())
    if not allowed:
        return None
    preferred = sorted(name for name in allowed if name != "application/octet-stream")
    return preferred[0] if preferred else sorted(allowed)[0]


def ingest_course(
    course_plan: CoursePlan,
    *,
    service: IngestionService,
    repository: CampusMaterialRepository,
    target_course_id: str,
) -> CourseIngestionReport:
    """Ingest one offering's ingestable material into an existing non-public course.

    Every file is re-verified against the inventory (size and SHA-256) before it is read, a
    duplicate is reused rather than re-ingested, and anything that cannot be parsed becomes
    `DOWNLOAD_ONLY` rather than an indexed document. The function never publishes anything: the
    material records keep their review status, and no `courses` row is touched here.
    """
    report = CourseIngestionReport(
        course_id=course_plan.course_id, target_course_id=target_course_id
    )
    for row in course_plan.rows:
        decision = course_plan.decisions[row.key]
        if decision.status != INGESTABLE:
            repository.upsert(row, decision, target_course_id=target_course_id)
            report.outcomes.append(
                IngestionOutcome(row.relative_path, decision.status, decision.reason)
            )
            continue
        outcome = _ingest_one(
            row, decision, service=service, repository=repository, target_course_id=target_course_id
        )
        report.outcomes.append(outcome)
    return report


def _ingest_one(
    row: InventoryRow,
    decision: MaterialDecision,
    *,
    service: IngestionService,
    repository: CampusMaterialRepository,
    target_course_id: str,
) -> IngestionOutcome:
    path = row.source_path
    if not path.is_file():
        blocked = MaterialDecision(BLOCKED, "SOURCE_FILE_MISSING", REVIEW_NEEDS_OWNER)
        repository.upsert(row, blocked, target_course_id=target_course_id)
        return IngestionOutcome(row.relative_path, BLOCKED, blocked.reason)
    digest, size = _hash_file(path)
    if size != row.bytes_disk or (row.sha256 and digest != row.sha256):
        blocked = MaterialDecision(
            BLOCKED,
            f"SOURCE_CHANGED: the file no longer matches the inventory "
            f"({size} bytes, sha256 {digest[:12]}…)",
            REVIEW_NEEDS_OWNER,
        )
        repository.upsert(row, blocked, target_course_id=target_course_id)
        return IngestionOutcome(row.relative_path, BLOCKED, blocked.reason)

    extension = pathlib.PurePosixPath(row.filename).suffix.casefold()
    media_type = _media_type(extension)
    if media_type is None:
        download_only = MaterialDecision(
            DOWNLOAD_ONLY,
            f"{extension or 'no extension'} is not a material type CourseMate can parse",
            REVIEW_NEEDS_RIGHTS,
        )
        repository.upsert(row, download_only, target_course_id=target_course_id)
        return IngestionOutcome(row.relative_path, DOWNLOAD_ONLY, download_only.reason)

    content = path.read_bytes()
    try:
        accepted = service.queue_document(
            course_id=target_course_id,
            filename=pathlib.PurePosixPath(row.filename).name,
            media_type=media_type,
            content=content,
            is_admin=True,
        )
    except ApiError as error:
        existing = error.details.get("documentId")
        if error.code == "DUPLICATE_DOCUMENT" and isinstance(existing, str):
            repository.upsert(
                row, decision, target_course_id=target_course_id, document_id=existing
            )
            return IngestionOutcome(
                row.relative_path,
                "SKIPPED_IDENTICAL",
                "identical content already in the course",
                document_id=existing,
            )
        repository.upsert(row, decision, target_course_id=target_course_id)
        return IngestionOutcome(row.relative_path, "FAILED", f"{error.code}: {error.message}")

    service.process_document(accepted.document.id, accepted.job.id)
    ingest_job = service.get_job(accepted.job.id)
    document = service.get_document(accepted.document.id)
    if str(ingest_job.status.value) == "completed" and document.chunk_count > 0:
        repository.upsert(
            row, decision, target_course_id=target_course_id, document_id=accepted.document.id
        )
        return IngestionOutcome(
            row.relative_path,
            "INDEXED",
            decision.reason,
            document_id=accepted.document.id,
            chunks=int(document.chunk_count),
        )
    # Stored, but no readable text: recorded as DOWNLOAD_ONLY so it can never count as coverage.
    download_only = MaterialDecision(
        DOWNLOAD_ONLY,
        str(ingest_job.error_message or "the file produced no extractable text"),
        REVIEW_NEEDS_RIGHTS,
    )
    repository.upsert(
        row, download_only, target_course_id=target_course_id, document_id=accepted.document.id
    )
    return IngestionOutcome(
        row.relative_path, DOWNLOAD_ONLY, download_only.reason, document_id=accepted.document.id
    )


def campus_course_id(institution_origin: str, canvas_course_id: str) -> str:
    """A stable course id for one offering, derived from the external unique key.

    The pack fixes the external key as institution origin plus Canvas course id, so the local id is
    derived from exactly those two facts and never from a name.
    """
    host = re.sub(r"[^a-z0-9]+", "-", institution_origin.casefold()).strip("-") or "canvas"
    digest = hashlib.sha256(f"{institution_origin}|{canvas_course_id}".encode()).hexdigest()[:10]
    return f"campus-{host}-{canvas_course_id}-{digest}"[:50].rstrip("-")


def review_list_rows(records: Sequence[sqlite3.Row]) -> list[dict[str, str]]:
    """The consolidated list the owner is asked to decide once, with no personal names in it."""
    return [
        {
            "institution_origin": str(record["institution_origin"]),
            "canvas_course_id": str(record["canvas_course_id"]),
            "course_code": str(record["course_code"] or ""),
            "filename": str(record["filename"]),
            "sha256": str(record["sha256"]),
            "bytes": str(record["bytes_disk"]),
            "classification": str(record["classification"]),
            "decision": str(record["decision"]),
            "reason": str(record["decision_reason"]),
            "review_status": str(record["review_status"]),
            "publication_basis": str(record["publication_basis"]),
        }
        for record in records
    ]
