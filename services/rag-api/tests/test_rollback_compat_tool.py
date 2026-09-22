"""The rollback-compatibility tool must not report an unverified pool filter as safe.

Reproduced before the fix: ``pool_filter_unchanged`` was
``bool(current_pool_filter())`` - the *current* tree's own filter, read from
``services/rag-api/app/learning/assessments.py``, with the release tree never
consulted. The field therefore read ``true`` for every release, including one whose
pool filter had changed and one whose source contained no such predicate at all,
while the module docstring promised "is the assessment pool filter unchanged, so old
and new code select the same pool?". A release-safety report that cannot say no is
worse than one that says nothing.

These tests pin the three states the comparison can now report (``UNCHANGED``,
``CHANGED``, ``UNDETERMINED``), that the field is ``False`` whenever the two trees
were not actually compared, and that ``main()`` still reaches both of its verdicts.
The end-to-end cases drive ``main()`` with a synthesised release tree, because a
tool whose negative path is never executed is exactly how the false field survived.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "scripts"
CURRENT_SERVICE = REPO_ROOT / "services" / "rag-api"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import verify_rollback_compat as tool  # noqa: E402  (import after the path insert)

# A pool filter shaped like the real one, in the two forms the comparison must
# handle. The re-indented variant has the same SQL tokens and different whitespace.
POOL_SOURCE = (
    "SELECT question.id FROM assessment_question_revisions AS question "
    "WHERE question.course_id=? "
    "AND question.validation_status='VALIDATED' "
    "AND question.verification_method!='MODEL_ONLY' "
    "AND NOT EXISTS(SELECT 1 FROM assessment_exposure_events AS exposure "
    "WHERE exposure.question_revision_id=question.id)"
)
POOL_SOURCE_REINDENTED = (
    "SELECT question.id FROM assessment_question_revisions AS question\n"
    "WHERE question.course_id=?\n"
    "  AND question.validation_status='VALIDATED'\n"
    "  AND question.verification_method!='MODEL_ONLY'\n"
    "  AND NOT EXISTS(SELECT 1 FROM assessment_exposure_events AS exposure\n"
    "      WHERE exposure.question_revision_id=question.id)"
)
# The behavioural change this check exists to catch: the pool is now owner-scoped.
POOL_SOURCE_OWNER_SCOPED = (
    "SELECT question.id FROM assessment_question_revisions AS question "
    "WHERE question.course_id=? "
    "AND question.validation_status='VALIDATED' "
    "AND question.owner_user_id=? "
    "AND question.verification_method!='MODEL_ONLY' "
    "AND NOT EXISTS(SELECT 1 FROM assessment_exposure_events AS exposure "
    "WHERE exposure.question_revision_id=question.id)"
)


def _write_pool_source(root: pathlib.Path, text: str) -> None:
    path = root / tool.ASSESSMENTS_SOURCE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_pool_filter_in_reads_the_predicate_from_the_given_tree(tmp_path: pathlib.Path) -> None:
    _write_pool_source(tmp_path, POOL_SOURCE)
    assert tool.pool_filter_in(tmp_path) == (
        "validation_status='VALIDATED' "
        "AND question.verification_method!='MODEL_ONLY'"
    )
    # A tree that is not a service tree has no predicate to compare.
    assert tool.pool_filter_in(tmp_path / "absent") == ""


def test_pool_filter_in_is_empty_when_the_predicate_was_rewritten(
    tmp_path: pathlib.Path,
) -> None:
    """A filter that no longer excludes MODEL_ONLY must not read as extractable."""
    _write_pool_source(tmp_path, "SELECT 1 FROM assessment_question_revisions")
    assert tool.pool_filter_in(tmp_path) == ""


def test_compare_reports_unchanged_only_for_the_same_predicate(
    tmp_path: pathlib.Path,
) -> None:
    release, current = tmp_path / "release", tmp_path / "current"
    _write_pool_source(release, POOL_SOURCE)
    _write_pool_source(current, POOL_SOURCE)
    verdict, release_filter, current_filter, detail = tool.compare_pool_filters(release, current)
    assert verdict == "UNCHANGED"
    assert release_filter == current_filter
    assert detail == "byte-identical predicate"

    # Re-indentation is a whitespace-only difference: same SQL, same pool.
    _write_pool_source(release, POOL_SOURCE_REINDENTED)
    verdict, _, _, detail = tool.compare_pool_filters(release, current)
    assert verdict == "UNCHANGED"
    assert detail == "identical after whitespace normalisation"


def test_compare_reports_changed_for_a_different_pool(tmp_path: pathlib.Path) -> None:
    """Negative control: the old implementation could not express this state."""
    release, current = tmp_path / "release", tmp_path / "current"
    _write_pool_source(release, POOL_SOURCE_OWNER_SCOPED)
    _write_pool_source(current, POOL_SOURCE)
    verdict, release_filter, current_filter, detail = tool.compare_pool_filters(release, current)
    assert verdict == "CHANGED"
    assert "owner_user_id" in release_filter
    assert "owner_user_id" not in current_filter
    assert detail == "the two predicates select different pools"


def test_compare_reports_undetermined_when_the_release_has_no_predicate(
    tmp_path: pathlib.Path,
) -> None:
    """The sharpest false assurance: an absent release predicate read as ``true``."""
    release, current = tmp_path / "release", tmp_path / "current"
    _write_pool_source(current, POOL_SOURCE)
    verdict, release_filter, _, detail = tool.compare_pool_filters(release, current)
    assert (verdict, release_filter) == ("UNDETERMINED", "")
    assert "not found in the release source" in detail

    # Same when the predicate exists on neither side.
    verdict, _, _, detail = tool.compare_pool_filters(release, tmp_path / "absent")
    assert verdict == "UNDETERMINED"
    assert "not found in the release or current source" in detail


def test_run_old_release_names_a_probe_that_did_not_print_an_object(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A release that prints parseable non-object JSON must not crash the report.

    ``main()`` immediately does ``old.get(...)``, so returning a list would die with an
    opaque ``AttributeError`` instead of naming the cause.
    """
    monkeypatch.setattr(tool, "OLD_PROBE", "print('[1, 2, 3]')\n")
    with pytest.raises(RuntimeError, match="did not print a JSON object"):
        tool.run_old_release(tmp_path / "service", tmp_path / "migrated.sqlite3")


