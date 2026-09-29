"""The copy guard: a target must be established, not assumed.

Every test here is a fact about a real filesystem operation performed in the test,
not a simulation of one.  Where the platform cannot perform the operation -- a
symbolic link without the privilege to create one -- the test says so and skips
rather than pretending the case was covered.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.db_target import (
    DatabaseTargetError,
    ReadOnlyDatabase,
    describe_permissions,
    read_only_connection,
    resolve_database_target,
)


def _make_db(path: Path, *, schema: int = 65) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, name TEXT)"
    )
    for version in range(1, schema + 1):
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (?, ?)",
            (version, f"m{version}"),
        )
    connection.commit()
    connection.close()
    return path


@pytest.fixture()
def layout(tmp_path: Path) -> dict[str, Path]:
    production = _make_db(tmp_path / "prod" / "rag.sqlite3")
    root = tmp_path / "work"
    root.mkdir()
    copy = _make_db(root / "copy" / "rag.sqlite3")
    return {"production": production, "root": root, "copy": copy, "tmp": tmp_path}


def _resolve(layout, *, path, purpose="MIGRATION_REHEARSAL", **overrides):
    arguments = {
        "purpose": purpose,
        "explicit_path": path,
        "allowed_root": layout["root"],
        "production_paths": (layout["production"],),
        "expected_schema": 65,
    }
    arguments.update(overrides)
    return resolve_database_target(**arguments)


# --- the two cases the previous guard got wrong ---------------------------------


def test_environment_naming_production_while_the_argument_names_a_copy_is_refused(layout) -> None:
    """The original incident: env says production, the argument says copy."""
    with pytest.raises(DatabaseTargetError) as caught:
        _resolve(layout, path=layout["copy"], environment_path=layout["production"])
    assert caught.value.code == "DATABASE_TARGET_ENVIRONMENT_MISMATCH"


def test_both_naming_production_is_still_refused(layout) -> None:
    """Agreement is not authorisation: equal production paths must not pass."""
    with pytest.raises(DatabaseTargetError) as caught:
        _resolve(layout, path=layout["production"], environment_path=layout["production"])
    assert caught.value.code == "DATABASE_TARGET_IS_PRODUCTION"


def test_the_argument_alone_naming_production_is_refused(layout) -> None:
    with pytest.raises(DatabaseTargetError) as caught:
        _resolve(layout, path=layout["production"])
    assert caught.value.code == "DATABASE_TARGET_IS_PRODUCTION"


def test_no_target_at_all_is_refused_rather_than_defaulted(layout) -> None:
    with pytest.raises(DatabaseTargetError) as caught:
        resolve_database_target(
            purpose="READ_ONLY_PROBE",
            explicit_path=None,
            allowed_root=layout["root"],
            production_paths=(layout["production"],),
        )
    assert caught.value.code == "DATABASE_TARGET_NOT_EXPLICIT"


# --- identity is not string equality ---------------------------------------------


def test_a_symlink_to_production_is_refused(layout) -> None:
    link = layout["root"] / "alias.sqlite3"
    try:
        os.symlink(layout["production"], link)
    except (OSError, NotImplementedError):
        pytest.skip("this platform/account cannot create a symbolic link")
    with pytest.raises(DatabaseTargetError) as caught:
        _resolve(layout, path=link)
    assert caught.value.code in {
        "DATABASE_TARGET_SYMLINK",
        "DATABASE_TARGET_IS_PRODUCTION",
    }


def test_a_hard_link_to_production_is_refused(layout) -> None:
    link = layout["root"] / "hardlink.sqlite3"
    try:
        os.link(layout["production"], link)
    except (OSError, NotImplementedError):
        pytest.skip("this platform/account cannot create a hard link")
    with pytest.raises(DatabaseTargetError) as caught:
        _resolve(layout, path=link)
    assert caught.value.code in {
        "DATABASE_TARGET_IS_PRODUCTION",
        "DATABASE_TARGET_HARDLINK",
    }


def test_a_hard_link_that_does_not_alias_production_is_still_refused(layout) -> None:
    """A second hard link means the file is not a private copy of anything."""
    other = _make_db(layout["root"] / "other.sqlite3")
    second = layout["root"] / "other-second-name.sqlite3"
    try:
        os.link(other, second)
    except (OSError, NotImplementedError):
        pytest.skip("this platform/account cannot create a hard link")
    with pytest.raises(DatabaseTargetError) as caught:
        _resolve(layout, path=other)
    assert caught.value.code == "DATABASE_TARGET_HARDLINK"


def test_a_case_alias_of_production_is_refused(layout) -> None:
    """On a case-insensitive filesystem the alias is the same file."""
    alias = Path(str(layout["production"]).upper())
    same_file = os.path.exists(alias) and os.path.samefile(alias, layout["production"])
    if not same_file:
        pytest.skip("this filesystem is case sensitive, so there is no alias to test")
    with pytest.raises(DatabaseTargetError) as caught:
        _resolve(layout, path=alias)
    assert caught.value.code in {
        "DATABASE_TARGET_IS_PRODUCTION",
        "DATABASE_TARGET_ENVIRONMENT_MISMATCH",
    }


def test_a_traversal_path_is_refused(layout) -> None:
    traversal = layout["root"] / ".." / "prod" / "rag.sqlite3"
    with pytest.raises(DatabaseTargetError) as caught:
        _resolve(layout, path=traversal)
    assert caught.value.code == "DATABASE_TARGET_NOT_EXPLICIT"


def test_a_target_outside_the_work_root_is_refused(layout) -> None:
    outside = _make_db(layout["tmp"] / "elsewhere.sqlite3")
    with pytest.raises(DatabaseTargetError) as caught:
        _resolve(layout, path=outside)
    assert caught.value.code == "DATABASE_TARGET_OUTSIDE_ALLOWED_ROOT"


def test_a_missing_target_is_refused_and_not_created(layout) -> None:
    missing = layout["root"] / "not-here.sqlite3"
    with pytest.raises(DatabaseTargetError) as caught:
        _resolve(layout, path=missing)
    assert caught.value.code == "DATABASE_TARGET_MISSING"
    assert not missing.exists()


def test_the_source_itself_is_not_a_valid_copy(layout) -> None:
    with pytest.raises(DatabaseTargetError) as caught:
        _resolve(layout, path=layout["copy"], source_path=layout["copy"])
    assert caught.value.code == "DATABASE_TARGET_IS_SOURCE"


def test_the_wrong_schema_is_refused(layout) -> None:
    with pytest.raises(DatabaseTargetError) as caught:
        _resolve(layout, path=layout["copy"], expected_schema=64)
    assert caught.value.code == "DATABASE_TARGET_SCHEMA_MISMATCH"
    assert caught.value.detail["observed_schema"] == 65


# --- the legitimate case ---------------------------------------------------------


def test_a_verified_distinct_copy_inside_the_work_root_is_accepted(layout) -> None:
    target = _resolve(layout, path=layout["copy"], source_path=layout["production"])
    assert target.purpose == "MIGRATION_REHEARSAL"
    assert os.path.realpath(target.path) == os.path.realpath(layout["copy"])
    assert target.identity == _resolve(
        layout, path=layout["copy"], source_path=layout["production"]
    ).identity
    assert target.source_fingerprint == hashlib.sha256(
        layout["production"].read_bytes()
    ).hexdigest()
    assert target.observed_fingerprint == hashlib.sha256(layout["copy"].read_bytes()).hexdigest()
    receipt = target.as_receipt()
    assert json.dumps(receipt, sort_keys=True)


def test_two_pointing_at_the_same_copy_is_accepted(layout) -> None:
    target = _resolve(layout, path=layout["copy"], environment_path=layout["copy"])
    assert os.path.realpath(target.path) == os.path.realpath(layout["copy"])


def test_a_production_write_must_name_a_declared_production_path(layout) -> None:
    """The one purpose whose target must be production, and only when named.

    Every other purpose refuses a production target outright.  Without this rule
    the honest installation step is impossible, and work that cannot be done
    through the guard is work that gets done around it -- which is how the
    accidental migration happened.
    """
    target = resolve_database_target(
        purpose="PRODUCTION_WRITE",
        explicit_path=layout["production"],
        allowed_root=layout["root"],
        production_paths=(layout["production"],),
        environment_path=layout["production"],
        verify_schema=False,
    )
    assert target.purpose == "PRODUCTION_WRITE"
    assert os.path.realpath(target.path) == os.path.realpath(layout["production"])

    # The same purpose pointed at something that is not production is refused.
    with pytest.raises(DatabaseTargetError) as caught:
        resolve_database_target(
            purpose="PRODUCTION_WRITE",
            explicit_path=layout["copy"],
            allowed_root=layout["root"],
            production_paths=(layout["production"],),
            verify_schema=False,
        )
    assert caught.value.code == "DATABASE_TARGET_NOT_PRODUCTION"

    # A production write may not be reached through a symlink either.
    link = layout["root"] / "prod-alias.sqlite3"
    try:
        os.symlink(layout["production"], link)
    except (OSError, NotImplementedError):
        return
    with pytest.raises(DatabaseTargetError) as caught:
        resolve_database_target(
            purpose="PRODUCTION_WRITE",
            explicit_path=link,
            allowed_root=layout["root"],
            production_paths=(layout["production"],),
            verify_schema=False,
        )
    assert caught.value.code == "DATABASE_TARGET_SYMLINK"


def test_a_source_fingerprint_can_be_demanded(layout) -> None:
    with pytest.raises(DatabaseTargetError) as caught:
        _resolve(layout, path=layout["copy"], require_source_fingerprint=True)
    assert caught.value.code == "DATABASE_TARGET_SOURCE_REQUIRED"


def test_a_read_only_identity_can_be_demanded(layout) -> None:
    if not os.access(layout["copy"], os.W_OK):
        target = _resolve(
            layout,
            path=layout["copy"],
            purpose="READ_ONLY_PROBE",
            require_no_write_permission=True,
        )
        assert target.writable_by_process is False
        return
    with pytest.raises(DatabaseTargetError) as caught:
        _resolve(
            layout,
            path=layout["copy"],
            purpose="READ_ONLY_PROBE",
            require_no_write_permission=True,
        )
    assert caught.value.code == "DATABASE_TARGET_WRITABLE_WHEN_READ_ONLY"


# --- a probe reads and never writes ----------------------------------------------


def test_the_read_only_probe_opens_mode_ro(layout) -> None:
    with read_only_connection(layout["copy"]) as connection:
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 65
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1


def test_the_read_only_probe_refuses_a_write(layout) -> None:
    with read_only_connection(layout["copy"]) as connection, pytest.raises(
        sqlite3.OperationalError
    ):
        connection.execute("CREATE TABLE should_not_exist (id INTEGER)")


def test_the_read_only_handle_refuses_to_migrate(layout) -> None:
    target = _resolve(layout, path=layout["copy"], purpose="READ_ONLY_PROBE")
    probe = ReadOnlyDatabase(target)
    assert probe.scalar("SELECT MAX(version) FROM schema_migrations") == 65
    with pytest.raises(DatabaseTargetError) as caught:
        probe.initialize()
    assert caught.value.code == "DATABASE_TARGET_READ_ONLY"
    # Nothing moved.
    assert probe.scalar("SELECT MAX(version) FROM schema_migrations") == 65


def test_a_writable_purpose_cannot_use_the_read_only_handle(layout) -> None:
    target = _resolve(layout, path=layout["copy"])
    with pytest.raises(DatabaseTargetError) as caught:
        ReadOnlyDatabase(target)
    assert caught.value.code == "DATABASE_TARGET_PURPOSE"


def test_the_read_only_probe_never_creates_a_missing_database(layout) -> None:
    missing = layout["root"] / "probe-created.sqlite3"
    with pytest.raises(sqlite3.OperationalError), read_only_connection(missing) as connection:
        connection.execute("SELECT 1")
    assert not missing.exists()


def test_permission_facts_are_reported(layout) -> None:
    facts = describe_permissions(layout["copy"])
    assert facts["exists"] is True
    assert isinstance(facts["st_nlink"], int)
    assert "writable_by_process" in facts


# --- importing a business module must not migrate anything ------------------------


PROBE_SOURCE = """
import os, sys
from pathlib import Path
sys.path.insert(0, os.environ["RAG_APP_ROOT"])
from app.db_target import ReadOnlyDatabase, resolve_database_target
from app.learning import candidate_recovery, question_validator  # noqa: F401
target = resolve_database_target(
    purpose="READ_ONLY_PROBE",
    explicit_path=os.environ["PROBE_DATABASE"],
    allowed_root=os.environ["PROBE_ROOT"],
    production_paths=(os.environ["PROBE_PRODUCTION"],),
    expected_schema=65,
)
probe = ReadOnlyDatabase(target)
print(probe.scalar("SELECT MAX(version) FROM schema_migrations"))
"""


def test_importing_business_modules_in_a_probe_process_does_not_migrate(layout) -> None:
    app_root = Path(__file__).resolve().parents[1]
    script = layout["root"] / "probe.py"
    script.write_text(PROBE_SOURCE, encoding="utf-8")
    before = hashlib.sha256(layout["copy"].read_bytes()).hexdigest()
    environment = dict(os.environ)
    environment.update(
        {
            "RAG_APP_ROOT": str(app_root),
            "PROBE_DATABASE": str(layout["copy"]),
            "PROBE_ROOT": str(layout["root"]),
            "PROBE_PRODUCTION": str(layout["production"]),
            "RAG_DATABASE_PATH": str(layout["copy"]),
            "PYTHONIOENCODING": "utf-8",
        }
    )
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        env=environment,
        cwd=str(app_root),
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "65"
    assert hashlib.sha256(layout["copy"].read_bytes()).hexdigest() == before
