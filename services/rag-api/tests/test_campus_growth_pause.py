"""The local campus catalog is closed: the growth paths refuse, and nothing else is affected.

The final batch was frozen on 2026-09-24 (`CAMPUS_FINAL_BATCH_CLOSURE.md`). "Growth" means
discovery (walking `D:\\Canvas` / `D:\\Canvas-DG`) and ingestion (turning those files into
courses, documents and chunks). Both must be impossible unless an operator explicitly reopens
the path, and the switch must be fail-closed: a forgotten environment variable must not reopen
a closed batch.

The last test in this file is the one that keeps the pause honest: a **private** upload still
works while growth is closed, because the pause is about the platform's own expansion from a
local directory, not about the product.
"""

from __future__ import annotations

import pathlib
import sqlite3
import sys
from contextlib import ExitStack

import pytest

from app.campus_growth import (
    CAMPUS_CATALOG_GROWTH_ENV,
    CLOSURE_RECORD,
    CampusCatalogGrowthPaused,
    growth_is_open,
    growth_status,
    require_growth_open,
)
from app.campus_ingestion import (
    InventoryRow,
    plan,
)
from app.config import Settings
from app.db import Database
from app.errors import ApiError
from app.models import CourseCreate, PublicationStatus
from app.rag.embeddings import DeterministicEmbeddingProvider
from app.services.ingestion import IngestionService

SCRIPTS = pathlib.Path(__file__).resolve().parents[3] / "scripts"
_STACKS: list[ExitStack] = []


@pytest.fixture(autouse=True)
def _isolate_growth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test states the growth status it expects instead of inheriting the machine's."""
    monkeypatch.delenv(CAMPUS_CATALOG_GROWTH_ENV, raising=False)


@pytest.fixture(autouse=True)
def _close_stacks() -> None:
    yield
    while _STACKS:
        _STACKS.pop().close()


def service(tmp_path: pathlib.Path) -> tuple[IngestionService, sqlite3.Connection]:
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
    connection.isolation_level = None
    return IngestionService(database, settings, DeterministicEmbeddingProvider()), connection


def test_growth_is_paused_when_the_variable_is_unset() -> None:
    assert growth_status() == "paused"
    assert growth_is_open() is False
    with pytest.raises(CampusCatalogGrowthPaused) as refusal:
        require_growth_open("scan the local Canvas roots")
    message = str(refusal.value)
    assert "scan the local Canvas roots" in message
    assert CLOSURE_RECORD in message
    assert f"{CAMPUS_CATALOG_GROWTH_ENV}=open" in message


def test_only_the_explicit_open_value_reopens_growth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CAMPUS_CATALOG_GROWTH_ENV, "OPEN")
    assert growth_status() == "open" and growth_is_open() is True

    monkeypatch.setenv(CAMPUS_CATALOG_GROWTH_ENV, " paused ")
    assert growth_status() == "paused"

    # Refuse rather than ignore: guessing here either grows a frozen catalog or blocks a run the
    # operator believes is open, and both look like "the setting did nothing".
    monkeypatch.setenv(CAMPUS_CATALOG_GROWTH_ENV, "yes")
    with pytest.raises(ValueError) as error:
        growth_status()
    assert CAMPUS_CATALOG_GROWTH_ENV in str(error.value)
    assert "open" in str(error.value) and "paused" in str(error.value)


class _NeverTouchedRepository:
    """Fails the test if the paused path touches the database at all."""

    def __getattr__(self, name: str):  # pragma: no cover - only reached on a regression
        raise AssertionError(f"paused ingestion touched the repository: {name}")


class _NeverTouchedService:
    def __getattr__(self, name: str):  # pragma: no cover - only reached on a regression
        raise AssertionError(f"paused ingestion touched the ingestion service: {name}")


def test_ingest_course_refuses_while_paused_before_reading_or_writing(
    tmp_path: pathlib.Path,
) -> None:
    """The refusal is at the door: no source file is read and no row is written."""
    source = tmp_path / "canvas"
    source.mkdir()
    payload = source / "lecture.md"
    payload.write_text("# Clustering\n\nDBSCAN groups points by density.\n", encoding="utf-8")
    import hashlib

    row = InventoryRow(
        source_root=str(source),
        institution_origin="https://cityu-dg.instructure.com",
        course_id="628",
        course_code="IP3902",
        course_name="社会实践",
        term="Summer Term 2026",
        summary_category="",
        relative_path="lecture.md",
        filename="lecture.md",
        bytes_disk=payload.stat().st_size,
        sha256=hashlib.sha256(payload.read_bytes()).hexdigest(),
        mime_guess="text/markdown",
        parse_class="PARSEABLE",
        classification="ACADEMIC_TEACHING",
        classification_reason="test",
        disk_status="PRESENT",
        publication_basis="OWNER_PLATFORM_IMPORT_INTENT_RIGHTS_UNVERIFIED",
        review_status="NEEDS_REVIEW",
    )
    (course_plan,) = plan([row]).values()

    from app.campus_ingestion import ingest_course

    with pytest.raises(CampusCatalogGrowthPaused):
        ingest_course(
            course_plan,
            service=_NeverTouchedService(),  # type: ignore[arg-type]
            repository=_NeverTouchedRepository(),  # type: ignore[arg-type]
            target_course_id="campus-628",
        )


