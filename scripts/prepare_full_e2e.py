"""Create a writable E2E database copy without mutating the local source database."""

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = (ROOT / "work").resolve()
SOURCE_DATABASE = (ROOT / "data" / "rag.sqlite3").resolve()
sys.path.insert(0, str(ROOT / "services" / "rag-api"))

from prepare_v3_e2e import seed_assessment_fixture  # noqa: E402

from app.config import Settings  # noqa: E402 - repository-local service bootstrap
from app.db import Database  # noqa: E402 - repository-local service bootstrap


def prepare(target: Path, owner: str) -> Path:
    target = target.resolve()
    if not SOURCE_DATABASE.is_file():
        raise FileNotFoundError("The local RAG source database is unavailable")
    if target.exists() or not target.is_relative_to(WORK_ROOT):
        raise ValueError("A fresh isolated target directory under work is required")
    if not owner.strip() or len(owner) > 200:
        raise ValueError("A bounded synthetic test owner is required")

    target.mkdir(parents=True)
    copied_database = target / "rag.sqlite3"
    with sqlite3.connect(
        SOURCE_DATABASE.as_uri() + "?mode=ro", uri=True
    ) as source_connection, sqlite3.connect(copied_database) as target_connection:
        source_connection.backup(target_connection)

    database = Database(
        Settings(
            database_path=copied_database,
            upload_dir=target / "uploads",
            v3_enabled=True,
        )
    )
    database.initialize()
    seed_assessment_fixture(database, owner)
    return copied_database


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: prepare_full_e2e.py TARGET_DIRECTORY SYNTHETIC_OWNER")
    print(prepare(Path(sys.argv[1]), sys.argv[2]))
