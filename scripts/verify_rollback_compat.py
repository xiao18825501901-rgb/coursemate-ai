"""Verify that a rollback to a previous release is data-safe.

Requirement: "旧客户端与新 Schema 不兼容时必须准备保数据回滚路径". This tool produces
the evidence instead of promising it.

It builds a database with the CURRENT code (all migrations applied), then runs the
PREVIOUS release's own code against that same file and reports whether the old
release can still open, read and write the migrated schema:

* does the old code import and ``Database.initialize()`` without error?
* are any tables or columns the old code expects missing, retyped or made NOT NULL?
* did any CHECK enum *narrow* (which would reject rows the old code still writes)?
* is the assessment pool filter the same in both trees, so old and new code select
  the same pool? This one is a source-text comparison of
  ``app/learning/assessments.py`` in the release tree against the same file in this
  tree (``pool_filter_verdict``); it is not a runtime observation, and an
  unextractable predicate is reported as ``UNDETERMINED``, never as unchanged.

Exit code 0 means the previous release can run against the migrated database, so a
code-only rollback is viable. Exit code 3 means it cannot, and the rollback must
restore the pre-migration database backup. Either way the database backup remains
the primary rollback path; this only tells the operator which one is required.

The pool filter is reported separately from the verdict: anything other than
``UNCHANGED`` is a behavioural difference that needs an owner decision, so it is
listed in ``rollback_concerns`` and deliberately does *not* change the exit code,
because a changed pool filter does not mean the database has to be restored.

Usage:
    python scripts/verify_rollback_compat.py --release-tree <path-to-previous-release>
    # a git export works: git archive --format=zip -o old.zip <sha> && expand it
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import tempfile
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
NEW_SERVICE = ROOT / "services" / "rag-api"

REBUILT_TABLES = (
    "assessment_question_revisions",
    "assessment_blueprint_items",
    "learning_model_run_evidence",
    "learning_model_call_reservations",
)
ENUM = re.compile(r"(\w+)\s+IN\s*\(([^)]*)\)")
# The assessment pool filter the two trees must agree on. It is matched as source
# text, because the release tree's source is the only record of what the release
# actually selected.
POOL_FILTER = re.compile(
    r"validation_status='VALIDATED'[^;]{0,200}?verification_method!='MODEL_ONLY'",
    re.DOTALL,
)
ASSESSMENTS_SOURCE = pathlib.Path("app") / "learning" / "assessments.py"

# Runs inside a subprocess with the OLD release's code on sys.path, so its imports
# can never be shadowed by the current tree. It does two independent things:
#   1. opens the MIGRATED database with the old code (can it still run?),
#   2. builds a fresh database with the old code to capture the OLD schema.
# Comparing (2) against the migrated schema is what makes the column/enum checks
# meaningful; comparing the release's view of the migrated file with itself would
# be circular and would always report "safe".
OLD_PROBE = r'''
import json, pathlib, re, sqlite3, sys, tempfile
service, db_path = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
sys.path.insert(0, str(service))
ENUM = re.compile(r"(\w+)\s+IN\s*\(([^)]*)\)")

def dump(connection):
    tables, enums = {}, {}
    for name, sql in connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table'"):
        if not sql:
            continue
        tables[name] = [(row[1], row[2], row[3])
                        for row in connection.execute(f'PRAGMA table_info("{name}")')]
        enums[name] = {m.group(1): [v.strip().strip("'") for v in m.group(2).split(",")]
                       for m in ENUM.finditer(sql)}
    return tables, enums

out = {"import_error": None, "migrated_open_error": None, "max_migration": None,
       "integrity": None, "foreign_key_violations": None,
       "release_schema_error": None, "release_tables": {}, "release_enums": {}}
try:
    from app.config import Settings
    from app.db import Database
except Exception as exc:
    out["import_error"] = f"{type(exc).__name__}: {exc}"
    print(json.dumps(out)); raise SystemExit(0)

# 1. The old release running against the migrated database.
try:
    database = Database(Settings(
        database_path=db_path, upload_dir=db_path.parent / "uploads",
        app_env="test", v3_enabled=True))
    database.initialize()
    with database.connect() as connection:
        out["max_migration"] = connection.execute(
            "SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        out["integrity"] = connection.execute("PRAGMA integrity_check").fetchone()[0]
        out["foreign_key_violations"] = len(
            connection.execute("PRAGMA foreign_key_check").fetchall())
except Exception as exc:
    out["migrated_open_error"] = f"{type(exc).__name__}: {exc}"

# 2. The old release's own schema, from a database it creates itself.
try:
    fresh = pathlib.Path(tempfile.mkdtemp(prefix="cm-old-schema-")) / "old.sqlite3"
    Database(Settings(
        database_path=fresh, upload_dir=fresh.parent / "uploads",
        app_env="test", v3_enabled=True)).initialize()
    with sqlite3.connect(fresh) as connection:
        out["release_tables"], out["release_enums"] = dump(connection)
    out["release_max_migration"] = sqlite3.connect(fresh).execute(
        "SELECT MAX(version) FROM schema_migrations").fetchone()[0]
except Exception as exc:
    out["release_schema_error"] = f"{type(exc).__name__}: {exc}"

print(json.dumps(out))
'''


def build_current_database(path: pathlib.Path) -> None:
    """Create a fully migrated database using the code in THIS tree."""
    sys.path.insert(0, str(NEW_SERVICE))
    from app.config import Settings
    from app.db import Database

    Database(
        Settings(
            database_path=path,
            upload_dir=path.parent / "uploads",
            app_env="test",
            v3_enabled=True,
        )
    ).initialize()


def run_old_release(service: pathlib.Path, database_path: pathlib.Path) -> dict[str, Any]:
    script = database_path.parent / "old_release_probe.py"
    script.write_text(OLD_PROBE, encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(script), str(service), str(database_path)],
        capture_output=True,
        text=True,
        # The release's own code may print anything, and this machine's locale codec
        # is not UTF-8: without an explicit encoding a single non-locale byte in the
        # release's output kills subprocess's reader thread and the tool reports
        # "printed nothing" instead of the release's real failure mode.
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    lines = [line for line in completed.stdout.strip().splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(
            f"the previous release printed nothing (stderr={completed.stderr[-400:]})"
        )
    parsed: Any = json.loads(lines[-1])
    if not isinstance(parsed, dict):
        # The probe prints one JSON object. Anything else means the release's own code
        # printed a line that happens to parse as JSON (or the probe itself failed), and
        # main() would then die on old.get(...) with an opaque AttributeError instead of
        # naming the cause.
        raise RuntimeError(
            f"the previous release's probe did not print a JSON object: {str(parsed)[:200]}"
        )
    return parsed


def pool_filter_in(root: pathlib.Path) -> str:
    """The assessment pool-filter predicate as written in ``root``'s source, or ""."""
    path = root / ASSESSMENTS_SOURCE
    if not path.is_file():
        return ""
    match = POOL_FILTER.search(path.read_text(encoding="utf-8"))
    return match.group(0) if match else ""


