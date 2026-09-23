"""The Canvas import worker: real ingestion, real retry rules, real checkpoints.

What is simulated here is the school's HTTP surface and nothing else. The tests drive the
real `CanvasReadAdapter` (URL validation, pagination, streaming, error classification), the
real `CanvasJobRepository` on the real migrated schema, and the real `IngestionService` with
the deterministic embedding provider, so the document rows, the chunk counts, the quotas and
the duplicate detection are production behaviour.

The import worker is the one place where "the job says COMPLETED" has to mean something, so
these tests are written around the ways that claim could become a lie: a locked file retried
until it looks like success, a throttled download reported as failed, a credential failure
that keeps hammering the school, a cancelled import that deletes what it already imported, a
second run that imports everything twice, an unparseable picture counted as material, and a
deferred file that lets a half-finished job finish. Each of those fails a test if the rule is
removed.
"""

from __future__ import annotations

import hashlib
import ipaddress
import pathlib
import re
import sqlite3
from contextlib import ExitStack
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.canvas import (
    CanvasImportWorker,
    CanvasReadAdapter,
    InstitutionConnectionRegistry,
    default_target_course_resolver,
    material_media_type,
    new_job,
    safe_upload_name,
    target_course_slug,
)
from app.canvas.job import ACTIVE_STATES, AWAITING_SELECTION, QUEUED, FileRecord
from app.canvas.store import CanvasJobRepository
from app.config import Settings
from app.db import Database
from app.rag.embeddings import DeterministicEmbeddingProvider
from app.services.ingestion import IngestionService

CITYU = "https://canvas.cityu.edu.hk"
SUBJECT = "user-1"
CONNECTION = "conn-1"
TOKEN = "token-1"

# `Database.connect()` is a context manager, so the connection a repository needs must stay
# open for the whole test. Held here for the process lifetime, as the store tests do.
_STACKS: list[ExitStack] = []

DETAIL_PATH = re.compile(r"^/api/v1/courses/(\d+)/files/(\d+)$")
LISTING_PATH = re.compile(r"^/api/v1/courses/(\d+)/files$")
DOWNLOAD_PATH = re.compile(r"^/download/(\d+)/(\d+)$")


def public_resolver(host, *_args, **_kwargs):
    """A resolver that must not touch DNS. An IP literal resolves to itself, so the
    private-address rules still run instead of being masked by a permissive stub."""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return [(2, 1, 6, "", ("93.184.216.34", 0))]
    return [(2, 1, 6, "", (host, 0))]


TEXT_A = "# Lighting\n\nDiffuse reflection scatters light in every direction.\n"
TEXT_B = "# Shading\n\nSpecular highlights depend on the view direction.\n"
# A one-pixel PNG: a real, valid image the ingestion layer stores but cannot parse into text,
# which is exactly the case that must not count as readable material.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)
# A file whose bytes merely claim to be a PDF: the upload validator checks the header and
# passes, the loader then fails, so a document row exists that can never become material.
FAKE_PDF = b"%PDF-1.4\nthis is not a real pdf body\n"


class FakeCanvas:
    """The school's read surface, and a record of everything the worker asked it for."""

    def __init__(
        self,
        *,
        courses: dict[str, list[dict[str, Any]]],
        files: dict[str, list[dict[str, Any]]],
        media: dict[tuple[str, str], bytes],
    ) -> None:
        self.courses = courses
        self.files = files
        self.media = media
        self.requests: list[tuple[str, str]] = []
        self.authorization: dict[str, str] = {}
        # Per-endpoint scripts: each call pops one entry, so a script can fail then succeed.
        self.detail_script: dict[tuple[str, str], list[Any]] = {}
        self.download_script: dict[tuple[str, str], list[Any]] = {}
        self.listing_script: dict[str, list[Any]] = {}
        self.retry_after: dict[tuple[str, str], float] = {}
        self.download_hits: dict[tuple[str, str], int] = {}
        self.detail_hits: dict[tuple[str, str], int] = {}

    def detail_calls(self, key: tuple[str, str]) -> int:
        return self.detail_hits.get(key, 0)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append((request.method, path))
        self.authorization[path] = request.headers.get("authorization", "")
        if request.method != "GET":
            return httpx.Response(405, json={"errors": [{"message": "read only"}]})
        query = dict(request.url.params)
        if path == "/api/v1/courses":
            state = query.get("enrollment_state", "active")
            return httpx.Response(200, json=self.courses.get(state, []))

        detail = DETAIL_PATH.match(path)
        if detail:
            key = (detail.group(1), detail.group(2))
            self.detail_hits[key] = self.detail_hits.get(key, 0) + 1
            scripted = self._pop(self.detail_script, key)
            if isinstance(scripted, int):
                return httpx.Response(scripted, json={"errors": [{"message": "scripted"}]})
            if key not in self.media:
                return httpx.Response(404, json={"errors": [{"message": "no such file"}]})
            return httpx.Response(
                200,
                json={
                    "id": int(key[1]),
                    "display_name": self._display_name(key),
                    "size": len(self.media[key]),
                    "url": f"{CITYU}/download/{key[0]}/{key[1]}",
                },
            )

        download = DOWNLOAD_PATH.match(path)
        if download:
            key = (download.group(1), download.group(2))
            self.download_hits[key] = self.download_hits.get(key, 0) + 1
            scripted = self._pop(self.download_script, key)
            if isinstance(scripted, int):
                headers = (
                    {"retry-after": str(self.retry_after.get(key, 1))} if scripted == 429 else {}
                )
                return httpx.Response(
                    scripted, headers=headers, json={"errors": [{"message": "scripted"}]}
                )
            if scripted == "network":
                raise httpx.ConnectError("connection reset", request=request)
            if key not in self.media:
                return httpx.Response(404, json={"errors": [{"message": "no such file"}]})
            return httpx.Response(
                200,
                content=self.media[key],
                headers={"content-type": "application/octet-stream"},
            )

        listing = LISTING_PATH.match(path)
        if listing:
            course_id = listing.group(1)
            scripted = self._pop(self.listing_script, course_id)
            if isinstance(scripted, int):
                return httpx.Response(scripted, json={"errors": [{"message": "scripted"}]})
            return httpx.Response(200, json=self.files.get(course_id, []))

        return httpx.Response(404, json={"errors": [{"message": "not found"}]})

    @staticmethod
    def _pop(script: dict[Any, list[Any]], key) -> Any:
        entries = script.get(key)
        return entries.pop(0) if entries else None

    def _display_name(self, key: tuple[str, str]) -> str:
        for entry in self.files.get(key[0], []):
            if str(entry["id"]) == key[1]:
                return str(entry["display_name"])
        return f"file-{key[1]}"


