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
