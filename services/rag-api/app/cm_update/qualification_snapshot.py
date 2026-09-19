"""Freeze, preview, and explicitly apply a Clerk qualification snapshot.

Capture never opens the CourseMate database. Preview opens an existing database
read-only. Apply accepts only the already-frozen records whose snapshot and
candidate-set hashes were approved by the operator; it never refetches Clerk.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from .db import Database
from .directory import ClerkDirectoryClient, apply_grandfather_snapshot, grandfather_candidates

SNAPSHOT_VERSION = 1
_RECORD_KEYS = {"id", "created_at", "updated_at", "banned", "deleted", "locked"}


def _valid_timestamp(value: object, *, optional: bool) -> int | float | None:
    if optional and value is None:
        return None
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError("Snapshot timestamps must be finite nonnegative numbers")
    return value


def _minimal_record(row: object) -> dict[str, object]:
    if not isinstance(row, dict):
        raise ValueError("Invalid identity record")
    subject = row.get("id")
    if not isinstance(subject, str) or not subject:
        raise ValueError("Invalid identity record")
    created = _valid_timestamp(row.get("created_at"), optional=True)
    updated = _valid_timestamp(row.get("updated_at"), optional=False)
    account_state: dict[str, bool] = {}
    for field in ("banned", "deleted", "locked"):
        value = row.get(field, False)
        if not isinstance(value, bool):
            raise ValueError("Snapshot account-state fields must be boolean")
        account_state[field] = value
    return {
        "id": subject,
        "created_at": created,
        "updated_at": updated,
        **account_state,
    }


def build_snapshot(records: list[dict[str, Any]], *, captured_at_ms: int) -> dict[str, object]:
    """Build a canonical, data-minimized complete snapshot envelope."""
    captured = _valid_timestamp(captured_at_ms, optional=False)
    if not isinstance(captured, int):
        raise ValueError("Snapshot capture timestamp must be an integer")
    minimal = [_minimal_record(row) for row in records]
    minimal.sort(key=lambda row: str(row["id"]))
    subjects = [row["id"] for row in minimal]
    if len(subjects) != len(set(subjects)):
        raise ValueError("Snapshot contains duplicate identity records")
    return {
        "version": SNAPSHOT_VERSION,
        "complete": True,
        "captured_at_ms": captured,
        "records": minimal,
    }


def _validated_snapshot(snapshot: object) -> dict[str, object]:
    if not isinstance(snapshot, dict) or set(snapshot) != {
        "version", "complete", "captured_at_ms", "records"
    }:
        raise ValueError("Invalid qualification snapshot envelope")
    if snapshot["version"] != SNAPSHOT_VERSION or snapshot["complete"] is not True:
        raise ValueError("Unsupported or incomplete qualification snapshot")
    captured = _valid_timestamp(snapshot["captured_at_ms"], optional=False)
    if not isinstance(captured, int):
        raise ValueError("Snapshot capture timestamp must be an integer")
    raw_records = snapshot["records"]
    if not isinstance(raw_records, list):
        raise ValueError("Invalid qualification snapshot records")
    records: list[dict[str, object]] = []
    for raw in raw_records:
        if not isinstance(raw, dict) or set(raw) != _RECORD_KEYS:
            raise ValueError("Qualification snapshot records must be data-minimized")
        record = _minimal_record(raw)
        if record != raw:
            raise ValueError("Qualification snapshot record is not canonical")
        records.append(record)
    subjects = [str(row["id"]) for row in records]
    if subjects != sorted(subjects) or len(subjects) != len(set(subjects)):
        raise ValueError("Qualification snapshot records must be sorted and unique")
    return {
        "version": SNAPSHOT_VERSION,
        "complete": True,
        "captured_at_ms": captured,
        "records": records,
    }


def _canonical_bytes(snapshot: object) -> bytes:
    validated = _validated_snapshot(snapshot)
    return json.dumps(validated, sort_keys=True, separators=(",", ":")).encode("utf-8")


def snapshot_sha256(snapshot: object) -> str:
    return hashlib.sha256(_canonical_bytes(snapshot)).hexdigest()


def write_snapshot(path: Path, snapshot: object) -> None:
    """Exclusively create a private file; a partial crash artifact is never overwritten."""
    data = _canonical_bytes(snapshot) + b"\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(path, 0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def read_snapshot(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as stream:
        return _validated_snapshot(json.load(stream))


def _candidate_set_sha256(candidates: object) -> str:
    if not isinstance(candidates, list) or not all(isinstance(item, str) for item in candidates):
        raise ValueError("Invalid qualification candidate set")
    data = json.dumps(sorted(candidates), separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _iso_to_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def _database_status(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(f"Existing UI database is required: {path}")
    uri = path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "cmui_meta" not in tables:
            raise ValueError("Target is not a CourseMate UI database")
        values = {
            row["key"]: row["value"]
            for row in connection.execute(
                "SELECT key,value FROM cmui_meta WHERE key IN "
                "('schema_version','verification_grandfather_cutoff',"
                "'verification_grandfather_registered_snapshot')"
            )
        }
    finally:
        connection.close()
    fixed = values.get("verification_grandfather_cutoff")
    receipt_raw = values.get("verification_grandfather_registered_snapshot")
    receipt = json.loads(receipt_raw) if receipt_raw else None
    receipt_evidence = receipt.get("evidence") if isinstance(receipt, dict) else None
    return {
        "schema_version": values.get("schema_version"),
        "fixed_cutoff_ms": _iso_to_ms(fixed) if fixed else None,
        "receipt_status": receipt.get("status") if isinstance(receipt, dict) else None,
        "receipt_cutoff_ms": receipt.get("cutoff_ms") if isinstance(receipt, dict) else None,
        "receipt_evidence_sha256": (
            receipt_evidence.get("snapshot_sha256")
            if isinstance(receipt_evidence, dict)
            else None
        ),
    }


def preview_snapshot(
    snapshot: object, *, cutoff_ms: int, database: Path | None = None
) -> dict[str, object]:
    """Return approval-safe aggregate evidence without mutating local state."""
    validated = _validated_snapshot(snapshot)
    records = validated["records"]
    if not isinstance(records, list):  # narrowed by validation; keeps the boundary explicit
        raise ValueError("Invalid qualification snapshot records")
    selection = grandfather_candidates(records, cutoff_ms=cutoff_ms, complete=True)
    evidence = selection["evidence"]
    return {
        "version": SNAPSHOT_VERSION,
        "complete": True,
        "captured_at_ms": validated["captured_at_ms"],
        "registered_count": evidence["registered_count"],
        "candidate_count": evidence["candidate_count"],
        "unknown_created_at": evidence["unknown_created_at"],
        "snapshot_sha256": snapshot_sha256(validated),
        "candidate_set_sha256": _candidate_set_sha256(selection["candidates"]),
        "eligibility_evidence_sha256": evidence["snapshot_sha256"],
        "database": _database_status(database) if database is not None else None,
    }


async def capture_snapshot(
    output: Path,
    secret: str,
    *,
    http_client: Any | None = None,
    captured_at_ms: int | None = None,
) -> dict[str, object]:
    """Fetch all Clerk pages and freeze only qualification-relevant fields."""
    if not secret:
        raise ValueError("CLERK_SECRET_KEY is required")
    capture_ms = captured_at_ms
    if capture_ms is None:
        capture_ms = int(datetime.now(UTC).timestamp() * 1000)
    if http_client is None:
        import httpx

        async with httpx.AsyncClient(
            base_url="https://api.clerk.com/v1/",
            headers={"Authorization": f"Bearer {secret}"},
            timeout=30,
            follow_redirects=False,
        ) as http:
            records = await ClerkDirectoryClient(http).fetch_users()
    else:
        records = await ClerkDirectoryClient(http_client).fetch_users()
    snapshot = build_snapshot(records, captured_at_ms=capture_ms)
    write_snapshot(output, snapshot)
    return {
        "version": SNAPSHOT_VERSION,
        "complete": True,
        "captured_at_ms": capture_ms,
        "registered_count": len(records),
        "snapshot_sha256": snapshot_sha256(snapshot),
    }


def apply_snapshot(
    database: Path,
    snapshot: object,
    *,
    cutoff_ms: int,
    expected_snapshot_sha256: str,
    expected_candidate_set_sha256: str,
) -> dict[str, Any]:
    """Apply the exact approved snapshot, with no network access or refetch."""
    preview = preview_snapshot(snapshot, cutoff_ms=cutoff_ms, database=database)
    if preview["snapshot_sha256"] != expected_snapshot_sha256:
        raise ValueError("Frozen snapshot hash does not match the approved snapshot hash")
    if preview["candidate_set_sha256"] != expected_candidate_set_sha256:
        raise ValueError("Frozen candidate-set hash does not match the approved candidate-set hash")
    database_status = preview["database"]
    if not isinstance(database_status, dict):
        raise ValueError("Existing CourseMate UI database status is required")
    if database_status["receipt_status"] == "COMPLETED" and (
        database_status["receipt_cutoff_ms"] != cutoff_ms
        or database_status["receipt_evidence_sha256"]
        != preview["eligibility_evidence_sha256"]
    ):
        raise ValueError("Existing completed receipt belongs to a different frozen snapshot")
    validated = _validated_snapshot(snapshot)
    records = validated["records"]
    if not isinstance(records, list):
        raise ValueError("Invalid qualification snapshot records")
    receipt = cast(
        dict[str, Any],
        apply_grandfather_snapshot(
            Database(database), records, cutoff_ms=cutoff_ms, complete=True
        ),
    )
    receipt_evidence = receipt.get("evidence")
    if (
        receipt.get("status") != "COMPLETED"
        or not isinstance(receipt_evidence, dict)
        or receipt_evidence.get("snapshot_sha256") != preview["eligibility_evidence_sha256"]
    ):
        raise ValueError("Completed receipt does not match the approved frozen snapshot")
    return {
        "status": "COMPLETED",
        "cutoff_ms": cutoff_ms,
        "completed_at": receipt.get("completed_at"),
        "registered_count": preview["registered_count"],
        "candidate_count": preview["candidate_count"],
        "unknown_created_at": preview["unknown_created_at"],
        "snapshot_sha256": preview["snapshot_sha256"],
        "candidate_set_sha256": preview["candidate_set_sha256"],
        "eligibility_evidence_sha256": preview["eligibility_evidence_sha256"],
    }


def _positive_cutoff(value: str) -> int:
    cutoff = int(value)
    if cutoff < 0:
        raise argparse.ArgumentTypeError("cutoff must be nonnegative")
    return cutoff


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Freeze, preview, or apply an exact Clerk qualification snapshot"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("capture", help="Read Clerk and create a private snapshot")
    capture.add_argument("--output", type=Path, required=True)
    preview = commands.add_parser("preview", help="Print aggregate evidence only")
    preview.add_argument("--snapshot", type=Path, required=True)
    preview.add_argument("--cutoff-ms", type=_positive_cutoff, required=True)
    preview.add_argument("--database", type=Path)
    apply = commands.add_parser("apply", help="Apply an already approved frozen snapshot")
    apply.add_argument("--snapshot", type=Path, required=True)
    apply.add_argument("--database", type=Path, required=True)
    apply.add_argument("--cutoff-ms", type=_positive_cutoff, required=True)
    apply.add_argument("--expected-snapshot-sha256", required=True)
    apply.add_argument("--expected-candidate-set-sha256", required=True)
    apply.add_argument("--approved-apply", action="store_true", required=True)
    return parser


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    if args.command == "capture":
        secret = os.getenv("CLERK_SECRET_KEY", "")
        if not secret:
            parser.error("capture requires CLERK_SECRET_KEY in the protected environment")
        result = asyncio.run(capture_snapshot(args.output, secret))
    else:
        snapshot = read_snapshot(args.snapshot)
        if args.command == "preview":
            result = preview_snapshot(snapshot, cutoff_ms=args.cutoff_ms, database=args.database)
        else:
            result = apply_snapshot(
                args.database,
                snapshot,
                cutoff_ms=args.cutoff_ms,
                expected_snapshot_sha256=args.expected_snapshot_sha256,
                expected_candidate_set_sha256=args.expected_candidate_set_sha256,
            )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
