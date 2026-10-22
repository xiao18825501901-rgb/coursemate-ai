from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from import_reviewed_multifile_course import (
    assert_publishable,
    initial_state,
    load_manifest,
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    course = tmp_path / "course"
    course.mkdir()
    review = tmp_path / "review.json"
    review_data = {
        "course_id": "valid-course",
        "status": "OFFLINE_DOCUMENT_SUBSET_QUALIFIED_CAPACITY_GATED_ZERO_COUNTED_BYTES",
        "license_url": "https://example.test/license",
        "qualified_pdf_subset": {"files": 2, "bytes": 12},
    }
    review.write_text(json.dumps(review_data), encoding="utf-8")
    documents = []
    for index, content in enumerate((b"%PDF-a", b"%PDF-b")):
        path = course / f"{index}.pdf"
        path.write_bytes(content)
        documents.append(
            {
                "relative_path": path.name,
                "filename": path.name,
                "bytes": len(content),
                "sha256": _sha(content),
                "media_type": "application/pdf",
                "resource_license": "https://example.test/license",
            }
        )
    manifest = {
        "schema_version": 1,
        "course_id": "valid-course",
        "title": "Valid course",
        "description": "Attribution",
        "license_url": "https://example.test/license",
        "review_path": review.relative_to(tmp_path).as_posix(),
        "review_sha256": _sha(review.read_bytes()),
        "expected_files": 2,
        "expected_bytes": sum(item["bytes"] for item in documents),
        "documents": documents,
    }
    manifest_path = course / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path, manifest_path


def test_manifest_binds_every_exact_source_file(tmp_path: Path) -> None:
    root, manifest_path = _fixture(tmp_path)
    manifest = load_manifest(root, manifest_path)
    assert len(manifest["documents"]) == 2
    assert all(Path(item["absolute_path"]).is_file() for item in manifest["documents"])


def test_manifest_rejects_changed_source_without_issuing_a_grant(tmp_path: Path) -> None:
    root, manifest_path = _fixture(tmp_path)
    (manifest_path.parent / "0.pdf").write_bytes(b"%PDF-changed")
    with pytest.raises(AssertionError):
        load_manifest(root, manifest_path)


def test_initial_state_is_private_and_nothing_is_counted(tmp_path: Path) -> None:
    root, manifest_path = _fixture(tmp_path)
    manifest = load_manifest(root, manifest_path)
    state = initial_state(manifest, _sha(manifest_path.read_bytes()))
    assert state["status"] == "PRIVATE_PREPARING"
    assert state["counted_public_bytes"] == 0
    assert {item["status"] for item in state["documents"]} == {"PLANNED"}


def test_publish_is_refused_until_every_document_is_ready(tmp_path: Path) -> None:
    root, manifest_path = _fixture(tmp_path)
    manifest = load_manifest(root, manifest_path)
    state = initial_state(manifest, _sha(manifest_path.read_bytes()))
    state["documents"][0]["status"] = "READY"
    with pytest.raises(AssertionError):
        assert_publishable(state)
    state["documents"][1]["status"] = "READY"
    assert_publishable(state)