def _fake_release_tree(root: pathlib.Path, *, config: str, db: str) -> pathlib.Path:
    """A release tree that satisfies the tool's layout check but is not the app."""
    service = root / "release" / "services" / "rag-api"
    (service / "app").mkdir(parents=True)
    (service / "app" / "config.py").write_text(config, encoding="utf-8")
    (service / "app" / "db.py").write_text(db, encoding="utf-8")
    return root / "release"


def _run_tool(
    monkeypatch: pytest.MonkeyPatch, tree: pathlib.Path, out: pathlib.Path
) -> tuple[int, dict[str, object]]:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_rollback_compat.py",
            "--release-tree",
            str(tree),
            "--out",
            str(out),
        ],
    )
    code = tool.main()
    assert out.is_file(), f"the tool wrote no report (exit {code})"
    return code, json.loads(out.read_text(encoding="utf-8"))


def test_main_requires_a_db_restore_when_the_release_cannot_import(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control for the verdict itself: the tool must be able to say no."""
    tree = _fake_release_tree(tmp_path, config="", db="")
    code, report = _run_tool(monkeypatch, tree, tmp_path / "report.json")
    assert code == 3
    assert report["verdict"] == "ROLLBACK_REQUIRES_DB_RESTORE"
    assert report["release_import_error"]
    assert any("import failed" in reason for reason in report["reasons"])
    # The release tree has no assessments.py, so nothing was compared and the
    # report must not claim the pool filter is unchanged.
    assert report["pool_filter_unchanged"] is False
    assert report["pool_filter_verdict"] == "UNDETERMINED"
    assert report["rollback_concerns"]


def test_main_analyses_a_release_that_prints_non_locale_bytes(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The release's output is arbitrary prior code and may not be decodable.

    ``subprocess.run(text=True)`` without an explicit encoding uses the locale codec
    (cp936 on this machine), whose reader thread dies on such bytes - the tool then
    reported "the previous release printed nothing" instead of the release's real
    failure. The 0x80 byte below is invalid in both cp936 and UTF-8, so this asserts
    the same thing under either locale.
    """
    config = (
        "import sys\n"
        "sys.stdout.buffer.write(b'release log \\x80\\x81\\n')\n"
        "sys.stdout.buffer.flush()\n"
    )
    tree = _fake_release_tree(tmp_path, config=config, db="")
    code, report = _run_tool(monkeypatch, tree, tmp_path / "report.json")
    assert code == 3
    assert report["release_import_error"]
    assert report["verdict"] == "ROLLBACK_REQUIRES_DB_RESTORE"


def test_main_reports_unchanged_for_a_tree_that_is_a_copy_of_this_one(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Positive control: the field is ``true`` when the two trees really agree.

    The release tree is a copy of this tree's own service, so the old release can run
    against the migrated database and the pool filters are byte-identical. Without a
    case like this, "the comparison works" would itself be untested.
    """
    tree = tmp_path / "release" / "services" / "rag-api"
    shutil.copytree(CURRENT_SERVICE / "app", tree / "app")
    # The app reads its migration SQL from the service directory, so a tree without
    # migrations/ reports "cannot open the migrated database" for the wrong reason.
    shutil.copytree(CURRENT_SERVICE / "migrations", tree / "migrations")
    code, report = _run_tool(monkeypatch, tmp_path / "release", tmp_path / "report.json")
    assert code == 0
    assert report["verdict"] == "ROLLBACK_SAFE_WITH_MIGRATED_DB"
    assert report["reasons"] == []
    assert report["pool_filter_verdict"] == "UNCHANGED"
    assert report["pool_filter_unchanged"] is True
    assert report["rollback_concerns"] == []
    assert report["pool_filter_release"] == report["pool_filter_current"]
    assert report["pool_filter_release"] != ""