def _normalise_sql(fragment: str) -> str:
    return re.sub(r"\s+", " ", fragment).strip()


def compare_pool_filters(
    release_root: pathlib.Path, current_root: pathlib.Path
) -> tuple[str, str, str, str]:
    """Compare the two trees' pool filters.

    Returns ``(verdict, release_filter, current_filter, detail)`` where verdict is
    one of ``UNCHANGED``, ``CHANGED`` or ``UNDETERMINED``. A predicate that cannot
    be found on either side yields ``UNDETERMINED``: "the two filters agree" is not
    something an unextractable filter can support, and silently reporting the
    current tree's own filter as if it had been compared is a false assurance - the
    operator would read ``pool_filter_unchanged: true`` on a release whose filter
    was never even located.
    """
    release = pool_filter_in(release_root)
    current = pool_filter_in(current_root)
    if not release or not current:
        where = " or ".join(
            name for name, value in (("release", release), ("current", current)) if not value
        )
        location = ASSESSMENTS_SOURCE.as_posix()
        return (
            "UNDETERMINED",
            release,
            current,
            f"pool-filter predicate not found in the {where} source of {location}",
        )
    if release == current:
        return "UNCHANGED", release, current, "byte-identical predicate"
    if _normalise_sql(release) == _normalise_sql(current):
        return "UNCHANGED", release, current, "identical after whitespace normalisation"
    return "CHANGED", release, current, "the two predicates select different pools"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-tree", required=True, type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path, default=None)
    arguments = parser.parse_args()

    tree = arguments.release_tree.resolve()
    service = tree / "services" / "rag-api" if (tree / "services").is_dir() else tree
    if not (service / "app" / "db.py").is_file():
        print(f"not a release tree (no app/db.py): {service}")
        return 2

    work = pathlib.Path(tempfile.mkdtemp(prefix="cm-rollback-"))
    database_path = work / "migrated.sqlite3"
    build_current_database(database_path)
    old = run_old_release(service, database_path)

    report: dict[str, Any] = {
        "release_tree": str(tree),
        "migrated_database": str(database_path),
        "release_import_error": old.get("import_error"),
        "release_open_migrated_error": old.get("migrated_open_error"),
        "release_schema_dump_error": old.get("release_schema_error"),
        "release_sees_max_migration": old.get("max_migration"),
        "release_own_schema_migration": old.get("release_max_migration"),
        "release_integrity_check": old.get("integrity"),
        "release_foreign_key_violations": old.get("foreign_key_violations"),
        "tables_missing_for_release": [],
        "columns_missing_for_release": [],
        "columns_retyped_for_release": [],
        "check_enums_narrowed": [],
        "pool_filter_verdict": None,
        "pool_filter_unchanged": None,
        "pool_filter_release": None,
        "pool_filter_current": None,
        "pool_filter_detail": None,
        "rollback_concerns": [],
        "reasons": [],
    }

    import sqlite3

    with sqlite3.connect(database_path) as connection:
        live_sql = {
            name: sql
            for name, sql in connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table'"
            )
            if sql
        }
        live_columns = {
            name: [
                (row[1], row[2], row[3])
                for row in connection.execute(f'PRAGMA table_info("{name}")')
            ]
            for name in live_sql
        }

    # The release's OWN schema (captured from a database the release built) vs the
    # migrated schema. This is the non-circular comparison.
    release_tables: dict[str, list[tuple[str, str, int]]] = old.get("release_tables") or {}
    if not release_tables and not old.get("release_schema_error"):
        report["reasons"].append("could not capture the previous release's own schema")

    for table, release_columns in release_tables.items():
        if table not in live_columns:
            report["tables_missing_for_release"].append(table)
            continue
        live = {name: (type_, notnull) for name, type_, notnull in live_columns[table]}
        for name, type_, notnull in release_columns:
            if name not in live:
                report["columns_missing_for_release"].append(f"{table}.{name}")
            elif live[name] != (type_, notnull):
                report["columns_retyped_for_release"].append(
                    f"{table}.{name}: {(type_, notnull)} -> {live[name]}"
                )

    for table, enums in (old.get("release_enums") or {}).items():
        sql = live_sql.get(table)
        if sql is None:
            continue
        live_enums = {
            match.group(1): [v.strip().strip("'") for v in match.group(2).split(",")]
            for match in ENUM.finditer(sql)
        }
        for column, before in enums.items():
            after = live_enums.get(column)
            if after is None:
                report["check_enums_narrowed"].append(f"{table}.{column}: constraint removed")
                continue
            missing = sorted(set(before) - set(after))
            if missing:
                report["check_enums_narrowed"].append(
                    f"{table}.{column}: {missing} no longer accepted"
                )

    if old.get("import_error"):
        report["reasons"].append(f"release import failed: {old['import_error']}")
    if old.get("migrated_open_error"):
        report["reasons"].append(
            f"previous release cannot open the migrated database: {old['migrated_open_error']}"
        )
    if old.get("release_schema_error"):
        report["reasons"].append(f"release schema dump failed: {old['release_schema_error']}")
    for key in (
        "tables_missing_for_release",
        "columns_missing_for_release",
        "columns_retyped_for_release",
        "check_enums_narrowed",
    ):
        if report[key]:
            report["reasons"].append(f"{key}: {report[key]}")

    # The pool filter is compared between the two trees rather than read from this
    # one. It deliberately does NOT feed `reasons`: a different pool filter means the
    # rollback changes behaviour, not that the migrated database is unusable, and
    # `reasons` drives the "restore the backup" verdict.
    (
        pool_verdict,
        pool_release,
        pool_current,
        pool_detail,
    ) = compare_pool_filters(service, NEW_SERVICE)
    report["pool_filter_verdict"] = pool_verdict
    report["pool_filter_unchanged"] = pool_verdict == "UNCHANGED"
    report["pool_filter_release"] = pool_release
    report["pool_filter_current"] = pool_current
    report["pool_filter_detail"] = pool_detail
    if pool_verdict != "UNCHANGED":
        report["rollback_concerns"].append(
            f"assessment pool filter {pool_verdict}: {pool_detail}"
        )

    # Rebuilt tables are the risky ones: name them explicitly in the verdict.
    report["rebuilt_tables_checked"] = list(REBUILT_TABLES)
    report["verdict"] = (
        "ROLLBACK_SAFE_WITH_MIGRATED_DB" if not report["reasons"]
        else "ROLLBACK_REQUIRES_DB_RESTORE"
    )
    report["note"] = (
        "A code-only rollback is viable when the verdict is "
        "ROLLBACK_SAFE_WITH_MIGRATED_DB; the pre-migration database backup remains "
        "the primary rollback path either way. The verdict covers schema and code "
        "compatibility with the migrated database only: pool_filter_verdict != "
        "UNCHANGED means the two releases select different assessment pools (or the "
        "predicate could not be located, reported as UNDETERMINED), which is listed "
        "in rollback_concerns and needs an owner decision."
    )

    payload = json.dumps(report, indent=2, ensure_ascii=False)
    if arguments.out:
        arguments.out.parent.mkdir(parents=True, exist_ok=True)
        arguments.out.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if report["verdict"] == "ROLLBACK_SAFE_WITH_MIGRATED_DB" else 3


if __name__ == "__main__":
    raise SystemExit(main())