def course_entry(
    course_id: int,
    name: str,
    *,
    workflow_state: str = "available",
    role: str = "student",
    enrollment_state: str = "active",
) -> dict[str, Any]:
    return {
        "id": course_id,
        "name": name,
        "course_code": name,
        "workflow_state": workflow_state,
        "enrollments": [
            {
                "type": role,
                "role": f"{role.title()}Enrollment",
                "enrollment_state": enrollment_state,
            }
        ],
    }


def file_entry(file_id: int, display_name: str, size: int) -> dict[str, Any]:
    return {"id": file_id, "display_name": display_name, "size": size, "updated_at": "2026-01-01"}


@dataclass
class Harness:
    canvas: FakeCanvas
    database: Database
    settings: Settings
    ingestion: IngestionService
    repository: CanvasJobRepository
    connection: sqlite3.Connection
    worker: CanvasImportWorker
    sleeps: list[float] = field(default_factory=list)
    work_dir: pathlib.Path = pathlib.Path()

    # ------------------------------------------------------------------ assertions
    def job_row(self, job_id: str = "job-1") -> sqlite3.Row:
        row = self.connection.execute(
            "SELECT * FROM canvas_import_jobs WHERE id=?", (job_id,)
        ).fetchone()
        assert row is not None
        return row

    def file_rows(self, job_id: str = "job-1") -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM canvas_import_files WHERE job_id=? ORDER BY rowid", (job_id,)
        ).fetchall()

    def files_by_id(self, job_id: str = "job-1") -> dict[str, sqlite3.Row]:
        return {str(row["source_file_id"]): row for row in self.file_rows(job_id)}

    def documents(self) -> list[sqlite3.Row]:
        return self.connection.execute("SELECT * FROM documents ORDER BY rowid").fetchall()

    def readable_documents(self) -> list[sqlite3.Row]:
        """Documents that produced text a model could actually read."""
        return [doc for doc in self.documents() if int(doc["chunk_count"]) > 0]

    def course_rows(self) -> list[sqlite3.Row]:
        return self.connection.execute("SELECT * FROM courses ORDER BY rowid").fetchall()

    def course_row(self, course_id: str) -> sqlite3.Row:
        row = self.connection.execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone()
        assert row is not None
        return row

    def chunks(self, document_id: str) -> int:
        return int(
            self.connection.execute(
                "SELECT COUNT(*) FROM chunks WHERE document_id=?", (document_id,)
            ).fetchone()[0]
        )


def two_course_canvas() -> FakeCanvas:
    media = {("560", "1"): TEXT_A.encode(), ("240", "7"): TEXT_B.encode()}
    return FakeCanvas(
        courses={
            "active": [course_entry(560, "CS2312 Problem Solving")],
            "completed": [course_entry(240, "CS2204 Internet Apps", workflow_state="completed")],
        },
        files={
            "560": [file_entry(1, "lighting.md", len(media[("560", "1")]))],
            "240": [file_entry(7, "shading.md", len(media[("240", "7")]))],
        },
        media=media,
    )


