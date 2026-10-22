"""Resume-safe multi-document imports through the existing direct OSS authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


EXPECTED_RUNTIME = "/srv/coursemate/releases/corpus-nullfix-02a7de2/services/rag-api"
PRODUCTION_RUNTIME = EXPECTED_RUNTIME
OWNER = "owner-authorized-corpus-import"
TERMINAL_DOCUMENT_STATUS = "READY"


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def load_manifest(root: Path, manifest_path: Path) -> dict[str, Any]:
    root = root.resolve(strict=True)
    manifest_path = manifest_path.resolve(strict=True)
    assert manifest_path.is_relative_to(root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert 2 <= len(manifest["course_id"]) <= 50
    assert manifest["expected_files"] == len(manifest["documents"])
    assert manifest["expected_files"] > 1
    assert manifest["expected_bytes"] == sum(
        int(document["bytes"]) for document in manifest["documents"]
    )
    review_path = (root / manifest["review_path"]).resolve(strict=True)
    assert review_path.is_relative_to(root)
    assert sha256_file(review_path) == manifest["review_sha256"]
    review = json.loads(review_path.read_text(encoding="utf-8"))
    assert review["course_id"] == manifest["course_id"]
    review_contract = manifest.get("review_contract", "mit_ocw_review_v1")
    if review_contract == "mit_ocw_review_v1":
        assert review["status"].startswith("OFFLINE_DOCUMENT_SUBSET_QUALIFIED")
        assert review["license_url"] == manifest["license_url"]
        assert review["qualified_pdf_subset"]["files"] == manifest["expected_files"]
        assert review["qualified_pdf_subset"]["bytes"] == manifest["expected_bytes"]
    elif review_contract == "source_receipt_v1":
        assert review["decision"].startswith("OFFLINE_QUALIFIED_LOADER_VALIDATED")
        assert len(review["files"]) == manifest["expected_files"]
        assert review["total_bytes"] == manifest["expected_bytes"]
        receipt_identities = {
            (item["path"], int(item["bytes"]), item["sha256"])
            for item in review["files"]
        }
        manifest_identities = {
            (item["filename"], int(item["bytes"]), item["sha256"])
            for item in manifest["documents"]
        }
        assert receipt_identities == manifest_identities
    else:
        raise AssertionError(f"Unsupported review contract: {review_contract}")
    seen_paths: set[str] = set()
    seen_hashes: set[str] = set()
    for document in manifest["documents"]:
        source = (manifest_path.parent / document["relative_path"]).resolve(strict=True)
        assert source.is_relative_to(root)
        assert source.name == document["filename"]
        assert source.suffix.casefold() == ".pdf"
        assert int(document["bytes"]) == source.stat().st_size
        assert sha256_file(source) == document["sha256"]
        assert document["media_type"] == "application/pdf"
        assert document["resource_license"] == manifest["license_url"]
        assert str(source) not in seen_paths
        assert document["sha256"] not in seen_hashes
        document["absolute_path"] = str(source)
        seen_paths.add(str(source))
        seen_hashes.add(document["sha256"])
    return manifest


def initial_state(manifest: dict[str, Any], manifest_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "course_id": manifest["course_id"],
        "manifest_sha256": manifest_sha256,
        "status": "PRIVATE_PREPARING",
        "counted_public_bytes": 0,
        "documents": [
            {
                "index": index,
                "filename": document["filename"],
                "sha256": document["sha256"],
                "bytes": document["bytes"],
                "status": "PLANNED",
            }
            for index, document in enumerate(manifest["documents"])
        ],
    }


def assert_publishable(state: dict[str, Any]) -> None:
    assert state["status"] == "PRIVATE_PREPARING"
    assert state["documents"]
    assert all(item["status"] == TERMINAL_DOCUMENT_STATUS for item in state["documents"])


def runtime_environment() -> dict[str, str]:
    pid = int(
        subprocess.check_output(
            ["systemctl", "show", "coursemate-rag", "-p", "MainPID", "--value"]
        )
    )
    environment = dict(
        pair.split("=", 1)
        for pair in Path(f"/proc/{pid}/environ").read_text().split("\0")
        if "=" in pair
    )
    assert environment["PYTHONPATH"] == PRODUCTION_RUNTIME
    assert environment.get("STORAGE_BACKEND") == "aliyun_oss"
    return environment


def services(max_document_bytes: int):
    os.environ.update(runtime_environment())
    sys.path.insert(0, EXPECTED_RUNTIME)
    from app.config import Settings
    from app.db import Database
    from app.rag.embeddings import OpenAIEmbeddingProvider
    from app.services.ingestion import IngestionService

    live = Settings()
    settings = Settings(max_upload_bytes=max(live.max_upload_bytes, max_document_bytes))
    database = Database(settings)
    provider = OpenAIEmbeddingProvider(
        api_key=settings.rag_embedding_api_key.get_secret_value(),
        model=settings.rag_embedding_model,
        base_url=settings.rag_embedding_base_url,
    )
    return live, settings, database, provider, IngestionService(
        database, settings, provider
    )


def write_state(path: Path, state: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def prepare(root: Path, manifest_path: Path, state_path: Path) -> None:
    manifest = load_manifest(root, manifest_path)
    assert not state_path.exists(), "Existing state must be reconciled; never overwrite it"
    _live, _settings, database, _provider, service = services(
        max(int(item["bytes"]) for item in manifest["documents"])
    )
    from app.models import CourseCreate, PublicationStatus

    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM ingestion_jobs WHERE status='processing'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM documents WHERE course_id=?", (manifest["course_id"],)
        ).fetchone()[0] == 0
        for document in manifest["documents"]:
            assert connection.execute(
                "SELECT COUNT(*) FROM storage_objects WHERE sha256=? AND state='CANONICAL'",
                (document["sha256"],),
            ).fetchone()[0] == 0
        existing = connection.execute(
            "SELECT * FROM courses WHERE id=?", (manifest["course_id"],)
        ).fetchone()
    if existing is None:
        service.create_course(
            CourseCreate(
                id=manifest["course_id"],
                name=manifest["title"],
                description=manifest["description"],
            ),
            is_admin=True,
            open_resource=True,
            publication_status=PublicationStatus.PRIVATE,
        )
    else:
        assert existing["name"] == manifest["title"]
        assert existing["description"] == manifest["description"]
        assert existing["publication_status"] == PublicationStatus.PRIVATE.value
    state = initial_state(manifest, sha256_file(manifest_path))
    state["prepared_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    write_state(state_path, state)
    print(json.dumps({"status": state["status"], "documents": len(state["documents"])}))


def begin(root: Path, manifest_path: Path, state_path: Path, index: int) -> None:
    manifest = load_manifest(root, manifest_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["manifest_sha256"] == sha256_file(manifest_path)
    item = state["documents"][index]
    assert item["status"] == "PLANNED", "Never create a second grant for an existing slot"
    document = manifest["documents"][index]
    _live, _settings, _database, _provider, service = services(int(document["bytes"]))
    from app.models import DirectUploadCreate

    grant = service.begin_direct_upload(
        course_id=manifest["course_id"],
        payload=DirectUploadCreate(
            filename=document["filename"],
            media_type=document["media_type"],
            byte_size=int(document["bytes"]),
            sha256=document["sha256"],
        ),
        owner_user_id=OWNER,
        is_admin=True,
    )
    assert grant.method == "PUT"
    item.update(
        status="GRANT_CREATED",
        upload_id=grant.upload_id,
        grant_created_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    write_state(state_path, state)
    print(grant.model_dump_json(by_alias=True))


def finalize(root: Path, manifest_path: Path, state_path: Path, index: int, upload_id: str) -> None:
    manifest = load_manifest(root, manifest_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["manifest_sha256"] == sha256_file(manifest_path)
    item = state["documents"][index]
    assert item["status"] == "GRANT_CREATED"
    assert item["upload_id"] == upload_id
    document = manifest["documents"][index]
    _live, _settings, database, _provider, service = services(int(document["bytes"]))
    accepted = service.finalize_direct_upload(
        upload_id=upload_id, owner_user_id=OWNER, is_admin=True
    )
    item.update(status="QUEUED", document_id=accepted.document.id, job_id=accepted.job.id)
    write_state(state_path, state)
    service.process_document(accepted.document.id, accepted.job.id)
    stored_document = service.get_document(accepted.document.id)
    assert str(stored_document.status) == "ready"
    with database.connect() as connection:
        stored = connection.execute(
            "SELECT object_key,version_id,byte_size,sha256 FROM storage_objects "
            "WHERE document_id=? AND state='CANONICAL'",
            (accepted.document.id,),
        ).fetchone()
        chunks = connection.execute(
            "SELECT COUNT(*) FROM chunks WHERE document_id=?", (accepted.document.id,)
        ).fetchone()[0]
    assert stored and stored["sha256"] == document["sha256"] and chunks > 0
    digest = hashlib.sha256()
    for start in range(0, int(stored["byte_size"]), 4 * 1024 * 1024):
        end = min(start + 4 * 1024 * 1024, int(stored["byte_size"])) - 1
        content = service.storage_backend.read_range(stored["object_key"], start=start, end=end)
        assert len(content) == end - start + 1
        digest.update(content)
    assert digest.hexdigest() == document["sha256"]
    item.update(
        status=TERMINAL_DOCUMENT_STATUS,
        chunks=chunks,
        storage=dict(stored),
        completed_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    write_state(state_path, state)
    print(json.dumps({"index": index, "status": item["status"], "chunks": chunks}))


def publish(root: Path, manifest_path: Path, state_path: Path) -> None:
    manifest = load_manifest(root, manifest_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["manifest_sha256"] == sha256_file(manifest_path)
    assert_publishable(state)
    _live, _settings, database, provider, _service = services(
        max(int(item["bytes"]) for item in manifest["documents"])
    )
    from app.models import PublicationStatus
    from app.rag.retrieval import HybridRetriever
    from app.repositories.chunks import ChunkRepository, RetrievalAccess
    from app.services.publication_snapshots import record_audit_event

    hits = HybridRetriever(ChunkRepository(database), provider).retrieve(
        course_id=manifest["course_id"],
        query=manifest["retrieval_query"],
        top_k=5,
        access=RetrievalAccess(owner_user_id="public-corpus-access-probe", scope="official"),
    )
    assert hits
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        course = connection.execute(
            "SELECT * FROM courses WHERE id=?", (manifest["course_id"],)
        ).fetchone()
        assert course["publication_status"] == PublicationStatus.PRIVATE.value
        assert connection.execute(
            "SELECT COUNT(*) FROM documents WHERE course_id=?", (manifest["course_id"],)
        ).fetchone()[0] == manifest["expected_files"]
        assert connection.execute(
            "SELECT COUNT(*) FROM documents WHERE course_id=? AND status!='ready'",
            (manifest["course_id"],),
        ).fetchone()[0] == 0
        connection.execute(
            "UPDATE courses SET visibility='public',publication_status='published',"
            "published_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),"
            "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (manifest["course_id"],),
        )
        record_audit_event(
            connection,
            subject_kind="COURSE",
            request_id="corpus-reviewed-multifile-20261023:" + manifest["course_id"],
            actor_user_id=OWNER,
            action="APPROVED",
            details={
                "basis": "Owner-authorized exact licensed reviewed multi-document import",
                "manifest_sha256": state["manifest_sha256"],
                "document_ids": [item["document_id"] for item in state["documents"]],
            },
        )
    state.update(
        status="INDEXED_OSS_VERIFIED",
        counted_public_bytes=0,
        retrieval_chunk_ids=[hit.chunk_id for hit in hits],
        published_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        accounting_note="Await real Clerk student access before strict student count",
    )
    write_state(state_path, state)
    print(json.dumps({"course_id": manifest["course_id"], "status": state["status"]}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "begin", "finalize", "publish"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--index", type=int)
    parser.add_argument("--upload-id")
    args = parser.parse_args()
    root = Path(args.root).resolve(strict=True)
    manifest_path = Path(args.manifest).resolve(strict=True)
    state_path = Path(args.state).resolve()
    assert state_path.is_relative_to(root)
    if args.action == "prepare":
        assert args.index is None and args.upload_id is None
        prepare(root, manifest_path, state_path)
    elif args.action == "begin":
        assert args.index is not None and args.upload_id is None
        begin(root, manifest_path, state_path, args.index)
    elif args.action == "finalize":
        assert args.index is not None and args.upload_id
        finalize(root, manifest_path, state_path, args.index, args.upload_id)
    else:
        assert args.index is None and args.upload_id is None
        publish(root, manifest_path, state_path)


if __name__ == "__main__":
    main()
