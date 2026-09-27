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

from app.campus_ingestion import campus_course_id

SCHEMA_VERSION = "coursejesus.campus-publication.v1"
PUBLICATION_BASIS = "OWNER_DIRECTED_CAMPUS_PUBLICATION_20260927"
APPROVED_REVIEW_STATUS = "OWNER_APPROVED_CAMPUS_USE"
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    prepare = subcommands.add_parser("prepare")
    prepare.add_argument("--plan", required=True, type=pathlib.Path)
    prepare.add_argument("--ledger", required=True, type=pathlib.Path)
    prepare.add_argument("--bundle", required=True, type=pathlib.Path)
    prepare.add_argument("--operation-id", required=True)
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
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