def build(
    tmp_path: pathlib.Path,
    canvas: FakeCanvas,
    *,
    max_ingest_bytes: int = 20 * 1024 * 1024,
    max_attempts: int = 3,
    max_files_per_run: int = 200,
    worker_id: str = "worker-1",
) -> Harness:
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        chunk_size=200,
        chunk_overlap=20,
        app_env="test",
        v3_enabled=True,
        rag_provider_mode="deterministic",
        ui_web_dir=tmp_path / "no-web-build",
    )
    database = Database(settings)
    database.initialize()
    stack = ExitStack()
    _STACKS.append(stack)
    connection = stack.enter_context(database.connect())
    # The harness connection stays open for the whole test, while the ingestion service writes
    # on its own connections. Autocommit here means a harness write never holds the database
    # lock against the code under test (which is what a real worker does anyway: one short
    # transaction per statement).
    connection.isolation_level = None
    connection.execute(
        "INSERT INTO canvas_connections(id, owner_user_id, institution_key, institution_origin, "
        "canvas_user_id) VALUES(?,?,?,?,?)",
        (CONNECTION, SUBJECT, "cityu", CITYU, "4242"),
    )
    ingestion = IngestionService(database, settings, DeterministicEmbeddingProvider())
    repository = CanvasJobRepository(connection)
    transport = httpx.MockTransport(canvas.handler)
    adapter = CanvasReadAdapter(
        connection_id=CONNECTION,
        origin=CITYU,
        token_provider=lambda: TOKEN,
        registry=InstitutionConnectionRegistry(),
        client=httpx.Client(base_url=CITYU, transport=transport, follow_redirects=False),
        download_client=httpx.Client(transport=transport, follow_redirects=False),
        resolver=public_resolver,
    )
    sleeps: list[float] = []
    work_dir = tmp_path / "canvas-work"
    worker = CanvasImportWorker(
        repository=repository,
        ingestion=ingestion,
        adapter_for=lambda claimed: adapter,
        target_course_for=default_target_course_resolver(ingestion, repository),
        work_dir=work_dir,
        max_ingest_bytes=max_ingest_bytes,
        worker_id=worker_id,
        max_files_per_run=max_files_per_run,
        max_attempts=max_attempts,
        sleeper=sleeps.append,
    )
    return Harness(
        canvas=canvas,
        database=database,
        settings=settings,
        ingestion=ingestion,
        repository=repository,
        connection=connection,
        worker=worker,
        sleeps=sleeps,
        work_dir=work_dir,
    )


def queued_job(harness: Harness, *, job_id: str = "job-1", course_ids=("560", "240")):
    """A job the way the confirmation route would leave it: selected, queued, frozen."""
    job = new_job(
        job_id=job_id,
        connection_id=CONNECTION,
        subject=SUBJECT,
        institution_origin=CITYU,
        course_ids=list(course_ids),
    )
    job.transition(AWAITING_SELECTION)
    job.transition(QUEUED)
    harness.repository.create_or_get(job)
    return job


def single_course_canvas(files: dict[str, bytes], *, names=None) -> FakeCanvas:
    """One course, one file list, so a test can be about exactly one file's outcome."""
    names = names or {}
    entries = [
        file_entry(int(file_id), names.get(file_id, f"{file_id}.md"), len(payload))
        for file_id, payload in files.items()
    ]
    return FakeCanvas(
        courses={"active": [course_entry(560, "CS2312")], "completed": []},
        files={"560": entries},
        media={("560", file_id): payload for file_id, payload in files.items()},
    )


# ------------------------------------------------------------------ the happy path
def test_a_selection_is_imported_into_a_private_course_through_real_ingestion(tmp_path) -> None:
    harness = build(tmp_path, two_course_canvas())
    queued_job(harness)

    result = harness.worker.run_once()

    assert result is not None and result.stopped == ""
    assert result.status == "COMPLETED"
    assert result.pending == 0

    course_row = harness.course_row(str(harness.job_row()["target_course_id"]))
    # The import must land somewhere private, owned by the student, outside the admin pipeline.
    assert course_row["course_type"] == "user"
    assert course_row["visibility"] == "private"
    assert course_row["publication_status"] == "private"
    assert course_row["owner_user_id"] == SUBJECT

    rows = harness.files_by_id()
    assert set(rows) == {"1", "7"}
    assert {row["status"] for row in rows.values()} == {"INDEXED"}
    assert {row["parse_state"] for row in rows.values()} == {"parsed"}
    assert {row["index_state"] for row in rows.values()} == {"indexed"}
    assert all(row["bytes_sha256"] for row in rows.values())
    assert all(row["local_document_id"] for row in rows.values())

    documents = harness.documents()
    assert {doc["filename"] for doc in documents} == {"lighting.md", "shading.md"}
    assert all(int(doc["chunk_count"]) > 0 for doc in documents)
    assert [harness.chunks(doc["id"]) for doc in documents] == [
        int(doc["chunk_count"]) for doc in documents
    ]
    assert all(doc["course_id"] == course_row["id"] for doc in documents)


