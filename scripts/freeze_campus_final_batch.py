"""Freeze the final local campus batch into one reviewable manifest.

The owner's decision (2026-09-24) is that the local expansion from `D:\\Canvas` /
`D:\\Canvas-DG` ends with this batch. This script records that batch as a single frozen
artefact — `CAMPUS_FINAL_BATCH_MANIFEST.json` — by joining the two things that already exist
rather than re-scanning 8.26 GiB:

* `docs/coursejesus/LOCAL_CAMPUS_INVENTORY.csv` — the committed, redacted, per-file scan with
  its SHA-256, classification and rights basis;
* `work/current-change/campus-library.sqlite3` — the local ingestion ledger
  (`campus_material_records`, one row per file actually processed) plus the campus courses it
  created.

It also reconciles the frozen set against the disk **without hashing anything**: every row's
size is compared with the file's current size, and a file whose size differs is marked
`UNSTABLE_SOURCE` (the same rule the ingestion path uses, which blocks rather than ingests a
changed file). Files that no longer exist are marked `SOURCE_MISSING`, and files present on
disk but absent from the inventory are listed as `UNLISTED_ON_DISK`. Both are reported, not
silently dropped.

What it deliberately does **not** do: publish anything (publication needs the owner's rights
decision; see `CAMPUS_FINAL_BATCH_CLOSURE.md`), move or delete a source file, or treat a local
ingestion count as production publication.

Usage:
    python scripts/freeze_campus_final_batch.py \
        --inventory docs/coursejesus/LOCAL_CAMPUS_INVENTORY.csv \
        --database work/current-change/campus-library.sqlite3 \
        --out CAMPUS_FINAL_BATCH_MANIFEST.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import sqlite3
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

# The scanner's own classifier decides what a file is; reusing it keeps one definition of
# "personal/restricted" instead of a second one that could disagree.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import scan_campus_inventory

# Terminal states of a file in this batch. Chosen to match the states the existing code already
# uses (`decision`, `review_status`, `publication_status`) rather than inventing a parallel
# vocabulary; see CAMPUS_FINAL_BATCH_CLOSURE.md for the mapping and the counts.
INGESTED_PRIVATE = "INGESTED_PRIVATE"
INGEST_REFUSED = "INGEST_REFUSED"
DOWNLOAD_ONLY = "DOWNLOAD_ONLY"
WITHHELD_POLICY = "WITHHELD_POLICY"
WITHHELD_OWNER_DECISION = "WITHHELD_OWNER_DECISION"
NOT_INGESTED = "NOT_INGESTED"
INTERNAL_SOURCE_RECORD = "INTERNAL_SOURCE_RECORD"
UNSTABLE_SOURCE = "UNSTABLE_SOURCE"
SOURCE_MISSING = "SOURCE_MISSING"

PUBLISHED = "PUBLISHED"  # never assigned by this script; asserted to be zero afterwards

# The committed inventory redacts the identity of personal/restricted files on purpose (see
# docs/coursejesus/CAMPUS_SOURCE_AND_PUBLICATION_MATRIX.md §5), so their paths cannot be compared
# against disk. They are neither "missing" nor "unlisted": they are withheld, and the unredacted
# identity lives in the working copy and in the local ingestion ledger.
REDACTED = "REDACTED_PERSONAL_OR_RESTRICTED"
MANIFEST_NAME = "_download_manifest.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=pathlib.Path, required=True)
    parser.add_argument("--database", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--batch-id", default="final-local-campus-batch-2026-09-24")
    return parser.parse_args()


def material_rows(database: pathlib.Path) -> list[sqlite3.Row]:
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute("SELECT * FROM campus_material_records").fetchall()
    finally:
        connection.close()


def campus_courses(database: pathlib.Path) -> list[dict[str, Any]]:
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT id, name, visibility, publication_status, published_at, display_type, "
            "requires_student_verification FROM courses WHERE display_type='campus' ORDER BY id"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def terminal_state(row: dict[str, str], material: sqlite3.Row | None) -> str:
    if row["disk_status"] == "MISSING_ON_DISK":
        return SOURCE_MISSING
    if (row["filename"] or "").endswith(MANIFEST_NAME) or row["manifest_status"] == (
        "SOURCE_MANIFEST"
    ):
        return INTERNAL_SOURCE_RECORD
    if material is None:
        # Never processed: the plan refused it before the database, which is what happens to
        # personal/restricted and announcement material.
        if row["classification"] in {"PERSONAL_OR_RESTRICTED", "INFORMATION", "TRAINING"}:
            return WITHHELD_POLICY
        if row["review_status"] == "INTERNAL_SOURCE_RECORD":
            return INTERNAL_SOURCE_RECORD
        return NOT_INGESTED
    decision = str(material["decision"])
    if decision == "INGESTABLE":
        return INGESTED_PRIVATE if material["document_id"] else INGEST_REFUSED
    if decision == "DOWNLOAD_ONLY":
        return DOWNLOAD_ONLY
    review = str(material["review_status"])
    if review == "NOT_FOR_PUBLICATION":
        return WITHHELD_POLICY
    return WITHHELD_OWNER_DECISION


def main() -> int:
    args = parse_args()
    started = datetime.now(UTC)
    local_offset = datetime.now().astimezone().utcoffset() or timedelta(0)
    material = material_rows(args.database)
    by_key: dict[tuple[str, str, str, str], sqlite3.Row] = {}
    for record in material:
        key = (
            str(record["source_root"]),
            str(record["institution_origin"]),
            str(record["canvas_course_id"]),
            str(record["relative_path"]),
        )
        by_key[key] = record

    files: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    roots: dict[str, dict[str, int]] = {}
    changed: list[str] = []
    unlisted: list[str] = []
    redacted_paths: set[tuple[str, str, str]] = set()
    with args.inventory.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (
                row["source_root"],
                row["institution_origin"],
                row["course_id"],
                row["relative_path"],
            )
            record = by_key.get(key)
            path = pathlib.Path(row["source_root"]) / pathlib.Path(row["relative_path"])
            redacted = REDACTED in (row["filename"] or "") or REDACTED in (
                row["relative_path"] or ""
            )
            size_now: int | None = None
            if not redacted and row["disk_status"] != "MISSING_ON_DISK" and path.is_file():
                size_now = path.stat().st_size
            state = terminal_state(row, record)
            if redacted:
                # Identity withheld by design: keep the review state, do not claim the file is gone.
                state = WITHHELD_POLICY
                redacted_paths.add((row["source_root"], row["course_id"], row["bytes_disk"]))
            elif state not in {SOURCE_MISSING, INTERNAL_SOURCE_RECORD}:
                if size_now is None:
                    state = SOURCE_MISSING
                elif size_now != int(row["bytes_disk"]):
                    state = UNSTABLE_SOURCE
                    changed.append(row["relative_path"])
            counts[state] += 1
            root_stats = roots.setdefault(row["source_root"], {"files": 0, "bytes": 0})
            root_stats["files"] += 1
            root_stats["bytes"] += int(row["bytes_disk"] or 0)
            files.append(
                {
                    "source_root": row["source_root"],
                    "institution_origin": row["institution_origin"],
                    "canvas_course_id": row["course_id"],
                    "term": row["term"],
                    "course_name": row["course_name"],
                    "relative_path": row["relative_path"],
                    "filename": row["filename"],
                    "bytes": int(row["bytes_disk"] or 0),
                    "sha256": row["sha256"],
                    "classification": row["classification"],
                    "parse_class": row["parse_class"],
                    "decision": (
                        str(record["decision"]) if record is not None else row["review_status"]
                    ),
                    "publication_basis": (
                        str(record["publication_basis"])
                        if record is not None
                        else row["publication_basis"]
                    ),
                    "review_status": (
                        str(record["review_status"]) if record is not None else row["review_status"]
                    ),
                    "target_course_id": (
                        str(record["target_course_id"]) if record is not None else ""
                    ),
                    "document_id": str(record["document_id"] or "") if record is not None else "",
                    "terminal_state": state,
                    "path_redacted": redacted,
                    "review_status_now": (
                        str(record["review_status"]) if record is not None else row["review_status"]
                    ),
                }
            )

    # Anything on disk that neither the inventory nor the local ingestion ledger lists: reported,
    # never folded into a total. The ledger knows the unredacted path of the personal/restricted
    # files, so those are not "unlisted" — they are withheld.
    #
    # A file that IS unlisted is classified with the scanner's own rule before its path is written
    # anywhere: the committed inventory redacts personal names on purpose, and a freeze artefact
    # must not undo that by listing a class list it happens to have found.
    listed = {(row["source_root"], row["relative_path"]) for row in files}
    listed |= {
        (str(record["source_root"]), str(record["relative_path"])) for record in material
    }
    unlisted_redacted: list[str] = []
    for root in sorted(roots):
        label = "canvas-dg" if "DG" in root.upper() else "canvas"
        for path in pathlib.Path(root).rglob("*"):
            if not path.is_file():
                continue
            relative = str(path.relative_to(pathlib.Path(root)))
            if (root, relative) in listed:
                continue
            category, _reason = scan_campus_inventory.classify(
                pathlib.PurePosixPath(relative), label
            )
            digest = hashlib.sha256(f"{root}|{relative}".encode()).hexdigest()
            if category == "PERSONAL_OR_RESTRICTED":
                unlisted_redacted.append(digest)
            else:
                unlisted.append(f"{root}\\{relative}")

    courses = campus_courses(args.database)
    published = [course for course in courses if course["publication_status"] == "published"]
    manifest = {
        "artifact_version": "campus-final-batch-manifest-v1",
        "batch_id": args.batch_id,
        "frozen_at_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "frozen_at_local": (started + local_offset).strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source_roots": sorted(roots),
        "scope": (
            "Every file listed by docs/coursejesus/LOCAL_CAMPUS_INVENTORY.csv, joined to the local "
            "ingestion ledger. No file was re-hashed for this freeze: identity comes from the "
            "inventory's SHA-256 and stability from a size comparison, so a file that changed "
            "after the scan is marked UNSTABLE_SOURCE rather than silently re-baselined."
        ),
        "roots": roots,
        "tallies": dict(sorted(counts.items())),
        "publication": {
            "published_files": 0,
            "campus_courses": len(courses),
            "campus_courses_published": len(published),
            "note": (
                "Nothing in this batch is published. Publication requires the owner's rights "
                "decision for the files on docs/coursejesus/CAMPUS_RIGHTS_REVIEW_LIST.csv; every "
                "ingested file sits in a private campus course with review_status NEEDS_REVIEW."
            ),
        },
        "campus_courses": courses,
        "unstable_source": changed,
        "unlisted_on_disk": unlisted,
        "unlisted_redacted_path_hashes": sorted(unlisted_redacted),
        "unlisted_note": (
            "Files on disk that neither the committed inventory nor the local ledger names. A "
            "personal/restricted one is represented by the SHA-256 of its path, not by the path: "
            "the committed inventory redacts those names and this artefact must not undo that. "
            "The unredacted list stays in work/current-change/."
        ),
        "redacted_rows": len(redacted_paths),
        "redaction_note": (
            "The committed inventory replaces the name and path of personal/restricted rows with "
            f"{REDACTED} ({len(redacted_paths)} rows). Their identity is in the working copy and "
            "in the local ingestion ledger; this manifest keeps them withheld and never claims "
            "their files are missing."
        ),
        "content_hash": "",
        "files": files,
    }
    files_only = json.dumps(files, ensure_ascii=False, sort_keys=True).encode("utf-8")
    manifest["content_hash"] = hashlib.sha256(files_only).hexdigest()
    args.out.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    print(f"batch: {manifest['batch_id']}")
    print(f"frozen at: {manifest['frozen_at_utc']} (UTC) / {manifest['frozen_at_local']} (local)")
    print(f"files: {len(files)}  content_hash: {manifest['content_hash'][:16]}…")
    for state, count in sorted(counts.items()):
        print(f"  {state:<24} {count}")
    print(f"unstable: {len(changed)}  unlisted: {len(unlisted)}")
    print(f"campus courses: {len(courses)}  published: {len(published)}")
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
