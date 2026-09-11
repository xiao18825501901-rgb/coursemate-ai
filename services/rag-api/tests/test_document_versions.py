import sqlite3
from pathlib import Path

import pytest
from test_learning_journey import setup_workspace
from test_learning_workspace import client_at

from app.config import Settings
from app.db import Database


def test_v3_migration_backfills_immutable_document_and_chunk_versions(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "rag.sqlite3"
    upload_dir = tmp_path / "uploads"
    source = upload_dir / "official" / "cs3481" / "doc-existing.txt"
    source.parent.mkdir(parents=True)
    source.write_text("existing versioned course content", encoding="utf-8")
    v2_database = Database(
        Settings(database_path=database_path, upload_dir=upload_dir)
    )
    v2_database.initialize()
    with v2_database.connect() as connection:
        connection.execute(
            "INSERT INTO courses(id,name,description) VALUES('cs3481','CS3481','')"
        )
        connection.execute(
            """
            INSERT INTO documents(
                id,course_id,filename,stored_path,media_type,extension,sha256,
                byte_size,status
            ) VALUES('doc-existing','cs3481','existing.txt',?,'text/plain','.txt',?,?,'ready')
            """,
            (str(source), "a" * 64, source.stat().st_size),
        )
        connection.execute(
            """
            INSERT INTO chunks(
                id,document_id,course_id,ordinal,content,locator_type,
                locator_value,embedding
            ) VALUES('chunk-existing','doc-existing','cs3481',0,'existing content',
                     'section','Document','[1.0]')
            """
        )

    v3_database = Database(
        Settings(
            database_path=database_path,
            upload_dir=upload_dir,
            v3_enabled=True,
        )
    )
    v3_database.initialize()
    v3_database.initialize()

    with v3_database.connect() as connection:
        version = connection.execute(
            "SELECT * FROM document_versions WHERE document_id='doc-existing'"
        ).fetchone()
        chunk_version = connection.execute(
            "SELECT document_version_id FROM chunk_source_versions "
            "WHERE chunk_id='chunk-existing'"
        ).fetchone()
        versions = [
            row[0]
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]

        assert version is not None
        assert version["version"] == 1
        assert version["source_scope"] == "OFFICIAL"
        assert version["owner_user_id"] is None
        assert version["sha256"] == "a" * 64
        assert version["stored_path"] == str(source)
        assert chunk_version["document_version_id"] == version["id"]
        assert versions == list(range(1, 14))

        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE document_versions SET filename='changed.txt' WHERE id=?",
                (version["id"],),
            )