def test_the_import_sends_only_gets_and_never_the_token_to_the_download_host(tmp_path) -> None:
    harness = build(tmp_path, two_course_canvas())
    queued_job(harness)
    harness.worker.run_once()

    assert {method for method, _ in harness.canvas.requests} == {"GET"}
    for path, authorization in harness.canvas.authorization.items():
        if path.startswith("/api/v1/"):
            assert authorization == f"Bearer {TOKEN}"
        else:
            assert authorization == "", f"{path} received the Canvas credential"


# ------------------------------------------------------------------ failure rules
def test_a_locked_file_is_never_retried_and_makes_the_import_imperfect(tmp_path) -> None:
    canvas = two_course_canvas()
    canvas.detail_script[("560", "1")] = [403, 403, 403, 403]
    harness = build(tmp_path, canvas)
    queued_job(harness)

    result = harness.worker.run_once()

    assert result is not None and result.status == "COMPLETED_WITH_WARNINGS"
    locked = harness.files_by_id()["1"]
    assert (locked["status"], locked["error_class"]) == ("WARNING", "FORBIDDEN")
    assert canvas.detail_calls(("560", "1")) == 1, "a 403 must not be re-probed"
    # The other course is still imported: one locked file does not fail the whole import.
    assert harness.files_by_id()["7"]["status"] == "INDEXED"
    assert [doc["filename"] for doc in harness.readable_documents()] == ["shading.md"]


def test_a_rate_limited_download_waits_the_interval_the_school_asked_for(tmp_path) -> None:
    canvas = two_course_canvas()
    canvas.download_script[("560", "1")] = [429]
    canvas.retry_after[("560", "1")] = 3
    harness = build(tmp_path, canvas)
    queued_job(harness)

    result = harness.worker.run_once()

    assert harness.sleeps == [3.0]
    assert canvas.download_hits[("560", "1")] == 2
    row = harness.files_by_id()["1"]
    assert (row["status"], row["attempts"]) == ("INDEXED", 2)
    assert result is not None and result.status == "COMPLETED"


def test_a_dead_credential_stops_the_batch_instead_of_hammering_the_school(tmp_path) -> None:
    canvas = two_course_canvas()
    for key in canvas.media:
        canvas.detail_script[key] = [401, 401, 401]
    harness = build(tmp_path, canvas)
    queued_job(harness)

    result = harness.worker.run_once()

    assert result is not None and result.status == "NEEDS_REAUTH"
    assert harness.job_row()["error_code"] == "EXPIRED_TOKEN"
    rows = harness.files_by_id()
    failed = [row for row in rows.values() if row["error_class"] == "EXPIRED_TOKEN"]
    pending = [row for row in rows.values() if row["status"] == "PENDING"]
    assert len(failed) == 1 and failed[0]["status"] == "FAILED"
    # Exactly one file was attempted: the batch ended rather than failing file by file.
    assert len(pending) == 1
    assert sum(canvas.detail_hits.values()) == 1
    assert canvas.download_hits == {}
    assert harness.documents() == []


def test_a_transport_failure_defers_the_file_and_leaves_the_job_unfinished(tmp_path) -> None:
    canvas = two_course_canvas()
    canvas.download_script[("560", "1")] = ["network"]
    harness = build(tmp_path, canvas)
    queued_job(harness)

    result = harness.worker.run_once()

    assert result is not None
    assert result.stopped == "deferred"
    # The critical property: a pending file can never be reported as a finished import.
    assert harness.job_row()["status"] in ACTIVE_STATES
    assert harness.job_row()["status"] == result.status
    assert result.pending == 1
    row = harness.files_by_id()["1"]
    assert (row["status"], row["error_class"], row["attempts"]) == ("PENDING", "NETWORK", 1)
    # The lease is handed back, so the next run continues this job instead of stranding it.
    assert harness.repository.claim(worker_id="worker-2") is not None


def test_a_file_that_keeps_failing_ends_as_a_visible_warning(tmp_path) -> None:
    canvas = two_course_canvas()
    canvas.download_script[("560", "1")] = ["network", "network", "network"]
    harness = build(tmp_path, canvas, max_attempts=2)
    queued_job(harness)

    first = harness.worker.run_once()
    assert first is not None and first.stopped == "deferred"
    assert harness.files_by_id()["1"]["attempts"] == 1
    second = harness.worker.run_once()
    # The second failure exhausts the attempt budget, so the third run gives up rather than
    # retrying a file that has never worked.
    assert second is not None and second.stopped == "deferred"
    assert harness.files_by_id()["1"]["attempts"] == 2
    third = harness.worker.run_once()

    assert third is not None and third.status == "COMPLETED_WITH_WARNINGS"
    row = harness.files_by_id()["1"]
    assert row["status"] == "WARNING" and row["attempts"] == 2
    assert "gave up after 2 attempts" in str(row["error_detail"])


