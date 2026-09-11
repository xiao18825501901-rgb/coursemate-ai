"""Run additive V3 migrations only on a fresh SQLite online-backup copy."""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/rag-api"))
from app.config import Settings  # noqa: E402
from app.db import Database  # noqa: E402

TABLES = (
    "courses",
    "documents",
    "chunks",
    "ingestion_jobs",
    "conversations",
    "messages",
    "course_teaching_profiles",
    "course_publication_requests",
    "rate_limit_windows",
)


def fingerprints(connection: sqlite3.Connection) -> dict[str, dict[str, object]]:
    result = {}
    for table in TABLES:
        rows = connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
        result[table] = {
            "rows": len(rows),
            "sha256": hashlib.sha256(json.dumps(rows).encode()).hexdigest(),
        }
    return result


def rehearse(source: Path, target: Path) -> dict[str, object]:
    source, target = source.resolve(), target.resolve()
    if not source.is_file() or target.exists() or not target.is_relative_to(ROOT / "work"):
        raise ValueError("Use an existing source and a fresh isolated target directory under work")
    target.mkdir(parents=True)
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original:
        before = fingerprints(original)
        with sqlite3.connect(target / "rag.sqlite3") as copied:
            original.backup(copied)
    database = Database(
        Settings(
            database_path=target / "rag.sqlite3",
            upload_dir=target / "uploads",
            v3_enabled=True,
        )
    )
    database.initialize()
    database.initialize()
    with sqlite3.connect(target / "rag.sqlite3") as copied:
        after = fingerprints(copied)
        integrity = copied.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = copied.execute("PRAGMA foreign_key_check").fetchall()
        versions = [
            row[0]
            for row in copied.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        v3_invariants = {
            "document_versions": copied.execute(
                "SELECT COUNT(*) FROM document_versions"
            ).fetchone()[0],
            "documents": copied.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
            "unbound_chunks": copied.execute(
                "SELECT COUNT(*) FROM chunks LEFT JOIN chunk_source_versions "
                "ON chunk_source_versions.chunk_id=chunks.id "
                "WHERE chunk_source_versions.chunk_id IS NULL"
            ).fetchone()[0],
            "invalid_source_owners": copied.execute(
                "SELECT COUNT(*) FROM document_versions WHERE "
                "(source_scope='OFFICIAL' AND owner_user_id IS NOT NULL) OR "
                "(source_scope!='OFFICIAL' AND owner_user_id IS NULL)"
            ).fetchone()[0],
        }
    invariants_ok = (
        v3_invariants["document_versions"] == v3_invariants["documents"]
        and v3_invariants["unbound_chunks"] == 0
        and v3_invariants["invalid_source_owners"] == 0
        and versions == list(range(1, 14))
    )
    result = {
        "old_rows_unchanged": before == after,
        "integrity": integrity,
        "foreign_key_violations": len(foreign_keys),
        "versions": versions,
        "v3_invariants": v3_invariants,
        "v3_invariants_ok": invariants_ok,
        "before": before,
        "after": after,
    }
    (target / "migration-evidence.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    if before != after or integrity != "ok" or foreign_keys or not invariants_ok:
        raise RuntimeError("Migration rehearsal failed; inspect local content-free evidence")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(rehearse(args.source, args.target)))
