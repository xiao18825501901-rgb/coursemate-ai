"""Inventory and explicitly reconcile orphaned practice operations.

Inventory is read-only and opens SQLite with ``mode=ro``.  Reconciliation is
append-only, requires a writer-drain assertion plus ``--apply``, stores only the
SHA-256 of the evidence file, and never calls a model or reuses an operation id.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVICE = ROOT / "services" / "rag-api"
sys.path.insert(0, str(SERVICE))

from app.learning.practice_recovery import (
    PRACTICE_OPERATION_ACTIVE_WINDOW_SECONDS,
    PracticeRecoveryError,
    inspect_practice_operations,
    reconcile_practice_operation,
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)

    inventory = commands.add_parser("inventory", help="read-only evidence inventory")
    inventory.add_argument("--database", type=pathlib.Path, required=True)
    inventory.add_argument("--workspace-id")
    inventory.add_argument("--operation-id")
    inventory.add_argument(
        "--active-window-seconds",
        type=int,
        default=PRACTICE_OPERATION_ACTIVE_WINDOW_SECONDS,
    )

    reconcile = commands.add_parser("reconcile", help="append an explicit disposition")
    reconcile.add_argument("--database", type=pathlib.Path, required=True)
    reconcile.add_argument("--workspace-id", required=True)
    reconcile.add_argument("--operation-id", required=True)
    reconcile.add_argument(
        "--expected-classification",
        required=True,
        choices=(
            "NOT_SENT",
            "UPSTREAM_FAILED",
            "UPSTREAM_UNKNOWN",
            "LEGACY_UPSTREAM_UNKNOWN",
            "UPSTREAM_COMPLETED_NO_RESULT",
        ),
    )
    reconcile.add_argument(
        "--disposition",
        required=True,
        choices=(
            "NOT_SENT",
            "UPSTREAM_FAILED",
            "UPSTREAM_UNKNOWN",
            "UPSTREAM_COMPLETED_NO_RESULT",
        ),
    )
    reconcile.add_argument("--operator-ref", required=True)
    reconcile.add_argument("--evidence-file", type=pathlib.Path, required=True)
    reconcile.add_argument(
        "--active-window-seconds",
        type=int,
        default=PRACTICE_OPERATION_ACTIVE_WINDOW_SECONDS,
    )
    reconcile.add_argument(
        "--writers-drained",
        action="store_true",
        help="assert that all writers for this database have been stopped",
    )
    reconcile.add_argument(
        "--apply",
        action="store_true",
        help="perform the append-only reconciliation write",
    )
    return result


def _read_only_connection(database: pathlib.Path) -> sqlite3.Connection:
    resolved = database.resolve(strict=True)
    connection = sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _write_connection(database: pathlib.Path) -> sqlite3.Connection:
    resolved = database.resolve(strict=True)
    connection = sqlite3.connect(resolved)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "inventory":
            with _read_only_connection(args.database) as connection:
                rows = inspect_practice_operations(
                    connection,
                    workspace_id=args.workspace_id,
                    operation_id=args.operation_id,
                    active_window_seconds=args.active_window_seconds,
                )
            print(json.dumps([row.to_dict() for row in rows], indent=2, sort_keys=True))
            return 0

        if not args.apply:
            raise PracticeRecoveryError("reconciliation requires the explicit --apply flag")
        if not args.evidence_file.is_file():
            raise PracticeRecoveryError("evidence file does not exist or is not a regular file")
        evidence = args.evidence_file.read_bytes()
        with _write_connection(args.database) as connection:
            row = reconcile_practice_operation(
                connection,
                workspace_id=args.workspace_id,
                operation_id=args.operation_id,
                expected_classification=args.expected_classification,
                disposition=args.disposition,
                operator_ref=args.operator_ref,
                evidence=evidence,
                writers_drained=args.writers_drained,
                active_window_seconds=args.active_window_seconds,
            )
        print(json.dumps(row.to_dict(), indent=2, sort_keys=True))
        return 0
    except (OSError, sqlite3.Error, PracticeRecoveryError) as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