def test_a_zero_byte_file_is_an_empty_warning_not_a_failure(tmp_path) -> None:
    media = {("560", "1"): b"", ("240", "7"): TEXT_B.encode()}
    canvas = FakeCanvas(
        courses={
            "active": [course_entry(560, "CS2312")],
            "completed": [course_entry(240, "CS2204", workflow_state="completed")],
        },
        files={
            "560": [file_entry(1, "empty.md", 0)],
            "240": [file_entry(7, "shading.md", len(media[("240", "7")]))],
        },
        media=media,
    )
    harness = build(tmp_path, canvas)
    queued_job(harness)

    result = harness.worker.run_once()

    assert result is not None and result.status == "COMPLETED_WITH_WARNINGS"
    row = harness.files_by_id()["1"]
    assert (row["status"], row["error_class"]) == ("WARNING", "EMPTY")
    assert [doc["filename"] for doc in harness.readable_documents()] == ["shading.md"]


# ------------------------------------------------------------------ unreadable material
def test_a_picture_is_stored_but_never_counted_as_readable_material(tmp_path) -> None:
    """The ingestion layer marks a loader-less extension "ready" with zero chunks.

    Treating that as an indexed document is exactly the mistake that would let an image count
    towards coverage, so it must be DOWNLOAD_ONLY, and the import must not be clean.
    """
    media = {("560", "1"): PNG, ("240", "7"): TEXT_B.encode()}
    canvas = FakeCanvas(
        courses={
            "active": [course_entry(560, "CS2312")],
            "completed": [course_entry(240, "CS2204", workflow_state="completed")],
        },
        files={
            "560": [file_entry(1, "diagram.png", len(PNG))],
            "240": [file_entry(7, "shading.md", len(media[("240", "7")]))],
        },
        media=media,
    )
    harness = build(tmp_path, canvas)
    queued_job(harness)

    result = harness.worker.run_once()

    assert result is not None and result.status == "COMPLETED_WITH_WARNINGS"
    row = harness.files_by_id()["1"]
    assert row["status"] == "DOWNLOAD_ONLY"
    assert (row["parse_state"], row["index_state"]) == ("empty", "skipped")
    assert row["bytes_sha256"] == hashlib.sha256(PNG).hexdigest()
    assert [doc["filename"] for doc in harness.readable_documents()] == ["shading.md"]
    # The bytes are kept: the worker's copy is the only one CourseMate has for this file.
    assert any(harness.work_dir.rglob("*"))


def test_a_file_that_cannot_be_parsed_keeps_its_document_row_but_indexes_nothing(tmp_path) -> None:
    media = {("560", "1"): FAKE_PDF, ("240", "7"): TEXT_B.encode()}
    canvas = FakeCanvas(
        courses={
            "active": [course_entry(560, "CS2312")],
            "completed": [course_entry(240, "CS2204", workflow_state="completed")],
        },
        files={
            "560": [file_entry(1, "broken.pdf", len(FAKE_PDF))],
            "240": [file_entry(7, "shading.md", len(media[("240", "7")]))],
        },
        media=media,
    )
    harness = build(tmp_path, canvas)
    queued_job(harness)

    result = harness.worker.run_once()

    assert result is not None and result.status == "COMPLETED_WITH_WARNINGS"
    row = harness.files_by_id()["1"]
    assert (row["status"], row["parse_state"]) == ("DOWNLOAD_ONLY", "failed")
    assert row["local_document_id"], "the stored document must be linked, not hidden"
    broken = [doc for doc in harness.documents() if doc["filename"] == "broken.pdf"]
    assert len(broken) == 1 and int(broken[0]["chunk_count"]) == 0
    assert [doc["filename"] for doc in harness.readable_documents()] == ["shading.md"]


def test_a_file_above_the_ingestion_limit_is_not_downloaded_at_all(tmp_path) -> None:
    media = {("560", "1"): b"x" * 5000, ("240", "7"): TEXT_B.encode()}
    canvas = FakeCanvas(
        courses={
            "active": [course_entry(560, "CS2312")],
            "completed": [course_entry(240, "CS2204", workflow_state="completed")],
        },
        files={
            "560": [file_entry(1, "huge.md", 5000)],
            "240": [file_entry(7, "shading.md", len(media[("240", "7")]))],
        },
        media=media,
    )
    harness = build(tmp_path, canvas, max_ingest_bytes=1000)
    queued_job(harness)

    result = harness.worker.run_once()

    assert result is not None and result.status == "COMPLETED_WITH_WARNINGS"
    row = harness.files_by_id()["1"]
    assert (row["status"], row["error_class"]) == ("WARNING", "TOO_LARGE")
    assert canvas.download_hits.get(("560", "1")) is None, "no bytes should be fetched at all"


