"""Build a verified, classified inventory of the local Canvas download roots.

Requirement (CourseJesus pack, task C1):
只读扫描 D:\\Canvas、D:\\Canvas-DG 及两个 _download_manifest.csv，核对实际文件、来源、
学期、课程 ID、大小与 hash；不要重新向 Canvas 下载已经在本地的文件。

This tool only reads: it stats, hashes and classifies. It never downloads, never moves,
never deletes and never writes into the source roots. Every row carries both sides of the
comparison -- what the manifest claims and what is actually on disk -- so a missing file,
an unlisted file, a size mismatch or a duplicate can be seen instead of averaged away.

Classification is deterministic and conservative. It decides only what a *reviewer* should
look at; it never decides that something may be published. `publication_basis` defaults to
an unverified platform-intent value and `review_status` defaults to NEEDS_REVIEW, because a
student's ability to download a file with their own token (or an MIT licence on a tool) is
not a licence to redistribute course material to every registered user.

Usage:
    python scripts/scan_campus_inventory.py \
        --root D:\\Canvas --root D:\\Canvas-DG \
        --out docs/coursejesus/LOCAL_CAMPUS_INVENTORY.csv \
        --full-out work/current-change/campus-inventory-full.csv \
        --summary work/current-change/campus-inventory-summary.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import re
import sys
from collections.abc import Callable, Iterable, Iterator
from typing import Any

# The growth guard lives with the service code. This script is documented to run from the
# repository root without PYTHONPATH, so make the service package importable here rather than
# silently depending on the caller's environment.
_SERVICE_ROOT = pathlib.Path(__file__).resolve().parents[1] / "services" / "rag-api"
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from app.campus_growth import (
    CampusCatalogGrowthPaused,
    require_growth_open,
)

MANIFEST_NAME = "_download_manifest.csv"
HASH_CHUNK = 1024 * 1024

# Source-root -> institution mapping. The manifests carry no institution column, so this
# is a *convention* from the owner's download setup, recorded as such in every row rather
# than presented as Canvas API evidence.
SOURCE_ROOTS: dict[str, dict[str, str]] = {
    "canvas": {
        "institution_origin": "https://canvas.cityu.edu.hk",
        "institution_label": "CityU",
        "institution_basis": "SOURCE_ROOT_CONVENTION",
    },
    "canvas-dg": {
        "institution_origin": "https://cityu-dg.instructure.com",
        "institution_label": "CityU(DG)",
        "institution_basis": "SOURCE_ROOT_CONVENTION",
    },
}

CATEGORIES = (
    "ACADEMIC_TEACHING",
    "INFORMATION",
    "TRAINING",
    "PERSONAL_OR_RESTRICTED",
    "UNKNOWN_REVIEW",
)

# Directory names that mark an information/notice board rather than teaching material.
INFORMATION_DIRS = ("信息板块", "announcement", "announcements", "scholarship", "news", "notice")
TRAINING_MARKERS = ("training", "mandatory", "induction", "safety", "ohs", "orientation", "workshop")
# Privacy markers. English ones are matched on word boundaries, because substring matching
# produced two false positives on the real inventory: `Grader.java` / `IGrade.java` (Java
# starter code whose class names contain "grade") and `...personality and emotion....pdf`
# (contains "personal"). A privacy classifier that cries wolf on programming exercises
# stops being read. Chinese markers have no word boundaries and stay substring matches.
RESTRICTED_MARKERS_EN = (
    "grade", "grades", "score", "scores", "marks", "transcript", "roster", "student_list",
    "studentlist", "attendance", "submission", "submissions", "personal", "individual",
    "feedback", "answer_key", "answers", "answer", "solution_manual", "id_card", "passport",
)
RESTRICTED_MARKERS_CJK = (
    "成绩", "成绩单", "分数", "名单", "学号", "姓名", "考勤", "个人", "答案", "分组",
    "花名册", "联系方式", "报名表",
)
ACADEMIC_DIRS = ("主课", "lecture", "lectures", "tutorial", "tutorials", "lab", "labs",
                 "assignment", "assignments", "coursework", "notes", "slides")
PARSEABLE_SUFFIXES = {
    ".pdf", ".txt", ".md", ".csv", ".html", ".htm", ".docx", ".doc", ".pptx", ".ppt",
    ".xlsx", ".xls", ".ipynb", ".java", ".py", ".c", ".cpp", ".h", ".js", ".ts", ".css",
    ".json", ".xml", ".sql", ".rtf",
}
DOWNLOAD_ONLY_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".mp3", ".wav", ".zip", ".rar",
                          ".7z", ".tar", ".gz", ".iso", ".exe", ".dmg", ".msg"}

MIME_BY_SUFFIX = {
    ".pdf": "application/pdf", ".zip": "application/zip", ".png": "image/png",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel", ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ipynb": "application/x-ipynb+json", ".mp4": "video/mp4", ".txt": "text/plain",
    ".html": "text/html", ".css": "text/css", ".java": "text/x-java-source",
    ".csv": "text/csv", ".msg": "application/vnd.ms-outlook",
}

COLUMNS = (
    "source_root", "institution_origin", "institution_basis", "term", "course_id",
    "course_code", "course_name", "source_file_id", "summary_category", "relative_path",
    "filename", "bytes_disk", "bytes_manifest", "sha256", "mime_guess", "parse_class",
    "classification", "classification_reason", "duplicate_group", "same_name_group",
    "manifest_status", "disk_status", "publication_basis", "review_status", "notes",
)


def normalise(path: str | pathlib.Path) -> str:
    return str(path).replace("/", "\\").rstrip("\\").lower()


def restricted_marker(text: str) -> str | None:
    """The privacy marker in ``text``, if any.

    English markers must start at a boundary and must not be followed by a lowercase
    letter: that keeps ``personality`` and ``Grader.java`` out (they contain ``personal``
    and ``grade``), while still catching compounds whose next word is capitalised --
    ``AttendanceLog.txt`` and ``StudentList.txt`` -- and ``grades_final.xlsx``. CJK
    markers have no word boundaries and stay substring matches.
    """
    for marker in RESTRICTED_MARKERS_EN:
        # The case-insensitivity is scoped to the marker itself: a plain re.IGNORECASE would
        # also case-fold the lookahead class, making `(?![a-z])` mean "not followed by any
        # letter" and blocking the capitalised compounds this must still catch.
        pattern = rf"(?<![A-Za-z])(?i:{re.escape(marker)})(?![a-z])"
        if re.search(pattern, text):
            return marker
    for marker in RESTRICTED_MARKERS_CJK:
        if marker in text:
            return marker
    return None


def classify(relative: pathlib.Path, root_key: str) -> tuple[str, str]:
    """Deterministic category + reason. Never returns a publishable verdict."""
    parts = [p.lower() for p in relative.parts]
    name = relative.name
    haystack = " ".join(parts)
    # Privacy first: a student list inside a workshop course is personal data, not training
    # material, so the restricted check must win over the training check.
    marker = restricted_marker(name)
    if marker:
        return "PERSONAL_OR_RESTRICTED", f"filename contains {marker!r}"
    marker = restricted_marker(str(relative))
    if marker:
        return "PERSONAL_OR_RESTRICTED", f"path contains {marker!r}"
    for info in INFORMATION_DIRS:
        if any(info in part for part in parts[:-1]):
            return "INFORMATION", f"path is under an information/scholarship area ({info!r})"
    for training in TRAINING_MARKERS:
        if training in haystack:
            return "TRAINING", f"path or name marks training material ({training!r})"
    if any(marker in haystack for marker in ACADEMIC_DIRS):
        return "ACADEMIC_TEACHING", "path is a teaching-material area"
    if root_key == "canvas-dg" and len(relative.parts) >= 3:
        # DG roots are <term>/<course>/<file>, i.e. course material by layout.
        return "ACADEMIC_TEACHING", "file sits directly inside a term/course layout"
    return "UNKNOWN_REVIEW", "no rule matched; needs a human look"


def parse_class(suffix: str) -> str:
    if suffix in PARSEABLE_SUFFIXES:
        return "PARSEABLE"
    if suffix in DOWNLOAD_ONLY_SUFFIXES:
        return "DOWNLOAD_ONLY"
    return "UNKNOWN"


def stream_sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_manifest(path: pathlib.Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def iter_disk_files(root: pathlib.Path) -> Iterator[pathlib.Path]:
    for entry in root.rglob("*"):
        if entry.is_symlink():
            continue
        if entry.is_file():
            yield entry


def scan_root(
    root: pathlib.Path, *, do_hash: bool, log: Callable[[str], None]
) -> dict[str, Any]:
    root_key = root.name.lower()
    manifest_path = root / MANIFEST_NAME
    detail = SOURCE_ROOTS.get(root_key, {
        "institution_origin": "UNKNOWN",
        "institution_label": "UNKNOWN",
        "institution_basis": "UNRECOGNISED_SOURCE_ROOT",
    })
    if not root.is_dir():
        raise SystemExit(f"source root not found: {root}")
    fields, manifest_rows = read_manifest(manifest_path) if manifest_path.is_file() else ([], [])
    log(f"{root}: manifest={manifest_path.name if fields else 'ABSENT'} rows={len(manifest_rows)} fields={fields}")

    disk = {normalise(p.relative_to(root)): p for p in iter_disk_files(root)}
    log(f"{root}: disk files={len(disk)}")

    rows: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for index, record in enumerate(manifest_rows):
        raw_path = (record.get("path") or "").strip()
        rel = pathlib.Path(raw_path)
        try:
            rel = rel.relative_to(root)
        except ValueError:
            rel = pathlib.Path(rel.name)
        key = normalise(rel)
        seen_paths.add(key)
        disk_path = disk.get(key)
        manifest_bytes = record.get("bytes") or ""
        try:
            manifest_size = int(manifest_bytes)
        except ValueError:
            manifest_size = -1
        manifest_status = record.get("status") or ""
        if disk_path is None:
            disk_status, disk_size, digest = "MISSING_ON_DISK", -1, ""
        else:
            disk_size = disk_path.stat().st_size
            digest = stream_sha256(disk_path) if do_hash else ""
            if manifest_size >= 0 and manifest_size != disk_size:
                disk_status = "SIZE_MISMATCH"
            else:
                disk_status = "PRESENT"
        category, reason = classify(rel, root_key)
        suffix = rel.suffix.lower()
        rows.append({
            "source_root": str(root),
            "institution_origin": detail["institution_origin"],
            "institution_basis": detail["institution_basis"],
            "term": record.get("term", ""),
            "course_id": record.get("course_id", ""),
            "course_code": record.get("course_code", ""),
            "course_name": record.get("course", ""),
            "source_file_id": record.get("file_id", ""),
            "summary_category": record.get("category", ""),
            "relative_path": str(rel),
            "filename": rel.name,
            "bytes_disk": disk_size if disk_size >= 0 else "",
            "bytes_manifest": manifest_size if manifest_size >= 0 else "",
            "sha256": digest,
            "mime_guess": MIME_BY_SUFFIX.get(suffix, ""),
            "parse_class": parse_class(suffix),
            "classification": category,
            "classification_reason": reason,
            "duplicate_group": "",
            "same_name_group": "",
            "manifest_status": manifest_status,
            "disk_status": disk_status,
            "publication_basis": "OWNER_PLATFORM_IMPORT_INTENT_RIGHTS_UNVERIFIED",
            "review_status": "NEEDS_REVIEW",
            "notes": "" if record.get("file_id", "").strip() else "manifest has no file_id column/value",
        })
        if index % 500 == 0 and index:
            log(f"{root}: hashed {index}/{len(manifest_rows)}")

    for key, path in sorted(disk.items()):
        if key in seen_paths:
            continue
        rel = path.relative_to(root)
        if rel.name == MANIFEST_NAME:
            rows.append({
                "source_root": str(root),
                "institution_origin": detail["institution_origin"],
                "institution_basis": detail["institution_basis"],
                "term": "", "course_id": "", "course_code": "", "course_name": "",
                "source_file_id": "", "summary_category": "", "relative_path": str(rel),
                "filename": rel.name, "bytes_disk": path.stat().st_size, "bytes_manifest": "",
                "sha256": stream_sha256(path) if do_hash else "", "mime_guess": "text/csv",
                "parse_class": "PARSEABLE", "classification": "UNKNOWN_REVIEW",
                "classification_reason": "the manifest file itself, kept as a source record",
                "duplicate_group": "", "same_name_group": "", "manifest_status": "",
                # Its own status, so it never inflates the "on disk but not in the manifest"
                # count that a reviewer reads as unaccounted-for course material.
                "disk_status": "SOURCE_MANIFEST",
                "publication_basis": "INTERNAL_SOURCE_RECORD",
                "review_status": "NOT_FOR_PUBLICATION",
                "notes": "source manifest, never a course file",
            })
            continue
        category, reason = classify(rel, root_key)
        rows.append({
            "source_root": str(root),
            "institution_origin": detail["institution_origin"],
            "institution_basis": detail["institution_basis"],
            "term": rel.parts[0] if len(rel.parts) > 1 else "",
            "course_id": "", "course_code": "", "course_name": "",
            "source_file_id": "", "summary_category": "", "relative_path": str(rel),
            "filename": rel.name, "bytes_disk": path.stat().st_size, "bytes_manifest": "",
            "sha256": stream_sha256(path) if do_hash else "",
            "mime_guess": MIME_BY_SUFFIX.get(rel.suffix.lower(), ""),
            "parse_class": parse_class(rel.suffix.lower()),
            "classification": category, "classification_reason": reason,
            "duplicate_group": "", "same_name_group": "", "manifest_status": "",
            "disk_status": "NOT_IN_MANIFEST",
            "publication_basis": "OWNER_PLATFORM_IMPORT_INTENT_RIGHTS_UNVERIFIED",
            "review_status": "NEEDS_REVIEW",
            "notes": "present on disk but absent from the manifest",
        })
    return {"root": str(root), "institution": detail, "manifest_fields": fields, "rows": rows}


def annotate_groups(rows: list[dict[str, Any]]) -> None:
    by_hash: dict[str, list[dict[str, Any]]] = {}
    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row["sha256"]:
            by_hash.setdefault(row["sha256"], []).append(row)
        if row["filename"]:
            by_name.setdefault(row["filename"].lower(), []).append(row)
    for index, (digest, group) in enumerate(sorted(by_hash.items()), start=1):
        if len(group) > 1:
            label = f"D{index:04d}"
            for row in group:
                row["duplicate_group"] = label
                row["notes"] = (row["notes"] + "; " if row["notes"] else "") + (
                    f"byte-identical to {len(group) - 1} other file(s)"
                )
    labelled = 0
    for name, group in sorted(by_name.items()):
        ids = {row["source_file_id"] for row in group if row["source_file_id"]}
        if len(group) > 1 and len(ids) > 1:
            labelled += 1
            label = f"N{labelled:04d}"
            for row in group:
                row["same_name_group"] = label
            for row in group:
                row["notes"] = (row["notes"] + "; " if row["notes"] else "") + (
                    f"same name, different Canvas file id ({len(ids)} ids)"
                )


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def counter(field: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in rows:
            key = str(row[field]) or "(empty)"
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items(), key=lambda item: -item[1]))

    published_candidates = [
        row for row in rows
        if row["classification"] == "ACADEMIC_TEACHING" and row["disk_status"] == "PRESENT"
        and row["review_status"] == "NEEDS_REVIEW"
    ]
    return {
        "rows": len(rows),
        "bytes_disk": sum(int(row["bytes_disk"]) for row in rows if str(row["bytes_disk"]).isdigit()),
        "by_classification": counter("classification"),
        "by_disk_status": counter("disk_status"),
        "by_parse_class": counter("parse_class"),
        "by_source_root": counter("source_root"),
        "by_course_id": counter("course_id"),
        "by_term": counter("term"),
        "duplicate_groups": len({row["duplicate_group"] for row in rows if row["duplicate_group"]}),
        "same_name_groups": len({row["same_name_group"] for row in rows if row["same_name_group"]}),
        "academic_candidates_present": len(published_candidates),
        "publishable_now": 0,
        "publishable_now_note": (
            "no file is publishable from this scan: every row needs a rights/publication "
            "decision, and this tool deliberately never grants one"
        ),
    }


REDACTED = "REDACTED_PERSONAL_OR_RESTRICTED"


def write_csv(rows: Iterable[dict[str, Any]], path: pathlib.Path, *, redact: bool) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        # Explicit LF: the default csv terminator is CRLF, which would make the committed
        # artefact differ from a regenerated one on a repository that stores LF.
        writer = csv.DictWriter(handle, fieldnames=list(COLUMNS), lineterminator=chr(10))
        writer.writeheader()
        for row in rows:
            out = dict(row)
            if redact and out["classification"] == "PERSONAL_OR_RESTRICTED":
                # The committed inventory must not leak personal filenames into Git; the
                # unredacted copy stays in work/ for processing. Identity of the file is
                # preserved by hash, size and course so a reviewer can still act on it.
                out["relative_path"] = REDACTED
                out["filename"] = REDACTED
                out["notes"] = (out["notes"] + "; " if out["notes"] else "") + (
                    "name redacted in the committed inventory"
                )
            writer.writerow(out)
            written += 1
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", required=True, type=pathlib.Path)
    parser.add_argument("--out", required=True, type=pathlib.Path)
    parser.add_argument("--full-out", type=pathlib.Path, default=None)
    parser.add_argument("--summary", type=pathlib.Path, default=None)
    parser.add_argument("--no-hash", action="store_true", help="skip SHA-256 (size only)")
    arguments = parser.parse_args()

    # Discovery is the first half of "growth" and is closed since the final batch was frozen
    # (2026-09-24). The check sits before the first walk of a source root, so a paused run does
    # not even stat the download directories. Pure helpers (`scan_root`, `classify`, `summarise`)
    # stay callable: the test suite drives them against temporary roots, and reporting on the
    # frozen inventory must remain possible.
    try:
        require_growth_open(f"scan {', '.join(str(r) for r in arguments.root)} for new campus material")
    except CampusCatalogGrowthPaused as paused:
        print(str(paused), file=sys.stderr)
        return 3

    def log(message: str) -> None:
        print(message, flush=True)

    all_rows: list[dict[str, Any]] = []
    per_root: list[dict[str, Any]] = []
    for root in arguments.root:
        result = scan_root(root.resolve(), do_hash=not arguments.no_hash, log=log)
        all_rows.extend(result["rows"])
        per_root.append({
            "root": result["root"],
            "institution": result["institution"],
            "manifest_fields": result["manifest_fields"],
            "rows": len(result["rows"]),
        })

    annotate_groups(all_rows)
    all_rows.sort(key=lambda row: (row["source_root"], row["course_id"], row["relative_path"]))
    summary = summarise(all_rows)
    summary["per_root"] = per_root

    if arguments.full_out:
        write_csv(all_rows, arguments.full_out, redact=False)
        log(f"full inventory: {arguments.full_out}")
    written = write_csv(all_rows, arguments.out, redact=True)
    log(f"committed inventory: {arguments.out} ({written} rows, personal names redacted)")
    if arguments.summary:
        arguments.summary.parent.mkdir(parents=True, exist_ok=True)
        arguments.summary.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        log(f"summary: {arguments.summary}")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
