"""Create synthetic-only E2E state. Never open the actual course database."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/rag-api"))

from app.config import Settings  # noqa: E402
from app.db import Database  # noqa: E402


def main() -> None:
    target = Path(sys.argv[1]).resolve()
    if not target.is_relative_to(ROOT / "work") or target.exists():
        raise ValueError("A fresh directory under work is required")
    db = Database(
        Settings(
            database_path=target / "rag.db",
            upload_dir=target / "uploads",
            v3_enabled=True,
        )
    )
    db.initialize()
    with db.connect() as connection:
        connection.execute(
            "INSERT INTO courses(id,name,publication_status) "
            "VALUES('cs3481','Synthetic CS3481 fixture','published')"
        )


if __name__ == "__main__":
    main()