# ------------------------------------------------------------------ identity and versions
def test_the_same_name_with_different_ids_is_two_files_and_two_documents(tmp_path) -> None:
    payloads = {"1": TEXT_A.encode(), "2": TEXT_B.encode()}
    canvas = single_course_canvas(payloads, names={"1": "notes.md", "2": "notes.md"})
    harness = build(tmp_path, canvas)
    queued_job(harness, course_ids=("560",))

    result = harness.worker.run_once()

    assert result is not None and result.status == "COMPLETED"
    rows = harness.files_by_id()
    assert set(rows) == {"1", "2"}
    assert len({row["bytes_sha256"] for row in rows.values()}) == 2
    assert len(harness.documents()) == 2


def test_a_changed_version_is_refetched_rather_than_reusing_the_old_bytes(tmp_path) -> None:
    """A pending row keeps the *previous* hash; trusting it would ingest stale content."""
    canvas = two_course_canvas()
    harness = build(tmp_path, canvas)
    job = queued_job(harness)
    first = harness.worker.run_once()
    assert first is not None and first.status == "COMPLETED"
    old = harness.files_by_id()["1"]
    assert old["bytes_sha256"] == hashlib.sha256(TEXT_A.encode()).hexdigest()

    # The school changes the file in place, and the import resumes.
    new_text = "# Lighting (revised)\n\nSpecular and diffuse reflection both matter.\n"
    canvas.media[("560", "1")] = new_text.encode()
    canvas.files["560"] = [file_entry(1, "lighting.md", len(new_text.encode()))]
    harness.connection.execute(
        "UPDATE canvas_import_jobs SET status='DOWNLOADING' WHERE id=?", (job.job_id,)
    )
    # A stale copy of the previous version sits exactly where a naive cache would reuse it.
    stale = harness.worker._sink(job.job_id, key_record(old))
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(TEXT_A.encode())
    assert hashlib.sha256(stale.read_bytes()).hexdigest() == old["bytes_sha256"]

    second = harness.worker.run_once()

    assert second is not None and second.status == "COMPLETED"
    row = harness.files_by_id()["1"]
    assert row["bytes_sha256"] == hashlib.sha256(new_text.encode()).hexdigest()
    document = [doc for doc in harness.documents() if doc["id"] == row["local_document_id"]]
    assert len(document) == 1
    assert document[0]["sha256"] == hashlib.sha256(new_text.encode()).hexdigest()
    assert int(document[0]["byte_size"]) == len(new_text.encode())


def key_record(row: sqlite3.Row) -> FileRecord:
    """The identity of a file row, which is all the worker's storage path depends on."""
    return FileRecord(
        origin=str(row["origin"]),
        course_id=str(row["source_course_id"]),
        file_id=str(row["source_file_id"]),
        display_name=str(row["display_name"]),
    )


def test_a_pending_row_never_vouches_for_bytes_on_disk(tmp_path) -> None:
    """The defence that a mutation first showed was untested.

    Removing the status check in the worker's reuse test left this suite green, because the
    changed-version test is caught earlier by `add_file` clearing the hash in memory. The state
    that check actually protects is the one a crash leaves behind: a row that went back to
    `PENDING` while the database still carries the previous version's hash, with those old bytes
    sitting exactly where the worker looks for them. Trusting that hash would ingest the old
    version and report the new one as done, so the state is set up here by hand and the worker
    must fetch the file again.
    """
    canvas = two_course_canvas()
    harness = build(tmp_path, canvas)
    job = queued_job(harness)
    assert harness.worker.run_once() is not None
    old = harness.files_by_id()["1"]
    old_sha = str(old["bytes_sha256"])

    target = len(TEXT_A.encode())
    new_text = "# Lighting v2\n\nCorrected diffuse reflection.\n"
    # Padded to the same length on purpose: the version check compares size, timestamp and
    # etag, so a same-length replacement with unchanged metadata is exactly the case where
    # nothing but the status can tell the worker that the bytes on disk are not the new file.
    new_text = (new_text + " " * target)[:target]
    assert len(new_text.encode()) == target and new_text != TEXT_A
    canvas.media[("560", "1")] = new_text.encode()
    canvas.files["560"] = [file_entry(1, "lighting.md", len(new_text.encode()))]
    stale = harness.worker._sink(job.job_id, key_record(old))
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(TEXT_A.encode())
    assert hashlib.sha256(stale.read_bytes()).hexdigest() == old_sha
    # The crashed state: pending, but still carrying the hash of what used to be there.
    harness.connection.execute(
        "UPDATE canvas_import_files SET status='PENDING', bytes_sha256=? "
        "WHERE job_id='job-1' AND source_file_id='1'",
        (old_sha,),
    )
    harness.connection.execute(
        "UPDATE canvas_import_jobs SET status='DOWNLOADING' WHERE id=?", (job.job_id,)
    )

    result = harness.worker.run_once()

    assert result is not None and result.status == "COMPLETED"
    row = harness.files_by_id()["1"]
    assert row["bytes_sha256"] == hashlib.sha256(new_text.encode()).hexdigest()
    assert canvas.download_hits[("560", "1")] == 2, "the stale copy must not have been reused"
    document = [doc for doc in harness.documents() if doc["id"] == row["local_document_id"]]
    assert document[0]["sha256"] == hashlib.sha256(new_text.encode()).hexdigest()


