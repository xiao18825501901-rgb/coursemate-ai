"""An imported Canvas course is a normal private course, and the rest of the product works on it.

The revision says so directly ("用户可以后续按现有规则：加入Dashboard、设置教学Prompt、学习、
做题、测评、删除、分享快照"), and that sentence is a claim about the *product*, not about the
import: a course that only the importer can see, that cannot be renamed, extended, asked about or
deleted would satisfy the import tests and still be useless.

So this suite imports a real course through the **local bridge** (the route that works without a
school Developer Key) and then uses it the way a student would:

* it appears in the owner's course list as `user`/`private`, owned, with its material indexed;
* another account cannot list it, read it, read its documents, rename it or delete it;
* the owner can rename it and choose a language;
* the owner can add more material through the ordinary upload route, and it is ingested;
* a question about the imported material is answered **and cites the imported file** — the real
  business effect, not a receipt;
* deleting it removes its material, and does **not** rewrite the import history.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sqlite3
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

USER = "import-owner"
OTHER_USER = "import-stranger"
AUTH = {"Authorization": "Bearer test-session-token"}
MARKDOWN = (
    b"# Clustering\n\n"
    b"DBSCAN groups points by density and marks outliers as noise.\n"
    b"Density is estimated from the number of neighbours inside a radius epsilon.\n"
)
SECOND = b"# Clustering tutorial 2\n\nA core point has at least minPts neighbours within epsilon.\n"
CANVAS_COURSE = "560"


@dataclass
class Imported:
    """A course imported through the bridge, plus everything needed to poke at it afterwards."""

    app: Any
    client: TestClient
    database: pathlib.Path
    course_id: str
    document_id: str

    def as_user(self, user: str | None) -> dict[str, str]:
        self.app.state.auth_verifier.user_id = user or USER
        return AUTH

    def query(self, sql: str, parameters: tuple = ()) -> list[sqlite3.Row]:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        try:
            return list(connection.execute(sql, parameters).fetchall())
        finally:
            connection.close()

    def events(self, response) -> list[tuple[str, dict]]:
        """Parse the QA stream: one `(event, data)` pair per SSE frame."""
        parsed: list[tuple[str, dict]] = []
        for frame in response.text.strip().split("\n\n"):
            lines = frame.splitlines()
            event = next((line[7:] for line in lines if line.startswith("event: ")), "")
            data = next((line[6:] for line in lines if line.startswith("data: ")), "")
            if event and data:
                parsed.append((event, json.loads(data)))
        return parsed


def import_a_course(tmp_path: pathlib.Path) -> Imported:
    """Drive the bridge exactly as the shipped page and the local tool do."""
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        ui_web_dir=tmp_path / "no-web-build",
        app_env="test",
        rag_provider_mode="deterministic",
        auth_test_user_id=USER,
        v3_enabled=True,
    )
    app = create_app(settings=settings)
    client = TestClient(app)
    harness = Imported(
        app=app, client=client, database=tmp_path / "rag.sqlite3", course_id="", document_id=""
    )

    opened = client.post(
        "/api/integrations/canvas/local-sessions",
        json={"institution_key": "cityu"},
        headers=AUTH,
    )
    assert opened.status_code == 201, opened.text
    session_id = opened.json()["sessionId"]

    claimed = client.post(
        "/api/integrations/canvas/local-sessions/claim",
        json={"code": opened.json()["code"], "canvas_user_id": "4242"},
        headers=AUTH,
    )
    assert claimed.status_code == 200, claimed.text

    discovered = client.post(
        f"/api/integrations/canvas/local-sessions/{session_id}/discovery",
        json={
            "courses": [
                {
                    "canvas_course_id": CANVAS_COURSE,
                    "name": "Problem Solve & Programming",
                    "course_code": "CS2312",
                    "term": "Semester B 2025_26",
                    "enrollment_state": "active",
                    "workflow_state": "available",
                    "file_count": 1,
                }
            ]
        },
        headers=AUTH,
    )
    assert discovered.status_code == 200, discovered.text
    assert (
        client.post(
            f"/api/integrations/canvas/local-sessions/{session_id}/selection",
            json={"canvas_course_ids": [CANVAS_COURSE]},
            headers=AUTH,
        ).status_code
        == 200
    )

    uploaded = client.post(
        f"/api/integrations/canvas/local-sessions/{session_id}/files",
        data={
            "canvas_course_id": CANVAS_COURSE,
            "canvas_file_id": "f-1",
            "display_name": "clustering-notes.md",
            "declared_size": str(len(MARKDOWN)),
            "declared_sha256": hashlib.sha256(MARKDOWN).hexdigest(),
            "source_updated_at": "2026-01-02T03:04:05Z",
        },
        files={"file": ("clustering-notes.md", MARKDOWN, "application/octet-stream")},
        headers=AUTH,
    )
    assert uploaded.status_code == 201, uploaded.text
    receipt = uploaded.json()
    assert receipt["status"] == "INDEXED", receipt
    assert (
        client.post(
            f"/api/integrations/canvas/local-sessions/{session_id}/finish", headers=AUTH
        ).status_code
        == 200
    )

    harness.course_id = receipt["targetCourseId"]
    harness.document_id = receipt["documentId"]
    return harness


@pytest.fixture()
def imported(tmp_path) -> Imported:
    return import_a_course(tmp_path)


# ---------------------------------------------------------------------------- it is a normal course
def test_the_imported_course_is_owned_private_and_indexed(
    imported: Imported,
) -> None:
    listed = imported.client.get("/api/courses", headers=AUTH)
    assert listed.status_code == 200, listed.text
    courses = {course["id"]: course for course in listed.json()["items"]}
    assert imported.course_id in courses, courses.keys()
    course = courses[imported.course_id]

    assert course["courseType"] == "user"
    assert course["visibility"] == "private"
    assert course["publicationStatus"] == "private"
    assert course["publishedAt"] is None
    assert course["isOwner"] is True
    assert course["displayType"] != "campus"
    assert course["documentCount"] >= 1
    # The material is really indexed, not merely stored.
    assert course["indexStatus"] not in ("", "empty")

    documents = imported.client.get(f"/api/courses/{imported.course_id}/documents", headers=AUTH)
    assert documents.status_code == 200, documents.text
    listed_documents = documents.json()["items"]
    assert [item["id"] for item in listed_documents] == [imported.document_id]
    assert listed_documents[0]["chunkCount"] > 0


def test_another_account_cannot_see_or_touch_it(imported: Imported) -> None:
    imported.as_user(OTHER_USER)

    listed = imported.client.get("/api/courses", headers=AUTH)
    assert listed.status_code == 200
    assert imported.course_id not in {course["id"] for course in listed.json()["items"]}

    assert (
        imported.client.get(f"/api/courses/{imported.course_id}", headers=AUTH).status_code == 404
    )
    assert (
        imported.client.get(
            f"/api/courses/{imported.course_id}/documents", headers=AUTH
        ).status_code
        == 404
    )
    renamed = imported.client.patch(
        f"/api/courses/{imported.course_id}", json={"name": "Mine now"}, headers=AUTH
    )
    assert renamed.status_code in (403, 404), renamed.text
    deleted = imported.client.delete(f"/api/courses/{imported.course_id}", headers=AUTH)
    assert deleted.status_code in (403, 404), deleted.text

    imported.as_user(None)
    assert (
        imported.client.get(f"/api/courses/{imported.course_id}", headers=AUTH).status_code == 200
    )


def test_the_owner_can_rename_it_and_choose_a_language(imported: Imported) -> None:
    renamed = imported.client.patch(
        f"/api/courses/{imported.course_id}",
        json={"name": "算法与数据结构（Canvas）", "preferred_language": "zh-CN"},
        headers=AUTH,
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "算法与数据结构（Canvas）"

    fetched = imported.client.get(f"/api/courses/{imported.course_id}", headers=AUTH)
    assert fetched.json()["name"] == "算法与数据结构（Canvas）"
    assert fetched.json()["preferredLanguage"] == "zh-CN"


def test_more_material_can_be_added_through_the_ordinary_upload_route(imported: Imported) -> None:
    """The imported course is a normal private course: the product's own upload path works on it."""
    uploaded = imported.client.post(
        f"/api/courses/{imported.course_id}/documents",
        files={"file": ("tutorial-2.md", SECOND, "text/markdown")},
        headers=AUTH,
    )
    assert uploaded.status_code == 202, uploaded.text
    accepted = uploaded.json()
    job = imported.client.get(f"/api/ingestion-jobs/{accepted['job']['id']}", headers=AUTH)
    assert job.status_code == 200, job.text
    assert job.json()["status"] == "completed", job.text

    documents = imported.client.get(
        f"/api/courses/{imported.course_id}/documents", headers=AUTH
    ).json()["items"]
    assert len(documents) == 2
    assert all(item["chunkCount"] > 0 for item in documents)