def test_the_ingest_cli_refuses_while_paused_with_its_own_exit_code(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sys.path.insert(0, str(SCRIPTS))
    try:
        import ingest_campus_course as ingest_cli
    finally:
        sys.path.remove(str(SCRIPTS))
    code = ingest_cli.main([
        "--plan", str(tmp_path / "missing-plan.json"),
        "--course", "628",
        "--database", str(tmp_path / "rag.sqlite3"),
        "--uploads", str(tmp_path / "uploads"),
        "--report", str(tmp_path / "report.json"),
    ])
    # 3, not 2: the pause is checked before the plan, so a closed catalog cannot look like a
    # missing file, and the operator is told which control reopens it.
    assert code == 3
    assert CLOSURE_RECORD in capsys.readouterr().err


def test_the_scan_cli_refuses_before_walking_a_source_root(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sys.path.insert(0, str(SCRIPTS))
    try:
        import scan_campus_inventory as scan
    finally:
        sys.path.remove(str(SCRIPTS))

    def _explode(*_args, **_kwargs):  # pragma: no cover - only reached on a regression
        raise AssertionError("a paused scan walked a source root")

    monkeypatch.setattr(scan, "scan_root", _explode)
    monkeypatch.setattr(sys, "argv", [
        "scan_campus_inventory.py",
        "--root", str(tmp_path),
        "--out", str(tmp_path / "inventory.csv"),
    ])
    assert scan.main() == 3
    assert CLOSURE_RECORD in capsys.readouterr().err
    assert not (tmp_path / "inventory.csv").exists()


def test_a_private_upload_still_works_while_growth_is_closed(tmp_path: pathlib.Path) -> None:
    """The pause closes one directory-driven growth path; it does not close the product."""
    ingestor, connection = service(tmp_path)
    ingestor.create_course(
        CourseCreate(id="private-course", name="我的课程", description="user upload"),
        owner_user_id="user-1",
        is_admin=False,
        publication_status=PublicationStatus.PRIVATE,
    )
    accepted = ingestor.queue_document(
        course_id="private-course",
        filename="my-notes.md",
        media_type="text/markdown",
        content=b"# My notes\n\nA private upload while the campus catalog is closed.\n",
        owner_user_id="user-1",
        is_admin=False,
    )
    ingestor.process_document(accepted.document.id, accepted.job.id)
    document = ingestor.get_document(accepted.document.id)

    assert growth_status() == "paused"
    assert document.chunk_count > 0
    assert connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
    # Nothing here is campus material: the private path never consults the growth gate.
    assert connection.execute("SELECT COUNT(*) FROM campus_material_records").fetchone()[0] == 0


def test_a_course_refusal_names_the_real_cause(tmp_path: pathlib.Path) -> None:
    """Found while writing the test above: every integrity failure was reported as a duplicate.

    An ownerless private course fails a NOT NULL, and the old handler turned that into
    `409 COURSE_EXISTS` 鈥?a cause that is false *and* that the caller acts on, because
    `ui_extension/domain.py` retries `COURSE_EXISTS` three times with fresh random ids.
    """
    ingestor, _connection = service(tmp_path)
    with pytest.raises(ApiError) as ownerless:
        ingestor.create_course(
            CourseCreate(id="ownerless", name="x", description="y"),
            is_admin=False,
            publication_status=PublicationStatus.PRIVATE,
        )
    assert ownerless.value.code == "COURSE_OWNER_REQUIRED"
    assert ownerless.value.status_code == 422

    ingestor.create_course(
        CourseCreate(id="taken", name="x", description="y"),
        owner_user_id="user-1",
        is_admin=False,
        publication_status=PublicationStatus.PRIVATE,
    )
    with pytest.raises(ApiError) as duplicate:
        ingestor.create_course(
            CourseCreate(id="taken", name="x", description="y"),
            owner_user_id="user-1",
            is_admin=False,
            publication_status=PublicationStatus.PRIVATE,
        )
    assert duplicate.value.code == "COURSE_EXISTS" and duplicate.value.status_code == 409
