from __future__ import annotations

import json
import pathlib
import sqlite3
import sys

import pytest

SCRIPTS = pathlib.Path(__file__).resolve().parents[3] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import publish_campus_catalog as publication  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.rag.embeddings import DeterministicEmbeddingProvider  # noqa: E402
from app.services.ingestion import IngestionService  # noqa: E402


def _plan(root: pathlib.Path, *, digest: str) -> dict:
    source = root / "course"
    source.mkdir()
    (source / "lecture.txt").write_text("lecture evidence", encoding="utf-8")
    (source / "lecture-copy.txt").write_text("lecture evidence", encoding="utf-8")
    return {
        "schemaVersion": "coursejesus.campus-ingestion-plan.v1",
        "courses": [
            {
                "institutionOrigin": "https://cityu-dg.instructure.com",
                "courseId": "629",
                "courseCode": "GE2324",
                "courseName": "Art and Science of Data",
                "term": "Semester A",
                "sourceRoot": str(root),
                "files": [
                    {
                        "filename": "lecture.txt",
                        "relativePath": "course/lecture.txt",
                        "sha256": digest,
                        "bytes": len(b"lecture evidence"),
                        "classification": "ACADEMIC_TEACHING",
                        "parseClass": "PARSEABLE",
                        "diskStatus": "PRESENT",
                        "publicationBasis": "RIGHTS_UNVERIFIED",
                        "status": "INGESTABLE",
                        "reason": "academic teaching material",
                        "review_status": "NEEDS_REVIEW",
                    },
                    {
                        "filename": "lecture-copy.txt",
                        "relativePath": "course/lecture-copy.txt",
                        "sha256": digest,
                        "bytes": len(b"lecture evidence"),
                        "classification": "ACADEMIC_TEACHING",
                        "parseClass": "PARSEABLE",
                        "diskStatus": "PRESENT",
                        "publicationBasis": "RIGHTS_UNVERIFIED",
                        "status": "INGESTABLE",
                        "reason": "academic teaching material",
                        "review_status": "NEEDS_REVIEW",
                    },
                    {
                        "filename": "student-list.xlsx",
                        "relativePath": "course/student-list.xlsx",
                        "sha256": "b" * 64,
                        "bytes": 10,
                        "classification": "PERSONAL_OR_RESTRICTED",
                        "parseClass": "PARSEABLE",
                        "diskStatus": "PRESENT",
                        "publicationBasis": "RIGHTS_UNVERIFIED",
                        "status": "BLOCKED",
                        "reason": "PERSONAL_OR_RESTRICTED",
                        "review_status": "NOT_FOR_PUBLICATION",
                    },
                ],
            },
            {
                "institutionOrigin": "https://canvas.cityu.edu.hk",
                "courseId": "50961",
                "courseCode": "",
                "courseName": "CS Announcement",
                "term": "",
                "sourceRoot": str(root),
                "files": [
                    {
                        "filename": "notice.pdf",
                        "relativePath": "notice.pdf",
                        "sha256": "c" * 64,
                        "bytes": 10,
                        "classification": "INFORMATION",
                        "parseClass": "PARSEABLE",
                        "diskStatus": "PRESENT",
                        "publicationBasis": "RIGHTS_UNVERIFIED",
                        "status": "BLOCKED",
                        "reason": "NOT_COURSE_MATERIAL: INFORMATION",
                        "review_status": "NOT_FOR_PUBLICATION",
                    }
                ],
            },
            {
                "institutionOrigin": "https://cityu-dg.instructure.com",
                "courseId": "214",
                "courseCode": "PE1911",
                "courseName": "Physical Education I",
                "term": "Semester A",
                "sourceRoot": str(root),
                "files": [],
            },
        ],
    }


