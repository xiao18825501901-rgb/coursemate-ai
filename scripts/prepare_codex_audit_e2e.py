"""Synthetic-only browser seed and test app factory; never opens the real DB."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Playwright itself inherits the desktop environment. Service children must not.
if __name__ == "__main__" and len(sys.argv) > 3 and sys.argv[1] == "--serve":
    import subprocess
    allowed = {
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "COMSPEC",
        "CODEX_AUDIT_RUN_DIR", "APP_ENV", "RAG_PROVIDER_MODE", "V3_ENABLED", "UI_EXTENSION_ENABLED",
        "CMUI_ENV", "CMUI_DATA_DIR", "CMUI_PROVIDER_MODE", "CMUI_COVERAGE_REVIEWER", "CMUI_ALLOW_BILLABLE",
        "CMUI_AUTO_VERIFY_NEW_USERS", "CMUI_ALLOWED_ORIGINS", "WEB_ORIGIN", "UI_TASK_AGENT_URL", "NODE_ENV",
        "AUTH_TEST_USER_ID", "AGENT_DATABASE_PATH", "AGENT_PROVIDER_MODE", "AGENT_PORT", "AGENT_HOST",
    }
    clean_env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    raise SystemExit(subprocess.call(sys.argv[2:], env=clean_env))

ROOT = Path(__file__).resolve().parents[1]
AUDIT_ROOT = (ROOT / "work" / "codex-audit").resolve()
sys.path.insert(0, str(ROOT / "services" / "rag-api"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.auth import TestAuthVerifier
from app.cm_update.db import Database as UiDatabase, now
from app.cm_update.social import set_verified
from app.config import Settings
from app.db import Database
from app.main import create_app
from app.models import CourseCreate
from app.rag.embeddings import DeterministicEmbeddingProvider
from app.services.ingestion import IngestionService
from prepare_v3_e2e import seed_assessment_fixture
from seed_tree_fixture import seed_tree_fixture

VERIFIED = "codex-audit-verified"
UNVERIFIED = "codex-audit-unverified"
WINDOW_ACTOR = "codex-audit-windows"


def settings_at(target: Path) -> Settings:
    target = target.resolve()
    if not target.is_relative_to(AUDIT_ROOT) or target == AUDIT_ROOT:
        raise ValueError("An isolated child of work/codex-audit is required")
    return Settings(
        _env_file=None, database_path=target / "rag.sqlite3", upload_dir=target / "uploads",
        app_env="test", rag_provider_mode="deterministic", auth_test_user_id=VERIFIED,
        v3_enabled=True, ui_extension_enabled=True, admin_user_ids="",
        web_origin="http://127.0.0.1:5373", ui_task_agent_url="http://127.0.0.1:8201",
        ui_web_dir=target / "web-dist",
    )


def prepare(target: Path) -> None:
    settings = settings_at(target)
    if target.exists():
        raise ValueError("Refusing to overwrite an existing audit run")
    target.mkdir(parents=True)
    db = Database(settings)
    db.initialize()
    ingestion = IngestionService(db, settings, DeterministicEmbeddingProvider())
    ingestion.create_course(CourseCreate(id="cs3481", name="CS3481 Synthetic Data Science"), is_admin=True)
    ingestion.create_course(CourseCreate(id="ge2324", name="GE2324 Synthetic Campus Course"), is_admin=True)
    with db.connect() as connection:
        connection.execute("UPDATE courses SET display_type='campus',requires_student_verification=1 WHERE id IN ('cs3481','ge2324')")
    seed_assessment_fixture(db, VERIFIED)
    seed_tree_fixture(db, VERIFIED)
    # Seed official content while the synthetic course is draft; the normal
    # published-content trigger must remain enabled throughout this fixture.
    with db.connect() as connection:
        connection.execute("UPDATE courses SET publication_status='private' WHERE id='cs3481'")
    accepted = ingestion.queue_document(
        course_id="cs3481", filename="Synthetic_Clustering.txt", media_type="text/plain",
        content=("Synthetic local browser fixture. DBSCAN core points have at least MinPts neighbours within eps. "
                 "K-means alternates nearest-centroid assignments and mean updates. "
                 "Question: classify a point with five neighbours when MinPts=4.").encode(),
        is_admin=True,
    )
    ingestion.process_document(accepted.document.id, accepted.job.id)
    with db.connect() as connection:
        connection.execute("UPDATE courses SET publication_status='published' WHERE id='cs3481'")
    ui = UiDatabase(target / "ui-extension" / "ui.sqlite3")
    ui.initialize()
    with ui.connect(True) as connection:
        connection.execute("INSERT INTO cmui_meta(key,value) VALUES('verification_grandfather_boundary',?)",
                           (json.dumps({"complete": True, "users": []}),))
        actors = [(VERIFIED, "Audit Verified", "audit-verified"),
                  (UNVERIFIED, "Audit Unverified", "audit-unverified"),
                  (WINDOW_ACTOR, "Audit Windows", "audit-windows")]
        actors += [(f"audit-directory-{i:02}", f"Directory Student {i:02}", f"directory-{i:02}") for i in range(25)]
        for subject, name, handle in actors:
            connection.execute("INSERT INTO cmui_users(id,name,handle,created_at) VALUES(?,?,?,?)", (subject,name,handle,now()))
        # This actor isolates window interactions without changing directory fixtures.
        connection.execute("UPDATE cmui_users SET discoverable=0 WHERE id=?", (WINDOW_ACTOR,))
    set_verified(ui, VERIFIED, "admin", "Explicit synthetic browser fixture")
    set_verified(ui, WINDOW_ACTOR, "admin", "Explicit synthetic window fixture")
    (target / "fixture.json").write_text(json.dumps({"verified": VERIFIED, "unverified": UNVERIFIED,
        "window_actor": WINDOW_ACTOR,
        "document_id": accepted.document.id, "synthetic_only": True}), encoding="utf-8")
    print(f"Prepared synthetic-only browser run: {target}")


class AuditVerifier:
    def __init__(self):
        self.primary = TestAuthVerifier(VERIFIED)

    def authenticate(self, request):
        if request.headers.get("authorization") == "Bearer audit-windows-token":
            return WINDOW_ACTOR
        if request.headers.get("authorization") == "Bearer audit-unverified-token":
            return UNVERIFIED
        return self.primary.authenticate(request)


def create_test_app():
    if os.environ.get("APP_ENV") != "test" or os.environ.get("CMUI_AUTO_VERIFY_NEW_USERS") != "false":
        raise RuntimeError("Audit factory requires explicit test mode and auto-verification disabled")
    target = Path(os.environ["CODEX_AUDIT_RUN_DIR"]).resolve()
    settings = settings_at(target)
    if not (target / "fixture.json").is_file():
        raise RuntimeError("Synthetic seed receipt missing")
    return create_app(settings=settings, auth_verifier=AuditVerifier())


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: prepare_codex_audit_e2e.py FRESH_AUDIT_RUN_DIRECTORY")
    prepare(Path(sys.argv[1]).resolve())