def test_workspace_upload_records_owner_scoped_source_version(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace, _ = setup_workspace(client)
        uploaded = client.post(
            f"/api/learning/workspaces/{workspace['id']}/documents",
            files={"file": ("private.txt", b"private version", "text/plain")},
        )
        assert uploaded.status_code == 202, uploaded.text
        document_id = uploaded.json()["document"]["id"]

        metadata = client.get(f"/api/learning/documents/{document_id}")
        assert metadata.status_code == 200, metadata.text
        body = metadata.json()
        assert body["version_number"] == 1
        assert body["source_scope"] == "WORKSPACE_PRIVATE"
        assert body["owner_user_id"] is None
        assert body["version_id"].endswith("-v1")

        listed = client.get(
            f"/api/learning/workspaces/{workspace['id']}/documents?scope=mine"
        )
        assert listed.status_code == 200, listed.text
        listed_document = listed.json()["data"][0]
        assert listed_document["version_id"] == body["version_id"]
        assert listed_document["source_scope"] == "WORKSPACE_PRIVATE"
        assert listed_document["access_scope"] == "OWNER_PRIVATE"
        assert listed_document["preview"]["kind"] == "SAFE_TEXT"

        with client.app.state.database.connect() as connection:
            stored = connection.execute(
                "SELECT owner_user_id,source_scope FROM document_versions "
                "WHERE id=?",
                (body["version_id"],),
            ).fetchone()
        assert tuple(stored) == ("a", "WORKSPACE_PRIVATE")

        for principal in ("b", "admin"):
            client.headers["Authorization"] = f"Bearer {principal}"
            denied = client.get(f"/api/learning/documents/{document_id}")
            missing = client.get("/api/learning/documents/missing")
            assert denied.status_code == 404
            assert denied.json() == missing.json()


def test_mutable_document_row_cannot_reclassify_a_private_source_version(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace, _ = setup_workspace(client)
        uploaded = client.post(
            f"/api/learning/workspaces/{workspace['id']}/documents",
            files={"file": ("private.txt", b"owner only", "text/plain")},
        )
        assert uploaded.status_code == 202, uploaded.text
        document_id = uploaded.json()["document"]["id"]
        with client.app.state.database.connect() as connection:
            connection.execute(
                "UPDATE documents SET course_id='cs3481' WHERE id=?",
                (document_id,),
            )

        for principal in ("b", "admin"):
            client.headers["Authorization"] = f"Bearer {principal}"
            denied = client.get(f"/api/learning/documents/{document_id}/content")
            missing = client.get("/api/learning/documents/missing/content")
            assert denied.status_code == 404
            assert denied.json() == missing.json()


def test_workspace_listing_uses_frozen_source_scope_not_mutable_document_course(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace, _ = setup_workspace(client)
        uploaded = client.post(
            f"/api/learning/workspaces/{workspace['id']}/documents",
            files={"file": ("private.txt", b"owner only", "text/plain")},
        )
        assert uploaded.status_code == 202, uploaded.text
        document_id = uploaded.json()["document"]["id"]
        with client.app.state.database.connect() as connection:
            connection.execute(
                "UPDATE documents SET course_id='cs3481' WHERE id=?",
                (document_id,),
            )

        owner_private = client.get(
            f"/api/learning/workspaces/{workspace['id']}/documents?scope=mine"
        )
        assert [row["id"] for row in owner_private.json()["data"]] == [document_id]

        client.headers["Authorization"] = "Bearer b"
        other_response = client.post(
            "/api/learning/workspaces", json={"course_id": "cs3481"}
        )
        assert other_response.status_code == 200, other_response.text
        other_workspace = other_response.json()
        other_official = client.get(
            f"/api/learning/workspaces/{other_workspace['id']}/documents?scope=official"
        )
        assert other_official.status_code == 200, other_official.text
        assert document_id not in {row["id"] for row in other_official.json()["data"]}


def test_version_routes_keep_frozen_source_identity_and_acl(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace, _ = setup_workspace(client)
        uploaded = client.post(
            f"/api/learning/workspaces/{workspace['id']}/documents",
            files={"file": ("frozen.txt", b"immutable source", "text/plain")},
        )
        assert uploaded.status_code == 202, uploaded.text
        document_id = uploaded.json()["document"]["id"]
        current = client.get(f"/api/learning/documents/{document_id}").json()
        version_id = current["version_id"]
        with client.app.state.database.connect() as connection:
            connection.execute(
                "UPDATE documents SET filename='mutable.txt',sha256=? WHERE id=?",
                ("f" * 64, document_id),
            )

        version = client.get(f"/api/learning/document-versions/{version_id}")
        assert version.status_code == 200, version.text
        assert version.json()["id"] == version_id
        assert version.json()["document_id"] == document_id
        assert version.json()["filename"] == "frozen.txt"
        assert version.json()["sha256"] == current["version"]
        assert version.json()["source_scope"] == "WORKSPACE_PRIVATE"
        assert version.json()["access_scope"] == "OWNER_PRIVATE"
        assert version.json()["owner_user_id"] is None

        content = client.get(f"/api/learning/document-versions/{version_id}/content")
        assert content.status_code == 200
        assert content.content == b"immutable source"
        assert content.headers["content-disposition"].startswith("inline")
        ranged = client.get(
            f"/api/learning/document-versions/{version_id}/content",
            headers={"Range": "bytes=0-8"},
        )
        assert ranged.status_code == 206
        assert ranged.content == b"immutable"
        preview = client.get(f"/api/learning/document-versions/{version_id}/preview")
        assert preview.json()["text"] == "immutable source"

        for principal in ("b", "admin"):
            client.headers["Authorization"] = f"Bearer {principal}"
            denied = client.get(f"/api/learning/document-versions/{version_id}")
            missing = client.get("/api/learning/document-versions/missing")
            assert denied.status_code == 404
            assert denied.json() == missing.json()


def test_upload_database_failure_removes_uncommitted_private_file(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace, _ = setup_workspace(client)
        with client.app.state.database.connect() as connection:
            connection.execute(
                """
                CREATE TRIGGER reject_test_document
                BEFORE INSERT ON documents
                BEGIN
                    SELECT RAISE(ABORT, 'simulated database failure');
                END
                """
            )

        with pytest.raises(sqlite3.IntegrityError, match="simulated database failure"):
            client.app.state.ingestion_service.queue_document(
                course_id=workspace["private_course_id"],
                filename="not-committed.txt",
                media_type="text/plain",
                content=b"must not remain on disk",
                owner_user_id="a",
                is_admin=False,
            )

        stored_files = [
            path
            for path in client.app.state.settings.upload_dir.rglob("*")
            if path.is_file()
        ]
        assert not stored_files
        with client.app.state.database.connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0


def test_reviewed_owner_course_sources_are_shared_then_revoked_on_unpublish(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        client.headers["Authorization"] = "Bearer a"
        created = client.post(
            "/api/courses", json={"id": "reviewed-course", "name": "Reviewed"}
        )
        assert created.status_code == 201, created.text
        uploaded = client.post(
            "/api/courses/reviewed-course/documents",
            files={"file": ("shared.txt", b"reviewed shared source", "text/plain")},
        )
        assert uploaded.status_code == 202, uploaded.text
        document_id = uploaded.json()["document"]["id"]
        requested = client.post(
            "/api/courses/reviewed-course/publication-requests",
            json={
                "shareMaterialsConsent": True,
                "rightsConfirmation": True,
                "consentVersion": "v1",
            },
        )
        assert requested.status_code == 201, requested.text
        client.headers["Authorization"] = "Bearer admin"
        approved = client.post(
            f"/api/admin/publication-requests/{requested.json()['id']}/review",
            json={"decision": "approve", "reviewNote": "Test approval"},
        )
        assert approved.status_code == 200, approved.text

        client.headers["Authorization"] = "Bearer b"
        joined = client.post(
            "/api/learning/workspaces", json={"course_id": "reviewed-course"}
        )
        assert joined.status_code == 200, joined.text
        workspace = joined.json()
        listed = client.get(
            f"/api/learning/workspaces/{workspace['id']}/documents?scope=official"
        )
        assert [row["id"] for row in listed.json()["data"]] == [document_id]
        assert listed.json()["data"][0]["access_scope"] == "REVIEWED_SHARED"
        from app.learning.workspaces import workspace_for

        learning = client.app.state.learning
        evidence = learning.evidence(
            workspace_for(learning.db, workspace["id"], "b"), "reviewed"
        )
        assert evidence[0]["document_id"] == document_id
        assert evidence[0]["source_scope"] == "OWNER_COURSE"
        shared = client.get(f"/api/learning/documents/{document_id}/content")
        assert shared.status_code == 200
        assert shared.content == b"reviewed shared source"

        client.headers["Authorization"] = "Bearer admin"
        unpublished = client.delete("/api/admin/courses/reviewed-course/publication")
        assert unpublished.status_code == 204
        client.headers["Authorization"] = "Bearer b"
        denied = client.get(f"/api/learning/documents/{document_id}/content")
        missing = client.get("/api/learning/documents/missing/content")
        assert denied.status_code == 404
        assert denied.json() == missing.json()
