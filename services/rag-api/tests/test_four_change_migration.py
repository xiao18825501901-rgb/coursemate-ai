"""Migration rehearsal for the additive four-change schema updates."""
from pathlib import Path

from app.cm_update.db import Database, SCHEMA_VERSION


def test_existing_layout_and_verification_rows_survive_additive_upgrade(tmp_path: Path) -> None:
    db = Database(tmp_path / "four-change-upgrade.sqlite3")
    db.initialize()
    db.execute("INSERT INTO cmui_users(id,name,handle,created_at) VALUES('owner','Owner','owner','2026-01-01T00:00:00Z')")
    with db.connect(True) as c:
        # This is the pre-v12 provenance check and the pre-v13 layout shape.
        c.execute("DROP TABLE cmui_verification")
        c.execute("CREATE TABLE cmui_verification (owner TEXT PRIMARY KEY, verified INTEGER NOT NULL DEFAULT 0, method TEXT CHECK(method IN ('grandfathered','code','admin')), verified_at TEXT, boundary_notes TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL)")
        c.execute("INSERT INTO cmui_verification VALUES('owner',1,'code','2026-01-01T00:00:00Z','original audit','2026-01-01T00:00:00Z')")
        c.execute("DROP TABLE cmui_layout")
        c.execute("CREATE TABLE cmui_layout (owner TEXT NOT NULL, course TEXT NOT NULL, ratio REAL NOT NULL DEFAULT 0.5, teach_conversation TEXT, problem_conversation TEXT, active_node TEXT, PRIMARY KEY(owner,course))")
        c.execute("INSERT INTO cmui_layout VALUES('owner','course-1',0.62,'teach-old','problem-old','node-old')")
        c.execute("UPDATE cmui_meta SET value='11' WHERE key='schema_version'")

    db.initialize()
    verification = db.one("SELECT verified,method,boundary_notes FROM cmui_verification WHERE owner='owner'")
    layout = db.one("SELECT ratio,teach_conversation,problem_conversation,active_node,teach_strength,problem_strength FROM cmui_layout WHERE owner='owner' AND course='course-1'")
    assert verification == {"verified": 1, "method": "code", "boundary_notes": "original audit"}
    assert layout == {"ratio": 0.62, "teach_conversation": "teach-old", "problem_conversation": "problem-old", "active_node": "node-old", "teach_strength": "medium", "problem_strength": "medium"}
    assert db.one("SELECT value FROM cmui_meta WHERE key='schema_version'")["value"] == str(SCHEMA_VERSION)
    assert db.one("SELECT name FROM sqlite_master WHERE type='table' AND name='cmui_preferences'") is not None