def test_a_second_run_of_a_finished_job_imports_nothing_again(tmp_path) -> None:
    harness = build(tmp_path, two_course_canvas())
    queued_job(harness)
    assert harness.worker.run_once() is not None
    course_id = str(harness.job_row()["target_course_id"])
    documents = len(harness.documents())

    again = harness.worker.run_once()

    assert again is None, "a completed job is not claimable again"
    assert harness.job_row()["target_course_id"] == course_id
    assert len(harness.documents()) == documents
    assert len(harness.course_rows()) == 1, "no second private course for the same import"


def test_identical_content_already_in_the_course_is_skipped_not_duplicated(tmp_path) -> None:
    canvas = single_course_canvas(
        {"1": TEXT_A.encode(), "2": TEXT_A.encode()},
        names={"1": "notes.md", "2": "notes-copy.md"},
    )
    harness = build(tmp_path, canvas)
    queued_job(harness, course_ids=("560",))

    result = harness.worker.run_once()

    assert result is not None and result.status == "COMPLETED"
    rows = harness.files_by_id()
    assert rows["1"]["status"] == "INDEXED"
    assert rows["2"]["status"] == "SKIPPED_IDENTICAL"
    assert rows["2"]["local_document_id"] == rows["1"]["local_document_id"]
    assert len(harness.documents()) == 1


# ------------------------------------------------------------------ scope and safety
def test_a_course_the_student_is_not_enrolled_in_is_never_read(tmp_path) -> None:
    canvas = two_course_canvas()
    canvas.courses["active"] = [
        course_entry(560, "CS2312"),
        course_entry(999, "A course where I am a teacher", role="teacher"),
    ]
    canvas.files["999"] = [file_entry(5, "secret.md", 4)]
    canvas.media[("999", "5")] = b"nope"
    harness = build(tmp_path, canvas)
    queued_job(harness, course_ids=("560", "999"))

    result = harness.worker.run_once()

    assert result is not None and result.status == "COMPLETED_WITH_WARNINGS"
    assert harness.job_row()["error_code"] == "NOT_FOUND"
    assert harness.canvas.detail_calls(("999", "5")) == 0
    assert not any("/courses/999/" in path for _, path in harness.canvas.requests)
    # Only the enrolled course contributed files: 999 was refused before any listing.
    assert set(harness.files_by_id()) == {"1"}
    assert [doc["filename"] for doc in harness.readable_documents()] == ["lighting.md"]


def test_a_job_waiting_for_the_student_is_left_exactly_where_it_is(tmp_path) -> None:
    harness = build(tmp_path, two_course_canvas())
    job = new_job(
        job_id="job-1",
        connection_id=CONNECTION,
        subject=SUBJECT,
        institution_origin=CITYU,
        course_ids=["560"],
    )
    harness.repository.create_or_get(job)

    result = harness.worker.run_once()

    assert result is not None and result.stopped == "awaiting_user"
    assert result.status == "DISCOVERING"
    assert harness.canvas.requests == [], "no Canvas call before the student confirms"
    assert harness.repository.claim(worker_id="worker-2") is not None


def test_an_import_that_finds_nothing_creates_no_course_and_is_not_clean(tmp_path) -> None:
    canvas = FakeCanvas(
        courses={"active": [course_entry(560, "CS2312")], "completed": []},
        files={"560": []},
        media={},
    )
    harness = build(tmp_path, canvas)
    queued_job(harness, course_ids=("560",))

    result = harness.worker.run_once()

    assert result is not None and result.status == "COMPLETED_WITH_WARNINGS"
    assert harness.job_row()["target_course_id"] is None
    assert harness.course_rows() == []


def test_a_cancelled_import_stops_at_the_checkpoint_and_keeps_what_it_imported(tmp_path) -> None:
    harness = build(tmp_path, two_course_canvas())
    queued_job(harness)
    original = harness.repository.record_file_result
    calls = {"n": 0}

    def cancel_after_the_first_file(*args, **kwargs):
        original(*args, **kwargs)
        calls["n"] += 1
        if calls["n"] == 2:  # the first file has been verified and indexed
            harness.connection.execute(
                "UPDATE canvas_import_jobs SET status='CANCELLED' WHERE id='job-1'"
            )

    harness.repository.record_file_result = cancel_after_the_first_file  # type: ignore[method-assign]

    result = harness.worker.run_once()

    assert result is not None and result.stopped == "cancelled"
    assert result.status == "CANCELLED"
    assert harness.job_row()["status"] == "CANCELLED"
    rows = harness.files_by_id()
    assert rows["7"]["status"] == "INDEXED"
    assert rows["1"]["status"] == "CANCELLED"
    # Cancelling stops the import; it does not delete material that is already stored.
    assert [doc["filename"] for doc in harness.documents()] == ["shading.md"]


