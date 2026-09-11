import base64
import hashlib
import io
import json
import zipfile
from pathlib import Path

from test_learning_workspace import client_at, join

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUB"
    "AScY42YAAAAASUVORK5CYII="
)


def office_zip(*entries: tuple[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        archive.writestr("word/document.xml", b"<document/>")
        for name, value in entries:
            archive.writestr(name, value)
    return output.getvalue()


def workspace_for_preview(client) -> dict[str, object]:
    client.headers["Authorization"] = "Bearer admin"
    created = client.post(
        "/api/courses", json={"id": "cs3481", "name": "CS3481"}
    )
    assert created.status_code == 201, created.text
    return join(client)


def upload(client, workspace_id: str, filename: str, content: bytes, media: str) -> str:
    response = client.post(
        f"/api/learning/workspaces/{workspace_id}/documents",
        files={"file": (filename, content, media)},
    )
    assert response.status_code == 202, response.text
    return response.json()["document"]["id"]


def test_safe_text_csv_notebook_and_image_previews_are_bounded_data(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace = workspace_for_preview(client)
        workspace_id = str(workspace["id"])
        text_id = upload(
            client,
            workspace_id,
            "notes.md",
            b"# Notes\n<script>alert('not executable')</script>",
            "text/markdown",
        )
        csv_id = upload(
            client,
            workspace_id,
            "scores.csv",
            b"name,value\nalice,=2+2\nbob,3\n",
            "text/csv",
        )
        notebook = {
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {},
            "cells": [
                {
                    "cell_type": "code",
                    "source": ["raise RuntimeError('must never run')"],
                    "execution_count": 7,
                    "metadata": {},
                    "outputs": [
                        {
                            "output_type": "display_data",
                            "data": {
                                "text/html": "<script>bad()</script>",
                                "text/plain": ["stored output only"],
                            },
                            "metadata": {},
                        }
                    ],
                }
            ],
        }
        notebook_id = upload(
            client,
            workspace_id,
            "analysis.ipynb",
            json.dumps(notebook).encode(),
            "application/x-ipynb+json",
        )
        image_id = upload(client, workspace_id, "pixel.png", PNG_1X1, "image/png")

        text_preview = client.get(f"/api/learning/documents/{text_id}/preview")
        assert text_preview.status_code == 200, text_preview.text
        assert text_preview.json() == {
            "kind": "SAFE_TEXT",
            "text": "# Notes\n<script>alert('not executable')</script>",
            "truncated": False,
        }
        assert text_preview.headers["content-type"].startswith("application/json")

        csv_preview = client.get(f"/api/learning/documents/{csv_id}/preview")
        assert csv_preview.status_code == 200, csv_preview.text
        assert csv_preview.json()["columns"] == ["name", "value"]
        assert csv_preview.json()["rows"] == [["alice", "=2+2"], ["bob", "3"]]
        assert csv_preview.json()["truncated"] is False

        notebook_preview = client.get(
            f"/api/learning/documents/{notebook_id}/preview"
        )
        assert notebook_preview.status_code == 200, notebook_preview.text
        body = notebook_preview.json()
        assert body["kind"] == "NOTEBOOK_PREVIEW"
        assert body["executed"] is False
        assert body["cells"][0]["source"] == "raise RuntimeError('must never run')"
        assert body["cells"][0]["outputs"] == ["stored output only"]
        assert "<script>" not in notebook_preview.text

        image_metadata = client.get(
            f"/api/learning/documents/{image_id}"
        ).json()
        assert image_metadata["preview"] == {
            "kind": "INLINE_ORIGINAL",
            "available": True,
            "reason": None,
        }
        image = client.get(f"/api/learning/documents/{image_id}/content")
        assert image.status_code == 200
        assert image.content == PNG_1X1
        assert image.headers["content-type"] == "image/png"
        assert image.headers["content-disposition"].startswith("inline")


def test_office_without_converter_is_truthful_download_only(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace = workspace_for_preview(client)
        document_id = upload(
            client,
            str(workspace["id"]),
            "legacy.doc",
            bytes.fromhex("D0CF11E0A1B11AE1") + b"safe fixture",
            "application/msword",
        )

        metadata = client.get(f"/api/learning/documents/{document_id}").json()
        assert metadata["preview"] == {
            "kind": "DOWNLOAD_ONLY",
            "available": False,
            "reason": "CONTROLLED_CONVERTER_NOT_CONFIGURED",
        }
        preview = client.get(f"/api/learning/documents/{document_id}/preview")
        assert preview.status_code == 409
        assert preview.json()["error"]["code"] == "PREVIEW_NOT_AVAILABLE"
        original = client.get(f"/api/learning/documents/{document_id}/content")
        assert original.status_code == 200
        assert original.headers["content-disposition"].startswith("attachment")
        assert original.headers["x-content-type-options"] == "nosniff"


def test_ooxml_upload_rejects_invalid_archives_traversal_macros_and_zip_bombs(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace = workspace_for_preview(client)
        endpoint = f"/api/learning/workspaces/{workspace['id']}/documents"
        cases = [
            ("fake.docx", b"PK-not-a-zip", "INVALID_FILE_CONTENT"),
            (
                "traversal.docx",
                office_zip(("../escape.txt", b"escape")),
                "UNSAFE_OFFICE_ARCHIVE",
            ),
            (
                "duplicate.docx",
                office_zip(("[content_types].xml", b"duplicate")),
                "UNSAFE_OFFICE_ARCHIVE",
            ),
            (
                "macro.docx",
                office_zip(("word/vbaProject.bin", b"macro")),
                "OFFICE_MACROS_NOT_ALLOWED",
            ),
            (
                "bomb.docx",
                office_zip(("word/media/payload.bin", b"0" * 2_000_000)),
                "OFFICE_ARCHIVE_LIMIT_EXCEEDED",
            ),
        ]
        for filename, content, code in cases:
            response = client.post(
                endpoint,
                files={
                    "file": (
                        filename,
                        content,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
            )
            assert response.status_code == 400, (filename, response.text)
            assert response.json()["error"]["code"] == code

        valid = client.post(
            endpoint,
            files={
                "file": (
                    "valid.docx",
                    office_zip(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        assert valid.status_code == 202, valid.text


def test_preview_limits_and_malformed_inputs_fail_safely(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace = workspace_for_preview(client)
        workspace_id = str(workspace["id"])
        rows = b"name,value\n" + b"".join(
            f"row-{index},{index}\n".encode() for index in range(201)
        )
        csv_id = upload(client, workspace_id, "large.csv", rows, "text/csv")
        csv_body = client.get(
            f"/api/learning/documents/{csv_id}/preview"
        ).json()
        assert len(csv_body["rows"]) == 200
        assert csv_body["truncated"] is True

        notebook_id = upload(
            client,
            workspace_id,
            "broken.ipynb",
            b"{not-json",
            "application/x-ipynb+json",
        )
        broken = client.get(f"/api/learning/documents/{notebook_id}/preview")
        assert broken.status_code == 422
        assert broken.json()["error"]["code"] == "PREVIEW_INVALID_NOTEBOOK"
        download = client.get(
            f"/api/learning/documents/{notebook_id}/content?download=true"
        )
        assert download.status_code == 200
        assert download.headers["content-disposition"].startswith("attachment")

        oversized_png_header = (
            b"\x89PNG\r\n\x1a\n"
            + b"\x00\x00\x00\x0dIHDR"
            + (100_000).to_bytes(4, "big")
            + (100_000).to_bytes(4, "big")
        )
        rejected = client.post(
            f"/api/learning/workspaces/{workspace_id}/documents",
            files={"file": ("huge.png", oversized_png_header, "image/png")},
        )
        assert rejected.status_code == 400
        assert rejected.json()["error"]["code"] == "IMAGE_DIMENSIONS_TOO_LARGE"

        extreme_dimension_header = (
            b"\x89PNG\r\n\x1a\n"
            + b"\x00\x00\x00\x0dIHDR"
            + (100_000).to_bytes(4, "big")
            + (1).to_bytes(4, "big")
        )
        rejected_dimension = client.post(
            f"/api/learning/workspaces/{workspace_id}/documents",
            files={"file": ("too-wide.png", extreme_dimension_header, "image/png")},
        )
        assert rejected_dimension.status_code == 400
        assert rejected_dimension.json()["error"]["code"] == "IMAGE_DIMENSIONS_TOO_LARGE"

        truncated_image = client.post(
            f"/api/learning/workspaces/{workspace_id}/documents",
            files={
                "file": (
                    "truncated.png",
                    b"\x89PNG\r\n\x1a\n"
                    + b"\x00\x00\x00\x0dIHDR"
                    + (1).to_bytes(4, "big")
                    + (1).to_bytes(4, "big"),
                    "image/png",
                )
            },
        )
        assert truncated_image.status_code == 400
        assert truncated_image.json()["error"]["code"] == "INVALID_FILE_CONTENT"

        deeply_nested = (
            b'{"cells":[' + b"[" * 1_100 + b"0" + b"]" * 1_100 + b"]}"
        )
        nested_id = upload(
            client,
            workspace_id,
            "deep.ipynb",
            deeply_nested,
            "application/x-ipynb+json",
        )
        nested_preview = client.get(f"/api/learning/documents/{nested_id}/preview")
        assert nested_preview.status_code == 422
        assert nested_preview.json()["error"]["code"] == "PREVIEW_INVALID_NOTEBOOK"


def test_private_preview_and_derived_artifact_share_source_acl(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace = workspace_for_preview(client)
        document_id = upload(
            client,
            str(workspace["id"]),
            "private.txt",
            b"private preview body",
            "text/plain",
        )
        metadata = client.get(f"/api/learning/documents/{document_id}").json()
        artifact_path = (
            client.app.state.settings.upload_dir / "derived" / "preview.pdf"
        )
        artifact_path.parent.mkdir(parents=True)
        artifact_content = b"%PDF-1.4\n% derived fixture"
        artifact_path.write_bytes(artifact_content)
        with client.app.state.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO derived_artifacts(
                    id,document_version_id,kind,status,media_type,stored_path,
                    sha256,byte_size,producer_version
                ) VALUES('artifact-private',?,'PREVIEW_PDF','READY',
                         'application/pdf',?,?,?,'test-converter-v1')
                """,
                (
                    metadata["version_id"],
                    str(artifact_path),
                    hashlib.sha256(artifact_content).hexdigest(),
                    len(artifact_content),
                ),
            )

        owner = client.get("/api/learning/artifacts/artifact-private/content")
        assert owner.status_code == 200
        assert owner.content == artifact_content
        assert owner.headers["content-disposition"].startswith("inline")
        assert client.head("/api/learning/artifacts/artifact-private/content").status_code == 200
        ranged = client.get(
            "/api/learning/artifacts/artifact-private/content",
            headers={"Range": "bytes=0-3"},
        )
        assert ranged.status_code == 206
        assert ranged.content == b"%PDF"

        for principal in ("b", "admin"):
            client.headers["Authorization"] = f"Bearer {principal}"
            denied_preview = client.get(
                f"/api/learning/documents/{document_id}/preview"
            )
            missing_preview = client.get(
                "/api/learning/documents/missing/preview"
            )
            assert denied_preview.status_code == 404
            assert denied_preview.json() == missing_preview.json()
            denied_artifact = client.get(
                "/api/learning/artifacts/artifact-private/content"
            )
            missing_artifact = client.get(
                "/api/learning/artifacts/missing/content"
            )
            assert denied_artifact.status_code == 404
            assert denied_artifact.json() == missing_artifact.json()
            assert (
                client.head("/api/learning/artifacts/artifact-private/content").status_code
                == 404
            )

        client.headers.pop("Authorization")
        protected_urls = (
            f"/api/learning/workspaces/{workspace['id']}/documents",
            f"/api/learning/documents/{document_id}",
            f"/api/learning/documents/{document_id}/preview",
            f"/api/learning/documents/{document_id}/content",
            f"/api/learning/document-versions/{metadata['version_id']}",
            f"/api/learning/document-versions/{metadata['version_id']}/preview",
            "/api/learning/artifacts/artifact-private/content",
        )
        for url in protected_urls:
            assert client.get(url).status_code == 401

        client.headers["Authorization"] = "Bearer a"
        artifact_path.write_bytes(b"tampered")
        unavailable = client.get(
            "/api/learning/artifacts/artifact-private/content"
        )
        assert unavailable.status_code == 410
        assert unavailable.json()["error"]["code"] == "ARTIFACT_UNAVAILABLE"


def test_tampered_original_and_derived_preview_are_not_advertised_as_available(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace = workspace_for_preview(client)
        document_id = upload(
            client,
            str(workspace["id"]),
            "notes.doc",
            bytes.fromhex("D0CF11E0A1B11AE1") + b"safe fixture",
            "application/msword",
        )
        metadata = client.get(f"/api/learning/documents/{document_id}").json()
        artifact_file = client.app.state.settings.upload_dir / "derived" / "notes.pdf"
        artifact_file.parent.mkdir(parents=True)
        artifact_bytes = b"%PDF-1.4\n% safe fixture"
        artifact_file.write_bytes(artifact_bytes)
        with client.app.state.database.connect() as connection:
            version = connection.execute(
                "SELECT * FROM document_versions WHERE id=?",
                (metadata["version_id"],),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO derived_artifacts(
                    id,document_version_id,kind,status,media_type,stored_path,
                    sha256,byte_size,producer_version
                ) VALUES('artifact-office',?,'PREVIEW_PDF','READY',
                         'application/pdf',?,?,?,'test-converter-v1')
                """,
                (
                    metadata["version_id"],
                    str(artifact_file),
                    hashlib.sha256(artifact_bytes).hexdigest(),
                    len(artifact_bytes),
                ),
            )

        initial = client.get(
            f"/api/learning/workspaces/{workspace['id']}/documents?scope=mine"
        ).json()["data"][0]
        assert initial["preview"]["kind"] == "DERIVED_PDF"

        artifact_file.write_bytes(b"tampered artifact")
        original_file = Path(version["stored_path"])
        original_file.write_bytes(b"tampered original")

        listed = client.get(
            f"/api/learning/workspaces/{workspace['id']}/documents?scope=mine"
        ).json()["data"][0]
        assert listed["preview"] == {
            "kind": "DOWNLOAD_ONLY",
            "available": False,
            "reason": "SOURCE_AND_DERIVED_ARTIFACT_UNAVAILABLE",
        }
        details = client.get(f"/api/learning/documents/{document_id}").json()
        assert details["original_status"] == "ORIGINAL_UNAVAILABLE"
        assert details["preview"] == listed["preview"]
        unavailable = client.get(f"/api/learning/documents/{document_id}/content")
        assert unavailable.status_code == 410
        assert unavailable.json()["error"]["code"] == "ORIGINAL_UNAVAILABLE"


def test_same_size_source_tamper_is_rejected_at_metadata_preview_and_content(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace = workspace_for_preview(client)
        document_id = upload(
            client,
            str(workspace["id"]),
            "notes.txt",
            b"trusted source",
            "text/plain",
        )
        metadata = client.get(f"/api/learning/documents/{document_id}").json()
        with client.app.state.database.connect() as connection:
            version = connection.execute(
                "SELECT stored_path FROM document_versions WHERE id=?",
                (metadata["version_id"],),
            ).fetchone()
        source = Path(version["stored_path"])
        source.write_bytes(b"tampered bytes")
        assert source.stat().st_size == len(b"trusted source")

        # Collection responses use a cheap size-based capability check. Every
        # endpoint that reads or serves bytes still verifies the immutable hash.
        listed = client.get(
            f"/api/learning/workspaces/{workspace['id']}/documents?scope=mine"
        )
        assert listed.status_code == 200
        assert listed.json()["data"][0]["preview"]["available"] is True

        details = client.get(f"/api/learning/documents/{document_id}")
        assert details.status_code == 200
        assert details.json()["original_status"] == "ORIGINAL_UNAVAILABLE"
        assert details.json()["preview"]["available"] is False
        preview = client.get(f"/api/learning/documents/{document_id}/preview")
        assert preview.status_code == 410
        assert preview.json()["error"]["code"] == "ORIGINAL_UNAVAILABLE"
        content = client.get(f"/api/learning/documents/{document_id}/content")
        assert content.status_code == 410
        assert content.json()["error"]["code"] == "ORIGINAL_UNAVAILABLE"


def test_private_document_deletion_removes_original_and_derived_files(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace = workspace_for_preview(client)
        document_id = upload(
            client,
            str(workspace["id"]),
            "private.txt",
            b"delete all private derivatives",
            "text/plain",
        )
        metadata = client.get(f"/api/learning/documents/{document_id}").json()
        with client.app.state.database.connect() as connection:
            original = Path(
                connection.execute(
                    "SELECT stored_path FROM document_versions WHERE id=?",
                    (metadata["version_id"],),
                ).fetchone()["stored_path"]
            )
        derived = client.app.state.settings.upload_dir / "derived" / "private-preview.pdf"
        derived.parent.mkdir(parents=True)
        derived_bytes = b"%PDF-1.4\nprivate derived preview"
        derived.write_bytes(derived_bytes)
        with client.app.state.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO derived_artifacts(
                    id,document_version_id,kind,status,media_type,stored_path,
                    sha256,byte_size,producer_version
                ) VALUES('artifact-delete',?,'PREVIEW_PDF','READY',
                         'application/pdf',?,?,?,'test-converter-v1')
                """,
                (
                    metadata["version_id"],
                    str(derived),
                    hashlib.sha256(derived_bytes).hexdigest(),
                    len(derived_bytes),
                ),
            )

        deleted = client.delete(
            f"/api/courses/{workspace['private_course_id']}/documents/{document_id}"
        )
        assert deleted.status_code == 204, deleted.text
        assert not original.exists()
        assert not derived.exists()
        with client.app.state.database.connect() as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM document_versions WHERE document_id=?",
                (document_id,),
            ).fetchone()[0] == 0
            assert connection.execute(
                "SELECT COUNT(*) FROM derived_artifacts WHERE id='artifact-delete'"
            ).fetchone()[0] == 0