def _ledger(path: pathlib.Path, *, digest: str) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE campus_material_records(
          institution_origin TEXT, canvas_course_id TEXT, sha256 TEXT,
          decision TEXT, document_id TEXT
        );
        CREATE TABLE documents(id TEXT PRIMARY KEY, status TEXT, chunk_count INTEGER);
        INSERT INTO campus_material_records VALUES(
          'https://cityu-dg.instructure.com','629','%s','INGESTABLE','doc-ready'
        );
        INSERT INTO documents VALUES('doc-ready','ready',2);
        """
        % digest
    )
    connection.commit()
    connection.close()


def test_prepare_freezes_courses_reuses_content_and_withholds_private_rows(
    tmp_path: pathlib.Path,
) -> None:
    digest = publication.sha256_bytes(b"lecture evidence")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_plan(tmp_path, digest=digest)), encoding="utf-8")
    ledger_path = tmp_path / "ledger.sqlite3"
    _ledger(ledger_path, digest=digest)
    bundle = tmp_path / "bundle"

    manifest = publication.prepare_bundle(
        plan_path=plan_path,
        ledger_path=ledger_path,
        bundle_dir=bundle,
        operation_id="campus-publication-test",
    )

    assert [course["targetCourseId"] for course in manifest["courses"]] == [
        "ge2324",
        publication.target_course_id("https://cityu-dg.instructure.com", "214"),
    ]
    assert manifest["excludedContainers"] == [
        {"courseId": "50961", "name": "CS Announcement", "reason": "INFORMATION_ONLY"}
    ]
    ge_files = manifest["courses"][0]["files"]
    assert [item["action"] for item in ge_files] == ["INDEX", "REUSE", "WITHHELD"]
    assert ge_files[0]["bundlePath"] == ge_files[1]["bundlePath"]
    assert (bundle / ge_files[0]["bundlePath"]).read_bytes() == b"lecture evidence"
    assert ge_files[2]["reviewStatus"] == "NOT_FOR_PUBLICATION"
    assert manifest["summary"]["courses"] == 2
    assert manifest["summary"]["indexFiles"] == 1
    assert manifest["summary"]["withheldFiles"] == 1
    assert (bundle / "manifest.json").is_file()


def test_prepare_refuses_an_ingestable_file_without_a_successful_ledger_result(
    tmp_path: pathlib.Path,
) -> None:
    digest = publication.sha256_bytes(b"lecture evidence")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_plan(tmp_path, digest=digest)), encoding="utf-8")
    ledger_path = tmp_path / "ledger.sqlite3"
    connection = sqlite3.connect(ledger_path)
    connection.executescript(
        "CREATE TABLE campus_material_records(institution_origin TEXT,canvas_course_id TEXT,"
        "sha256 TEXT,decision TEXT,document_id TEXT);"
        "CREATE TABLE documents(id TEXT PRIMARY KEY,status TEXT,chunk_count INTEGER);"
    )
    connection.close()

    with pytest.raises(publication.PublicationBundleError, match="no successful ledger result"):
        publication.prepare_bundle(
            plan_path=plan_path,
            ledger_path=ledger_path,
            bundle_dir=tmp_path / "bundle",
            operation_id="campus-publication-test",
        )


def test_manifest_hash_rejects_changes_after_freeze(tmp_path: pathlib.Path) -> None:
    digest = publication.sha256_bytes(b"lecture evidence")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_plan(tmp_path, digest=digest)), encoding="utf-8")
    ledger_path = tmp_path / "ledger.sqlite3"
    _ledger(ledger_path, digest=digest)
    manifest = publication.prepare_bundle(
        plan_path=plan_path,
        ledger_path=ledger_path,
        bundle_dir=tmp_path / "bundle",
        operation_id="campus-publication-test",
    )
    publication.verify_manifest(manifest)

    manifest["courses"][0]["name"] = "changed after freeze"
    with pytest.raises(publication.PublicationBundleError, match="manifest hash"):
        publication.verify_manifest(manifest)


class _BatchRecorder:
    def __init__(self) -> None:
        self.opened: list[dict] = []
        self.items: list[dict] = []
        self.sealed: list[dict] = []

    def begin_upload_batch(self, **values):
        self.opened.append(values)
        return {"status": "OPEN", **values}

    def record_upload_batch_item(self, **values):
        self.items.append(values)

    def seal_upload_batch(self, **values):
        self.sealed.append(values)
        return {"status": "SEALED", **values}


def _database(tmp_path: pathlib.Path) -> tuple[Database, IngestionService]:
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        app_env="test",
        v3_enabled=True,
        rag_provider_mode="deterministic",
        ui_web_dir=tmp_path / "web",
    )
    database = Database(settings)
    database.initialize()
    return database, IngestionService(database, settings, DeterministicEmbeddingProvider())


def test_import_is_private_idempotent_and_seals_one_batch_per_course(
    tmp_path: pathlib.Path,
) -> None:
    digest = publication.sha256_bytes(b"lecture evidence")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_plan(tmp_path, digest=digest)), encoding="utf-8")
    ledger_path = tmp_path / "ledger.sqlite3"
    _ledger(ledger_path, digest=digest)
    bundle = tmp_path / "bundle"
    manifest = publication.prepare_bundle(
        plan_path=plan_path,
        ledger_path=ledger_path,
        bundle_dir=bundle,
        operation_id="campus-publication-test",
    )
    database, ingestion = _database(tmp_path / "runtime")
    batches = _BatchRecorder()

    first = publication.import_bundle(
        bundle_dir=bundle,
        database=database,
        ingestion=ingestion,
        auto_map=batches,
        receipt_path=tmp_path / "receipt-first.json",
    )
    second = publication.import_bundle(
        bundle_dir=bundle,
        database=database,
        ingestion=ingestion,
        auto_map=_BatchRecorder(),
        receipt_path=tmp_path / "receipt-second.json",
    )

    with database.connect() as connection:
        ge = connection.execute("SELECT * FROM courses WHERE id='ge2324'").fetchone()
        pe = connection.execute(
            "SELECT * FROM courses WHERE id=?",
            (publication.target_course_id("https://cityu-dg.instructure.com", "214"),),
        ).fetchone()
        assert ge["visibility"] == "private"
        assert ge["publication_status"] == "private"
        assert pe["visibility"] == "private"
        assert connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] > 0
        rows = connection.execute(
            "SELECT decision,review_status,usage_rights FROM campus_material_records "
            "ORDER BY relative_path"
        ).fetchall()
    assert [row["decision"] for row in rows] == ["INGESTABLE", "INGESTABLE", "BLOCKED"]
    assert rows[0]["review_status"] == publication.APPROVED_REVIEW_STATUS
    assert rows[0]["usage_rights"] == "UNVERIFIED"
    assert rows[2]["review_status"] == publication.WITHHELD_REVIEW_STATUS
    assert len(batches.opened) == len(batches.sealed) == 1
    assert len(batches.items) == 1
    assert first["summary"]["indexed"] == 1
    assert second["summary"]["existing"] == 1


def test_import_preserves_an_immutable_published_release_and_records_new_sources(
    tmp_path: pathlib.Path,
) -> None:
    digest = publication.sha256_bytes(b"lecture evidence")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_plan(tmp_path, digest=digest)), encoding="utf-8")
    ledger_path = tmp_path / "ledger.sqlite3"
    _ledger(ledger_path, digest=digest)
    bundle = tmp_path / "bundle"
    publication.prepare_bundle(
        plan_path=plan_path,
        ledger_path=ledger_path,
        bundle_dir=bundle,
        operation_id="campus-publication-test",
    )
    database, ingestion = _database(tmp_path / "runtime")
    ingestion.create_course(
        publication.course_create("ge2324", "Existing GE2324", "published release"),
        is_admin=True,
        publication_status=publication.PublicationStatus.PUBLISHED,
    )
    batches = _BatchRecorder()

    receipt = publication.import_bundle(
        bundle_dir=bundle,
        database=database,
        ingestion=ingestion,
        auto_map=batches,
        receipt_path=tmp_path / "receipt.json",
    )

    with database.connect() as connection:
        course = connection.execute("SELECT * FROM courses WHERE id='ge2324'").fetchone()
        records = connection.execute(
            "SELECT relative_path,decision,document_id FROM campus_material_records "
            "WHERE target_course_id='ge2324' ORDER BY relative_path"
        ).fetchall()
        assert connection.execute(
            "SELECT COUNT(*) FROM documents WHERE course_id='ge2324'"
        ).fetchone()[0] == 0
    assert course["visibility"] == "public"
    assert course["publication_status"] == "published"
    assert [row["decision"] for row in records] == [
        "DOWNLOAD_ONLY",
        "DOWNLOAD_ONLY",
        "BLOCKED",
    ]
    assert all(row["document_id"] is None for row in records)
    assert batches.opened == batches.items == batches.sealed == []
    assert receipt["summary"]["lockedReleaseSkipped"] == 2
    assert receipt["courses"][0]["lockedReleaseSkipped"] == 2


def test_activation_is_atomic_and_requires_terminal_auto_map_state(
    tmp_path: pathlib.Path,
) -> None:
    database, ingestion = _database(tmp_path)
    target = publication.target_course_id("https://cityu-dg.instructure.com", "214")
    ingestion.create_course(
        publication.course_create(target, "Physical Education I", "campus"),
        is_admin=True,
        publication_status=publication.private_publication_status(),
    )
    manifest = {
        "schemaVersion": publication.SCHEMA_VERSION,
        "operationId": "activation-test",
        "courses": [
            {
                "targetCourseId": target,
                "sourceCourseId": "214",
                "name": "Physical Education I",
                "files": [],
            }
        ],
        "excludedContainers": [],
        "summary": {},
    }
    manifest["manifestSha256"] = publication.freeze_manifest(manifest)
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO auto_knowledge_targets(target_key,course_id,target_kind,status,message) "
            "VALUES(?,?,'AUTO_COURSE','BUILDING','still building')",
            (f"AUTO_COURSE:{target}", target),
        )

    with pytest.raises(publication.PublicationBundleError, match="not terminal"):
        publication.activate_catalog(database=database, manifest=manifest)
    with database.connect() as connection:
        assert connection.execute(
            "SELECT visibility FROM courses WHERE id=?", (target,)
        ).fetchone()[0] == "private"
        connection.execute(
            "UPDATE auto_knowledge_targets SET status='WAITING_SOURCE' WHERE target_key=?",
            (f"AUTO_COURSE:{target}",),
        )

    result = publication.activate_catalog(database=database, manifest=manifest)
    with database.connect() as connection:
        course = connection.execute("SELECT * FROM courses WHERE id=?", (target,)).fetchone()
    assert course["visibility"] == "public"
    assert course["publication_status"] == "published"
    assert result == {"activated": 1, "alreadyPublished": 0}
