"""The campus inventory scan must report differences instead of averaging them away.

Task C1 asks for a real reconciliation of two local Canvas download roots: "核对实际文件、
来源、学期、课程 ID、大小与 hash". The failure mode this file guards against is an inventory
that looks complete because it only echoes the manifests -- a missing file, an unlisted
file, a wrong size or a duplicate would all be invisible, and a reviewer would sign off on
a list that does not describe the disk.

It also pins the two boundaries the pack is explicit about: classification never grants a
publication right (so `publishable_now` is 0 by construction), and the committed CSV must
not leak personal filenames into Git while the working copy keeps them.
"""

from __future__ import annotations

import csv
import json
import os
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import scan_campus_inventory as scan  # noqa: E402  (import after the path insert)

MAIN_FIELDS = ("course_id", "course", "category", "filename", "bytes", "path", "status")
DG_FIELDS = (
    "course_id", "course", "term", "course_code", "file_id", "filename", "bytes", "path",
    "status",
)
CS4182 = "CS4182 Computer Graphics"


def _manifest(root: pathlib.Path, fields, rows) -> None:
    path = root / scan.MANIFEST_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _file(root: pathlib.Path, relative: str, data: bytes = b"lecture") -> pathlib.Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _main_row(root: pathlib.Path, category: str, course: str, name: str, size: int) -> dict:
    return {
        "course_id": "70574", "course": course, "category": category, "filename": name,
        "bytes": str(size), "path": str(root / category / course / name),
        "status": "downloaded",
    }


def _dg_row(
    root: pathlib.Path, term: str, course: str, name: str, size: int, file_id: str
) -> dict:
    return {
        "course_id": "214", "course": course, "term": term, "course_code": "PE1911",
        "file_id": file_id, "filename": name, "bytes": str(size),
        "path": str(root / term / course / name), "status": "downloaded",
    }