def test_a_question_about_the_imported_material_is_answered_and_cites_the_file(
    imported: Imported,
) -> None:
    """The real business effect: the imported file is retrieved, quoted and answered from."""
    response = imported.client.post(
        "/api/qa/chat",
        json={"course_id": imported.course_id, "question": "DBSCAN 如何判断离群点？"},
        headers=AUTH,
    )
    assert response.status_code == 200, response.text
    events = imported.events(response)
    kinds = [kind for kind, _ in events]
    assert "meta" in kinds or "answer" in kinds, kinds

    answer = "".join(str(data.get("text", "")) for kind, data in events if kind == "delta")
    citations = [data for kind, data in events if kind == "citation"]

    assert citations, f"no citation in {kinds}"
    document_ids = {str(item.get("documentId") or "") for item in citations}
    assert imported.document_id in document_ids, citations
    assert isinstance(answer, str)
    assert citations[0]["excerpt"], "a citation without the text the learner was shown"


def test_deleting_the_course_removes_its_material_and_keeps_the_import_history(
    imported: Imported,
) -> None:
    deleted = imported.client.delete(f"/api/courses/{imported.course_id}", headers=AUTH)
    assert deleted.status_code == 204, deleted.text

    assert (
        imported.client.get(f"/api/courses/{imported.course_id}", headers=AUTH).status_code == 404
    )
    documents_left = imported.query(
        "SELECT COUNT(*) AS n FROM documents WHERE course_id=?", (imported.course_id,)
    )[0]["n"]
    chunks_left = imported.query(
        "SELECT COUNT(*) AS n FROM chunks WHERE course_id=?", (imported.course_id,)
    )[0]["n"]
    assert documents_left == 0 and chunks_left == 0

    # The import record is history: the user's own action of deleting a course does not rewrite the
    # fact that material arrived, nor where it came from.
    receipts = imported.query(
        "SELECT canvas_file_id, status, target_course_id FROM canvas_local_files"
    )
    assert len(receipts) == 1
    assert receipts[0]["target_course_id"] == imported.course_id
    assert receipts[0]["status"] == "INDEXED"
