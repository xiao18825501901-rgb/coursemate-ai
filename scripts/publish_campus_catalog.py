"""Freeze and apply one owner-directed campus-course publication batch.

The local ``prepare`` phase uses the already-reviewed ingestion ledger to choose only documents
that produced real chunks.  It hard-links (or copies when hard links are unavailable) those exact
source bytes into an immutable transfer bundle.  Personal/restricted, assessment and information
files remain represented in the manifest but are never copied into the bundle.

The production ``import`` and ``activate`` phases are defined later in this file.  They are kept
separate so a backup and a complete import receipt exist before a course can become visible.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import sqlite3
import sys
from typing import Any

_SERVICE_ROOT = pathlib.Path(__file__).resolve().parents[1] / "services" / "rag-api"
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from app.campus_ingestion import (
    BLOCKED,
    DOWNLOAD_ONLY,
    INGESTABLE,
    CampusMaterialRepository,
    InventoryRow,
    MaterialDecision,
    campus_course_id,
)
from app.campus_growth import require_growth_open
from app.errors import ApiError
from app.learning.uploads import MEDIA_TYPES
from app.models import CourseCreate, PublicationStatus

SCHEMA_VERSION = "coursejesus.campus-publication.v1"
PUBLICATION_BASIS = "OWNER_DIRECTED_CAMPUS_PUBLICATION_20260927"
# The schema deliberately has no value meaning "licence verified".  The owner directed this
# restricted campus deployment, but that is not evidence of a third-party licence, so the rights
# review status stays honest while ``publication_basis`` records the operational decision.
APPROVED_REVIEW_STATUS = "NEEDS_REVIEW"
WITHHELD_REVIEW_STATUS = "NOT_FOR_PUBLICATION"

_CANONICAL_COURSES = {
    ("https://cityu-dg.instructure.com", "629"): "ge2324",
    ("https://cityu-dg.instructure.com", "630"): "cs3481",
}


class PublicationBundleError(RuntimeError):
    """The frozen source, ledger, or manifest does not satisfy the publication contract."""


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _manifest_digest(payload: dict[str, Any]) -> str:
    unsigned = dict(payload)
    unsigned.pop("manifestSha256", None)
    return sha256_bytes(_canonical_bytes(unsigned))


def verify_manifest(payload: dict[str, Any]) -> None:
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        raise PublicationBundleError("unsupported campus publication manifest schema")
    recorded = str(payload.get("manifestSha256") or "")
    if not recorded or recorded != _manifest_digest(payload):
        raise PublicationBundleError("campus publication manifest hash does not match")


def freeze_manifest(payload: dict[str, Any]) -> str:
    """Return the digest callers store after the complete payload has been assembled."""

    return _manifest_digest(payload)


def course_create(course_id: str, name: str, description: str) -> CourseCreate:
    return CourseCreate(id=course_id, name=name[:120], description=description[:1000])


def private_publication_status() -> PublicationStatus:
    return PublicationStatus.PRIVATE


def target_course_id(institution_origin: str, canvas_course_id: str) -> str:
    canonical = _CANONICAL_COURSES.get((institution_origin, canvas_course_id))
    return canonical or campus_course_id(institution_origin, canvas_course_id)


def _ledger_states(connection: sqlite3.Connection) -> dict[tuple[str, str, str], dict[str, Any]]:
    states: dict[tuple[str, str, str], dict[str, Any]] = {}
    rows = connection.execute(
        "SELECT material.institution_origin,material.canvas_course_id,material.sha256,"
        "material.decision,document.status AS document_status,"
        "COALESCE(document.chunk_count,0) AS chunk_count "
        "FROM campus_material_records AS material "
        "LEFT JOIN documents AS document ON document.id=material.document_id"
    ).fetchall()
    for row in rows:
        key = (str(row[0]), str(row[1]), str(row[2]))
        state = states.setdefault(key, {"seen": True, "indexable": False, "decisions": set()})
        state["decisions"].add(str(row[3]))
        state["indexable"] = bool(
            state["indexable"]
            or (
                row[3] == "INGESTABLE"
                and row[4] == "ready"
                and int(row[5] or 0) > 0
            )
        )
    return states


def _is_information_container(course: dict[str, Any]) -> bool:
    files = list(course.get("files") or [])
    return bool(files) and all(
        str(item.get("classification") or "") == "INFORMATION" for item in files
    )


def _item_key(course_id: str, relative_path: str) -> str:
    return hashlib.sha256(f"{course_id}\0{relative_path}".encode("utf-8")).hexdigest()[:32]


def _stage_file(source: pathlib.Path, destination: pathlib.Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def prepare_bundle(
    *,
    plan_path: pathlib.Path,
    ledger_path: pathlib.Path,
    bundle_dir: pathlib.Path,
    operation_id: str,
) -> dict[str, Any]:
    """Create a frozen, content-addressed transfer bundle without changing either source root."""

    if not plan_path.is_file() or not ledger_path.is_file():
        raise PublicationBundleError("the frozen plan and local ingestion ledger must both exist")
    if bundle_dir.exists():
        raise PublicationBundleError("the bundle directory already exists; use a new operation id")
    if not operation_id or len(operation_id) > 100:
        raise PublicationBundleError("operation id must contain between 1 and 100 characters")

    plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
    connection = sqlite3.connect(f"file:{ledger_path.as_posix()}?mode=ro", uri=True)
    try:
        states = _ledger_states(connection)
    finally:
        connection.close()

    bundle_dir.mkdir(parents=True)
    courses: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    staged: set[str] = set()
    seen_course_content: set[tuple[str, str]] = set()
    summary = {
        "courses": 0,
        "indexFiles": 0,
        "reusedFiles": 0,
        "downloadOnlyFiles": 0,
        "withheldFiles": 0,
        "stagedBytes": 0,
    }

    for course in plan_payload.get("courses") or []:
        source_id = str(course.get("courseId") or "")
        name = str(course.get("courseName") or course.get("courseCode") or source_id).strip()
        if _is_information_container(course):
            excluded.append(
                {"courseId": source_id, "name": name, "reason": "INFORMATION_ONLY"}
            )
            continue
        origin = str(course.get("institutionOrigin") or "")
        target = target_course_id(origin, source_id)
        source_root = pathlib.Path(str(course.get("sourceRoot") or ""))
        if not source_root.is_dir():
            raise PublicationBundleError(f"source root is unavailable for Canvas course {source_id}")
        frozen_files: list[dict[str, Any]] = []
        for item in course.get("files") or []:
            relative_path = str(item.get("relativePath") or "")
            digest = str(item.get("sha256") or "")
            planned = str(item.get("status") or "")
            key = (origin, source_id, digest)
            state = states.get(key)
            if planned == "BLOCKED":
                action = "WITHHELD"
            elif state and state["indexable"]:
                content_key = (target, digest)
                action = "REUSE" if content_key in seen_course_content else "INDEX"
                seen_course_content.add(content_key)
            elif planned == "INGESTABLE" and state is None:
                raise PublicationBundleError(
                    f"ingestable file has no successful ledger result: {source_id}/{relative_path}"
                )
            else:
                action = "DOWNLOAD_ONLY"

            bundle_path = ""
            if action in {"INDEX", "REUSE"}:
                source = source_root / pathlib.PureWindowsPath(relative_path)
                if not source.is_file():
                    raise PublicationBundleError(f"frozen source file is missing: {source}")
                expected_size = int(item.get("bytes") or 0)
                if source.stat().st_size != expected_size or sha256_file(source) != digest:
                    raise PublicationBundleError(
                        f"frozen source file changed after inventory: {source_id}/{relative_path}"
                    )
                suffix = pathlib.Path(str(item.get("filename") or "")).suffix.lower()
                bundle_path = (pathlib.Path("files") / digest[:2] / f"{digest}{suffix}").as_posix()
                if bundle_path not in staged:
                    _stage_file(source, bundle_dir / pathlib.PurePosixPath(bundle_path))
                    staged.add(bundle_path)
                    summary["stagedBytes"] += expected_size

            if action == "INDEX":
                summary["indexFiles"] += 1
            elif action == "REUSE":
                summary["reusedFiles"] += 1
            elif action == "DOWNLOAD_ONLY":
                summary["downloadOnlyFiles"] += 1
            else:
                summary["withheldFiles"] += 1
            frozen_files.append(
                {
                    "itemKey": _item_key(source_id, relative_path),
                    "filename": str(item.get("filename") or ""),
                    "relativePath": relative_path,
                    "sha256": digest,
                    "bytes": int(item.get("bytes") or 0),
                    "classification": str(item.get("classification") or ""),
                    "parseClass": str(item.get("parseClass") or ""),
                    "action": action,
                    "reason": str(item.get("reason") or ""),
                    "bundlePath": bundle_path,
                    "usageRights": "UNVERIFIED",
                    "publicationBasis": PUBLICATION_BASIS,
                    "reviewStatus": (
                        WITHHELD_REVIEW_STATUS
                        if action == "WITHHELD"
                        else APPROVED_REVIEW_STATUS
                    ),
                }
            )
        courses.append(
            {
                "institutionOrigin": origin,
                "sourceCourseId": source_id,
                "targetCourseId": target,
                "courseCode": str(course.get("courseCode") or ""),
                "name": name,
                "term": str(course.get("term") or ""),
                "sourceRootLabel": source_root.name,
                "files": frozen_files,
            }
        )

    summary["courses"] = len(courses)
    manifest: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "operationId": operation_id,
        "sourcePlanSha256": sha256_file(plan_path),
        "sourceLedgerSha256": sha256_file(ledger_path),
        "publicationBasis": PUBLICATION_BASIS,
        "rightsStatement": (
            "Owner directed restricted campus use; underlying third-party licence remains "
            "UNVERIFIED. Personal, restricted, assessment and information-only files are withheld."
        ),
        "courses": courses,
        "excludedContainers": excluded,
        "summary": summary,
    }
    manifest["manifestSha256"] = _manifest_digest(manifest)
    (bundle_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def _manifest_path(bundle_dir: pathlib.Path) -> pathlib.Path:
    path = bundle_dir / "manifest.json"
    if not path.is_file():
        raise PublicationBundleError("the publication bundle has no manifest.json")
    return path


def _read_manifest(bundle_dir: pathlib.Path) -> dict[str, Any]:
    payload = json.loads(_manifest_path(bundle_dir).read_text(encoding="utf-8"))
    verify_manifest(payload)
    return payload


def _inventory_row(course: dict[str, Any], item: dict[str, Any]) -> InventoryRow:
    return InventoryRow(
        source_root=str(course.get("sourceRootLabel") or "LOCAL_CANVAS_EXPORT"),
        institution_origin=str(course["institutionOrigin"]),
        course_id=str(course["sourceCourseId"]),
        course_code=str(course.get("courseCode") or ""),
        course_name=str(course["name"]),
        term=str(course.get("term") or ""),
        summary_category="",
        relative_path=str(item["relativePath"]),
        filename=str(item["filename"]),
        bytes_disk=int(item["bytes"]),
        sha256=str(item["sha256"]),
        mime_guess="",
        parse_class=str(item.get("parseClass") or ""),
        classification=str(item.get("classification") or ""),
        classification_reason="",
        disk_status="PRESENT",
        publication_basis=str(item["publicationBasis"]),
        review_status=str(item["reviewStatus"]),
    )


def _media_type(filename: str) -> str:
    extension = pathlib.PurePosixPath(filename).suffix.casefold()
    allowed = MEDIA_TYPES.get(extension)
    if not allowed:
        raise PublicationBundleError(f"indexed bundle file has unsupported extension: {extension}")
    non_generic = sorted(item for item in allowed if item != "application/octet-stream")
    return non_generic[0] if non_generic else "application/octet-stream"


def _safe_bundle_file(bundle_dir: pathlib.Path, item: dict[str, Any]) -> pathlib.Path:
    relative = pathlib.PurePosixPath(str(item.get("bundlePath") or ""))
    if not relative.parts or relative.is_absolute() or ".." in relative.parts:
        raise PublicationBundleError("an indexed file has an unsafe bundle path")
    path = bundle_dir.joinpath(*relative.parts)
    if not path.is_file():
        raise PublicationBundleError(f"an indexed bundle file is missing: {relative.as_posix()}")
    if path.stat().st_size != int(item["bytes"]) or sha256_file(path) != item["sha256"]:
        raise PublicationBundleError(f"an indexed bundle file failed verification: {item['filename']}")
    return path


def _batch_id(operation_id: str, target_course_id_value: str) -> str:
    digest = hashlib.sha256(
        f"{operation_id}\0{target_course_id_value}".encode("utf-8")
    ).hexdigest()[:32]
    return f"campus_{digest}"


def import_bundle(
    *,
    bundle_dir: pathlib.Path,
    database: Any,
    ingestion: Any,
    auto_map: Any,
    receipt_path: pathlib.Path,
) -> dict[str, Any]:
    """Import frozen files, leaving every newly created course private.

    One upload batch is opened per course and sealed only after every selected index file has a
    terminal result.  This produces one source revision for the automatic map instead of one paid
    rebuild per file.  Re-running is safe: content hashes resolve to the already stored document.
    """

    manifest = _read_manifest(bundle_dir)
    operation_id = str(manifest["operationId"])
    receipt: dict[str, Any] = {
        "schemaVersion": "coursejesus.campus-publication-receipt.v1",
        "operationId": operation_id,
        "manifestSha256": manifest["manifestSha256"],
        "courses": [],
        "summary": {"indexed": 0, "existing": 0, "failed": 0, "downloadOnly": 0, "withheld": 0},
    }

    with database.connect() as connection:
        connection.isolation_level = None
        repository = CampusMaterialRepository(connection)
        for course in manifest["courses"]:
            target = str(course["targetCourseId"])
            current = connection.execute("SELECT * FROM courses WHERE id=?", (target,)).fetchone()
            if current is None:
                ingestion.create_course(
                    course_create(
                        target,
                        str(course["name"]),
                        "由本地 Canvas 冻结清单导入；仅限已注册校园用户，机器知识图会明确标注。",
                    ),
                    is_admin=True,
                    publication_status=PublicationStatus.PRIVATE,
                )
                current = connection.execute(
                    "SELECT * FROM courses WHERE id=?", (target,)
                ).fetchone()
            if current is None or current["course_type"] != "official":
                raise PublicationBundleError(f"target course is not an official course: {target}")

            index_items = [item for item in course["files"] if item["action"] == "INDEX"]
            batch = None
            batch_items: list[dict[str, Any]] = []
            if index_items:
                batch = auto_map.begin_upload_batch(
                    course_id=target,
                    source_course_id=target,
                    owner_user_id="campus-catalog-owner",
                    batch_id=_batch_id(operation_id, target),
                    expected_items=len(index_items),
                )
            documents_by_sha: dict[str, str] = {}
            course_result = {
                "targetCourseId": target,
                "sourceCourseId": str(course["sourceCourseId"]),
                "indexed": 0,
                "existing": 0,
                "failed": 0,
                "downloadOnly": 0,
                "withheld": 0,
                "batchStatus": str(batch.get("status")) if batch else "NOT_REQUIRED",
            }
            for item in course["files"]:
                row = _inventory_row(course, item)
                action = str(item["action"])
                if action == "WITHHELD":
                    decision = MaterialDecision(BLOCKED, str(item["reason"]), WITHHELD_REVIEW_STATUS)
                    repository.upsert(row, decision, target_course_id=target)
                    course_result["withheld"] += 1
                    receipt["summary"]["withheld"] += 1
                    continue
                if action == "DOWNLOAD_ONLY":
                    decision = MaterialDecision(
                        DOWNLOAD_ONLY, str(item["reason"]), APPROVED_REVIEW_STATUS
                    )
                    repository.upsert(row, decision, target_course_id=target)
                    course_result["downloadOnly"] += 1
                    receipt["summary"]["downloadOnly"] += 1
                    continue
                if action == "REUSE":
                    document_id = documents_by_sha.get(str(item["sha256"]))
                    if document_id is None:
                        existing = connection.execute(
                            "SELECT id FROM documents WHERE course_id=? AND sha256=?",
                            (target, item["sha256"]),
                        ).fetchone()
                        document_id = str(existing["id"]) if existing else None
                    if document_id is None:
                        raise PublicationBundleError(
                            f"duplicate manifest item has no indexed source: {item['filename']}"
                        )
                    decision = MaterialDecision(
                        INGESTABLE, "identical content already indexed in this course", APPROVED_REVIEW_STATUS
                    )
                    repository.upsert(
                        row, decision, target_course_id=target, document_id=document_id
                    )
                    continue

                source = _safe_bundle_file(bundle_dir, item)
                content = source.read_bytes()
                status = "INDEXED"
                error_code = None
                existing_document = False
                try:
                    accepted = ingestion.queue_document(
                        course_id=target,
                        filename=str(item["filename"]),
                        media_type=_media_type(str(item["filename"])),
                        content=content,
                        is_admin=True,
                    )
                    document_id = str(accepted.document.id)
                    ingestion.process_document(document_id, str(accepted.job.id))
                except ApiError as error:
                    if error.code != "DUPLICATE_DOCUMENT" or not isinstance(
                        error.details.get("documentId"), str
                    ):
                        status = "FAILED"
                        error_code = error.code
                        document_id = None
                    else:
                        document_id = str(error.details["documentId"])
                        existing_document = True

                if document_id is not None:
                    document = ingestion.get_document(document_id)
                    if document.status.value == "ready" and int(document.chunk_count) > 0:
                        documents_by_sha[str(item["sha256"])] = document_id
                        decision = MaterialDecision(
                            INGESTABLE, "academic teaching material", APPROVED_REVIEW_STATUS
                        )
                        repository.upsert(
                            row, decision, target_course_id=target, document_id=document_id
                        )
                        key = "existing" if existing_document else "indexed"
                        course_result[key] += 1
                        receipt["summary"][key] += 1
                    else:
                        status = "FAILED"
                        error_code = "NO_READABLE_CHUNKS"
                        decision = MaterialDecision(
                            DOWNLOAD_ONLY,
                            "production parser produced no readable chunks",
                            APPROVED_REVIEW_STATUS,
                        )
                        repository.upsert(
                            row, decision, target_course_id=target, document_id=document_id
                        )
                else:
                    decision = MaterialDecision(
                        DOWNLOAD_ONLY,
                        f"production ingestion refused the file: {error_code}",
                        APPROVED_REVIEW_STATUS,
                    )
                    repository.upsert(row, decision, target_course_id=target)

                if status == "FAILED":
                    course_result["failed"] += 1
                    receipt["summary"]["failed"] += 1
                batch_item = {
                    "item_key": str(item["itemKey"]),
                    "status": status,
                    "document_id": document_id,
                    "error_code": error_code,
                }
                batch_items.append(batch_item)
                auto_map.record_upload_batch_item(
                    batch_id=_batch_id(operation_id, target),
                    item_key=batch_item["item_key"],
                    course_id=target,
                    owner_user_id="campus-catalog-owner",
                    status=status,
                    document_id=document_id,
                    error_code=error_code,
                )
            if batch_items:
                sealed = auto_map.seal_upload_batch(
                    course_id=target,
                    owner_user_id="campus-catalog-owner",
                    batch_id=_batch_id(operation_id, target),
                    items=batch_items,
                )
                course_result["batchStatus"] = str(sealed.get("status"))
            receipt["courses"].append(course_result)

    receipt["receiptSha256"] = sha256_bytes(_canonical_bytes(receipt))
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return receipt


def activate_catalog(*, database: Any, manifest: dict[str, Any]) -> dict[str, int]:
    """Atomically publish course rows after every automatic-map target is terminal."""

    verify_manifest(manifest)
    allowed = {"READY", "READY_WITH_EXCEPTIONS", "WAITING_SOURCE", "EXISTING_ACTIVE"}
    activated = already = 0
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        decisions: list[tuple[str, bool]] = []
        for course in manifest["courses"]:
            target = str(course["targetCourseId"])
            row = connection.execute("SELECT * FROM courses WHERE id=?", (target,)).fetchone()
            if row is None or row["course_type"] != "official":
                raise PublicationBundleError(f"campus course is missing before activation: {target}")
            open_batches = connection.execute(
                "SELECT COUNT(*) FROM auto_knowledge_upload_batches "
                "WHERE source_course_id=? AND status='OPEN'",
                (target,),
            ).fetchone()[0]
            if open_batches:
                raise PublicationBundleError(f"campus course has an open upload batch: {target}")
            target_state = connection.execute(
                "SELECT status FROM auto_knowledge_targets WHERE target_key=?",
                (f"AUTO_COURSE:{target}",),
            ).fetchone()
            status = str(target_state["status"]) if target_state else "MISSING"
            if status not in allowed:
                raise PublicationBundleError(
                    f"automatic map is not terminal for {target}: {status}"
                )
            readable_selected = any(item["action"] == "INDEX" for item in course["files"])
            if readable_selected and status == "WAITING_SOURCE":
                raise PublicationBundleError(
                    f"automatic map did not consume readable material for {target}"
                )
            active_jobs = connection.execute(
                "SELECT COUNT(*) FROM auto_knowledge_jobs WHERE course_id=? "
                "AND status IN ('QUEUED','RUNNING','UNKNOWN')",
                (target,),
            ).fetchone()[0]
            if active_jobs:
                raise PublicationBundleError(f"automatic map work is unresolved for {target}")
            decisions.append((target, row["publication_status"] == "published"))

        for target, is_published in decisions:
            if is_published:
                already += 1
                continue
            connection.execute(
                (
                    "UPDATE courses SET visibility='public',publication_status='published',"
                    "published_at=COALESCE(published_at,"
                    "strftime('%Y-%m-%dT%H:%M:%fZ','now'))"
                    ",updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),"
                    "display_type='campus',requires_student_verification=1 WHERE id=?"
                ),
                (target,),
            )
            activated += 1
    return {"activated": activated, "alreadyPublished": already}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    prepare = subcommands.add_parser("prepare")
    prepare.add_argument("--plan", required=True, type=pathlib.Path)
    prepare.add_argument("--ledger", required=True, type=pathlib.Path)
    prepare.add_argument("--bundle", required=True, type=pathlib.Path)
    prepare.add_argument("--operation-id", required=True)
    apply_import = subcommands.add_parser("import")
    apply_import.add_argument("--bundle", required=True, type=pathlib.Path)
    apply_import.add_argument("--receipt", required=True, type=pathlib.Path)
    activate = subcommands.add_parser("activate")
    activate.add_argument("--bundle", required=True, type=pathlib.Path)
    activate.add_argument("--receipt", required=True, type=pathlib.Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "prepare":
        manifest = prepare_bundle(
            plan_path=args.plan,
            ledger_path=args.ledger,
            bundle_dir=args.bundle,
            operation_id=args.operation_id,
        )
        print(json.dumps({"manifest": str(args.bundle / "manifest.json"), **manifest["summary"]}))
        return 0
    if args.command in {"import", "activate"}:
        require_growth_open(f"{args.command} the frozen campus publication batch")
        from app.main import create_app

        application = create_app()
        database = application.state.database
        if args.command == "import":
            auto_map = getattr(application.state, "auto_knowledge_map", None)
            if auto_map is None:
                raise PublicationBundleError("automatic knowledge maps are not enabled")
            receipt = import_bundle(
                bundle_dir=args.bundle,
                database=database,
                ingestion=application.state.ingestion_service,
                auto_map=auto_map,
                receipt_path=args.receipt,
            )
        else:
            manifest = _read_manifest(args.bundle)
            result = activate_catalog(database=database, manifest=manifest)
            receipt = {
                "schemaVersion": "coursejesus.campus-activation-receipt.v1",
                "operationId": manifest["operationId"],
                "manifestSha256": manifest["manifestSha256"],
                **result,
            }
            receipt["receiptSha256"] = sha256_bytes(_canonical_bytes(receipt))
            args.receipt.parent.mkdir(parents=True, exist_ok=True)
            args.receipt.write_text(
                json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        print(json.dumps(receipt["summary"] if "summary" in receipt else receipt))
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