def _main_root(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "Canvas"
    lecture = rf"01_主课\{CS4182}\Lecture_01.pdf"
    assignment = rf"01_主课\{CS4182}\Assignment_01.zip"
    notice = r"03_信息板块\CS Announcement\Notice.pdf"
    _file(root, lecture, b"a" * 100)
    _file(root, assignment, b"b" * 50)
    _file(root, notice, b"c" * 10)
    _manifest(root, MAIN_FIELDS, [
        _main_row(root, "01_主课", CS4182, "Lecture_01.pdf", 100),
        _main_row(root, "01_主课", CS4182, "Assignment_01.zip", 50),
        _main_row(root, "03_信息板块", "CS Announcement", "Notice.pdf", 10),
    ])
    return root


def _run(tmp_path: pathlib.Path, roots):
    outputs = tmp_path / "out"
    committed = outputs / "inventory.csv"
    full = outputs / "inventory-full.csv"
    summary_path = outputs / "summary.json"
    results = [scan.scan_root(root, do_hash=True, log=lambda *_: None) for root in roots]
    rows = [row for result in results for row in result["rows"]]
    scan.annotate_groups(rows)
    rows.sort(key=lambda row: (row["source_root"], row["course_id"], row["relative_path"]))
    summary = scan.summarise(rows)
    scan.write_csv(rows, full, redact=False)
    scan.write_csv(rows, committed, redact=True)
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return rows, summary, committed, full


def _by_name(rows) -> dict[str, dict[str, object]]:
    return {str(row["filename"]): row for row in rows}


def test_manifest_rows_are_joined_to_disk_with_size_and_hash(tmp_path: pathlib.Path) -> None:
    rows, summary, _, _ = _run(tmp_path, [_main_root(tmp_path)])
    # three course files plus the manifest itself, which is recorded as a source record
    assert summary["rows"] == 4
    assert summary["by_disk_status"] == {"PRESENT": 3, "SOURCE_MANIFEST": 1}
    lecture = _by_name(rows)["Lecture_01.pdf"]
    assert lecture["disk_status"] == "PRESENT"
    assert lecture["bytes_disk"] == 100
    assert len(str(lecture["sha256"])) == 64
    assert lecture["classification"] == "ACADEMIC_TEACHING"
    assert lecture["parse_class"] == "PARSEABLE"
    # The institution comes from the source-root convention, and says so: the manifests
    # carry no institution column, so this is never presented as Canvas API evidence.
    assert lecture["institution_origin"] == "https://canvas.cityu.edu.hk"
    assert lecture["institution_basis"] == "SOURCE_ROOT_CONVENTION"


def test_an_unrecognised_source_root_is_labelled_unknown(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "SomeOtherDownload"
    _file(root, r"01_主课\CS1\Lecture_01.pdf", b"a" * 10)
    _manifest(root, MAIN_FIELDS, [
        _main_row(root, "01_主课", "CS1", "Lecture_01.pdf", 10),
    ])
    rows, _, _, _ = _run(tmp_path, [root])
    lecture = _by_name(rows)["Lecture_01.pdf"]
    assert lecture["institution_origin"] == "UNKNOWN"
    assert lecture["institution_basis"] == "UNRECOGNISED_SOURCE_ROOT"


def test_information_area_is_not_a_course_candidate(tmp_path: pathlib.Path) -> None:
    rows, summary, _, _ = _run(tmp_path, [_main_root(tmp_path)])
    notice = _by_name(rows)["Notice.pdf"]
    assert notice["classification"] == "INFORMATION"
    assert summary["academic_candidates_present"] == 2  # the two 01_主课 files only
    # Having candidates is not having permission: the count of publishable files is 0 even
    # here, where two academic candidates exist. Without this assertion the suite still
    # passed when the field was changed to count candidates as publishable.
    assert summary["publishable_now"] == 0


def test_missing_unlisted_and_resized_files_are_all_reported(tmp_path: pathlib.Path) -> None:
    root = _main_root(tmp_path)
    # 1. a manifest row whose file is gone
    (root / rf"01_主课\{CS4182}\Assignment_01.zip").unlink()
    # 2. a file that exists but is not in the manifest
    _file(root, rf"01_主课\{CS4182}\Tutorial_02.pdf", b"d" * 20)
    # 3. a manifest row whose byte count is wrong
    _manifest(root, MAIN_FIELDS, [
        _main_row(root, "01_主课", CS4182, "Lecture_01.pdf", 999),
        _main_row(root, "01_主课", CS4182, "Assignment_01.zip", 50),
    ])
    rows, summary, _, _ = _run(tmp_path, [root])
    statuses = {str(row["filename"]): row["disk_status"] for row in rows}
    assert statuses["Lecture_01.pdf"] == "SIZE_MISMATCH"
    assert statuses["Assignment_01.zip"] == "MISSING_ON_DISK"
    assert statuses["Tutorial_02.pdf"] == "NOT_IN_MANIFEST"
    # Notice.pdf still exists on disk but the rewritten manifest no longer lists it, so a
    # shrunk manifest shows up as unaccounted-for files rather than silently disappearing
    assert statuses["Notice.pdf"] == "NOT_IN_MANIFEST"
    assert summary["by_disk_status"]["NOT_IN_MANIFEST"] == 2
    assert summary["by_disk_status"]["SOURCE_MANIFEST"] == 1
    # the manifest file itself is recorded, but never as a course file
    manifest_row = _by_name(rows)[scan.MANIFEST_NAME]
    assert manifest_row["review_status"] == "NOT_FOR_PUBLICATION"
    assert manifest_row["disk_status"] == "SOURCE_MANIFEST"


def test_restricted_names_are_classified_and_never_publishable(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "Canvas"
    _file(root, r"01_主课\CS4182\grades_final.xlsx", b"x" * 10)
    _manifest(root, MAIN_FIELDS, [
        _main_row(root, "01_主课", "CS4182", "grades_final.xlsx", 10),
    ])
    rows, summary, _, _ = _run(tmp_path, [root])
    restricted = _by_name(rows)["grades_final.xlsx"]
    assert restricted["classification"] == "PERSONAL_OR_RESTRICTED"
    assert "grade" in str(restricted["classification_reason"])
    assert summary["publishable_now"] == 0
    assert "never grants" in summary["publishable_now_note"]


def test_dg_term_layout_is_a_candidate_but_still_needs_review(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "canvas-dg"
    term = "Semester A 2024_25"
    course = "PE1911 Physical education_1A"
    _file(root, rf"{term}\{course}\lecture.mp4", b"v" * 30)
    _manifest(root, DG_FIELDS, [_dg_row(root, term, course, "lecture.mp4", 30, "13791")])
    rows, summary, _, _ = _run(tmp_path, [root])
    lecture = _by_name(rows)["lecture.mp4"]
    assert lecture["institution_origin"] == "https://cityu-dg.instructure.com"
    assert lecture["term"] == term
    assert lecture["source_file_id"] == "13791"
    assert lecture["classification"] == "ACADEMIC_TEACHING"
    assert lecture["review_status"] == "NEEDS_REVIEW"
    assert lecture["parse_class"] == "DOWNLOAD_ONLY"
    assert summary["academic_candidates_present"] == 1


def test_duplicates_and_same_name_different_ids_are_grouped(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "canvas-dg"
    term_a, term_b, course = "Semester A 2024_25", "Semester B 2025_26", "CS1"
    _file(root, rf"{term_a}\{course}\handout.pdf", b"same")
    _file(root, rf"{term_b}\{course}\handout_copy.pdf", b"same")
    _file(root, rf"{term_b}\{course}\handout.pdf", b"different")
    _manifest(root, DG_FIELDS, [
        _dg_row(root, term_a, course, "handout.pdf", 4, "111"),
        _dg_row(root, term_b, course, "handout_copy.pdf", 4, "222"),
        _dg_row(root, term_b, course, "handout.pdf", 9, "333"),
    ])
    rows, summary, _, _ = _run(tmp_path, [root])
    grouped = [
        row for row in rows if str(row["filename"]) in {"handout.pdf", "handout_copy.pdf"}
    ]
    assert len(grouped) == 3
    assert summary["duplicate_groups"] == 1  # only the two byte-identical files
    assert summary["same_name_groups"] == 1  # two handout.pdf with different file ids
    by_path = {str(row["relative_path"]): row for row in grouped}
    same_name_row = by_path[rf"{term_b}\{course}\handout.pdf"]
    assert str(same_name_row["same_name_group"]).startswith("N")
    assert "different Canvas file id" in str(same_name_row["notes"])


def test_committed_csv_redacts_personal_names_and_the_working_copy_does_not(
    tmp_path: pathlib.Path,
) -> None:
    root = tmp_path / "Canvas"
    _file(root, r"01_主课\CS4182\grades_2024.xlsx", b"x" * 10)
    _file(root, r"01_主课\CS4182\Lecture_01.pdf", b"y" * 10)
    _manifest(root, MAIN_FIELDS, [
        _main_row(root, "01_主课", "CS4182", "grades_2024.xlsx", 10),
        _main_row(root, "01_主课", "CS4182", "Lecture_01.pdf", 10),
    ])
    _, _, committed, full = _run(tmp_path, [root])
    committed_rows = list(csv.DictReader(committed.open(encoding="utf-8", newline="")))
    full_rows = list(csv.DictReader(full.open(encoding="utf-8", newline="")))
    restricted_class = "PERSONAL_OR_RESTRICTED"
    committed_restricted = next(
        row for row in committed_rows if row["classification"] == restricted_class
    )
    full_restricted = next(row for row in full_rows if row["classification"] == restricted_class)
    assert committed_restricted["filename"] == scan.REDACTED
    assert committed_restricted["relative_path"] == scan.REDACTED
    assert full_restricted["filename"] == "grades_2024.xlsx"
    # the academic row keeps its name in both, and the hash still identifies the file
    committed_academic = next(
        row for row in committed_rows if row["classification"] == "ACADEMIC_TEACHING"
    )
    full_academic = next(
        row for row in full_rows if row["relative_path"] == committed_academic["relative_path"]
    )
    assert committed_academic["filename"] == "Lecture_01.pdf"
    assert committed_academic["sha256"] == full_academic["sha256"] != ""
    assert len(committed_restricted["sha256"]) == 64
    assert "redacted in the committed inventory" in committed_restricted["notes"]


def test_scan_reads_only_and_never_writes_into_the_source_root(tmp_path: pathlib.Path) -> None:
    root = _main_root(tmp_path)
    before = {
        path.relative_to(root): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in root.rglob("*") if path.is_file()
    }
    _run(tmp_path, [root])
    after = {
        path.relative_to(root): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in root.rglob("*") if path.is_file()
    }
    assert after == before


def test_real_inventory_false_positives_are_pinned() -> None:
    """Three misclassifications found by scanning the real roots must not come back.

    On the actual inventory, substring matching put `Grader.java` / `IGrade.java` (Java
    starter code) and `...personality and emotion....pdf` into PERSONAL_OR_RESTRICTED,
    while a student grouping list inside a "Freshman Workshop" course was filed as
    TRAINING because the training check ran before the privacy check.
    """
    cs2312 = r"Semester B 2025_26\Problem Solve & Programming CS2312"
    cases = {
        rf"{cs2312}\Grader.java": "ACADEMIC_TEACHING",
        rf"{cs2312}\IGrade.java": "ACADEMIC_TEACHING",
        r"Semester A 2025_26\Management CB2300 Management"
        r"\Week 2--personality and emotion--Sep 10 2025--SV.pdf": "ACADEMIC_TEACHING",
        r"Semester B 2024_25\Freshman Workshop II ME1921 Freshman Workshop II"
        r"\学生分组.xlsx": "PERSONAL_OR_RESTRICTED",
        rf"{cs2312}\StudentList.txt": "PERSONAL_OR_RESTRICTED",
        rf"{cs2312}\AttendanceLog.txt": "PERSONAL_OR_RESTRICTED",
        r"Semester A 2024_25\University English I GE1401"
        r"\Library Orientation for GE1401.pdf": "TRAINING",
    }
    for relative, expected in cases.items():
        category, reason = scan.classify(pathlib.Path(relative), "canvas-dg")
        assert category == expected, f"{relative}: {category} ({reason})"
    # and the word-boundary markers still catch the real thing
    for relative in (r"a\grades_final.xlsx", r"a\Class_roster.pdf", r"a\Tutorial_1_answers.pdf"):
        category, reason = scan.classify(pathlib.Path(relative), "canvas")
        assert category == "PERSONAL_OR_RESTRICTED", f"{relative}: {category} ({reason})"


def test_symlinks_are_skipped_rather_than_followed(tmp_path: pathlib.Path) -> None:
    root = _main_root(tmp_path)
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"z" * 5)
    link = root / rf"01_主课\{CS4182}\link_to_outside.pdf"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError) as error:  # pragma: no cover - Windows privilege
        pytest.skip(f"cannot create symlinks here: {error}")
    rows, summary, _, _ = _run(tmp_path, [root])
    assert "link_to_outside.pdf" not in _by_name(rows)
    assert summary["rows"] == 4  # three course files plus the manifest record