def test_a_worker_that_lost_its_lease_writes_nothing(tmp_path) -> None:
    harness = build(tmp_path, two_course_canvas())
    queued_job(harness)
    harness.repository.touch = lambda *args, **kwargs: False  # type: ignore[method-assign]

    result = harness.worker.run_once()

    assert result is not None and result.stopped == "lease_lost"
    assert harness.job_row()["status"] == "QUEUED"
    assert harness.documents() == []


def test_a_worker_defect_fails_the_job_instead_of_stranding_the_lease(tmp_path) -> None:
    harness = build(tmp_path, two_course_canvas())
    queued_job(harness)

    def explode(*args, **kwargs):
        raise RuntimeError("the database went away")

    harness.repository.list_files = explode  # type: ignore[method-assign]

    result = harness.worker.run_once()

    assert result is not None and result.stopped == "defect"
    assert result.status == "FAILED"
    row = harness.job_row()
    assert (row["status"], row["error_code"]) == ("FAILED", "WORKER_DEFECT")
    assert row["leased_until"] is None and row["worker_id"] is None


def test_the_batch_limit_stops_a_run_without_finishing_the_job(tmp_path) -> None:
    payloads = {str(i): f"# Part {i}\n\nContent {i}.\n".encode() for i in (1, 2, 3)}
    canvas = single_course_canvas(payloads, names={i: f"part{i}.md" for i in (1, 2, 3)})
    harness = build(tmp_path, canvas, max_files_per_run=1)
    queued_job(harness, course_ids=("560",))

    first = harness.worker.run_once()
    assert first is not None and first.stopped == "batch_limit"
    assert first.processed == 1
    # The phase records how far the run got, and it stays a working state: the job is not
    # finished just because this run ran out of its file budget.
    assert harness.job_row()["status"] == "INDEXING"
    assert harness.job_row()["status"] in ACTIVE_STATES
    assert harness.job_row()["completed_at"] is None
    assert sum(1 for row in harness.file_rows() if row["status"] == "PENDING") == 2

    second = harness.worker.run_once()
    assert second is not None and second.stopped == "batch_limit"
    third = harness.worker.run_once()
    assert third is not None and third.status == "COMPLETED"
    assert {row["status"] for row in harness.file_rows()} == {"INDEXED"}
    assert len(harness.documents()) == 3


def test_drain_imports_every_queued_job_and_then_stops(tmp_path) -> None:
    harness = build(tmp_path, two_course_canvas())
    queued_job(harness)
    other = new_job(
        job_id="job-2",
        connection_id=CONNECTION,
        subject=SUBJECT,
        institution_origin=CITYU,
        course_ids=["560"],
    )
    other.transition(AWAITING_SELECTION)
    other.transition(QUEUED)
    harness.repository.create_or_get(other)

    results = harness.worker.drain(max_jobs=3)

    assert [item.job_id for item in results] == ["job-1", "job-2"]
    assert {item.status for item in results} == {"COMPLETED"}
    assert harness.repository.claim(worker_id="worker-9") is None
    assert len(harness.course_rows()) == 2


# ------------------------------------------------------------------ pure helpers
def test_only_indexable_extensions_get_a_media_type() -> None:
    assert material_media_type(".md") == "text/markdown"
    assert material_media_type(".PDF") == "application/pdf"
    assert material_media_type(".mp4") is None
    assert material_media_type("") is None


def test_unsafe_names_are_made_storable_without_losing_the_extension() -> None:
    assert safe_upload_name("notes.md", file_id="1") == "notes.md"
    assert safe_upload_name("../../etc/passwd.md", file_id="1") == "passwd.md"
    assert safe_upload_name("a\x00b.md", file_id="1") == "a_b.md"
    assert safe_upload_name("   ", file_id="9") == "canvas-file-9"
    assert safe_upload_name("x" * 300 + ".pdf", file_id="1").endswith(".pdf")
    assert len(safe_upload_name("x" * 300 + ".pdf", file_id="1")) <= 200


def test_the_private_course_id_is_a_stable_valid_slug() -> None:
    first = target_course_slug(institution_host="canvas.cityu.edu.hk", course_ids=["560", "240"])
    assert first == target_course_slug(
        institution_host="canvas.cityu.edu.hk", course_ids=["240", "560"]
    ), "the id must not depend on the order the courses were chosen in"
    assert first != target_course_slug(institution_host="canvas.cityu.edu.hk", course_ids=["560"])
    assert first != target_course_slug(
        institution_host="cityu-dg.instructure.com", course_ids=["560", "240"]
    )
    assert re.fullmatch(r"[a-z0-9][a-z0-9-]{1,49}", first)
    assert not first.startswith("ws-")
