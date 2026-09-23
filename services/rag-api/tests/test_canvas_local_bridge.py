"""The Local Canvas Bridge: what a user's own machine may and may not do.

The OAuth suite (`test_canvas_api_routes.py`) covers the production route to a school. This suite
covers the fallback that exists while a school has no Developer Key, and it is written around
the one promise that makes that fallback acceptable at all: **the Personal Access Token never
reaches CourseJesus**.

Every test here runs the real application (`app.main.create_app`) with the real database, the real
`IngestionService` and the real routes. What is asserted is the property, not the prose:

* a request that tries to carry a credential is refused by the schema (422), so no route can quietly
  accept one;
* no column in the two new tables could hold one, checked by reading the schema;
* the plaintext code appears exactly once (the response that created the session) and is stored only
  as a hash, so nothing that later reads a session can hand it back;
* the session belongs to one user and one school;
* a file may only arrive for a course the user selected, and the bytes must match the size and
  digest the bridge declared;
* and the import lands in the user's own private course through the real ingestion path, with the
  real quotas — not in a hand-written row.
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

from app.canvas.local_bridge import hash_code
from app.config import Settings
from app.main import create_app

USER = "bridge-user-1"
OTHER_USER = "bridge-user-2"
AUTH = {"Authorization": "Bearer test-session-token"}
CITYU = "cityu"
MARKDOWN = b"# Clustering\n\nDBSCAN groups points by density and marks outliers as noise.\n"
COURSES = [
    {
        "canvas_course_id": "560",
        "name": "Problem Solve & Programming",
        "course_code": "CS2312",
        "term": "Semester B 2025_26",
        "enrollment_state": "active",
        "workflow_state": "available",
        "file_count": 3,
        "size_bytes": 4096,
    },
    {
        "canvas_course_id": "240",
        "name": "Funda. of Internet App. Dev.",
        "course_code": "CS2204",
        "term": "Semester A 2024_25",
        "enrollment_state": "completed",
        "workflow_state": "completed",
        "file_count": 0,
        "size_bytes": 0,
    },
]


@dataclass
class Bridge:
    """A harness that drives the routes exactly as a local tool would."""

    app: Any
    client: TestClient
    settings: Settings
    database: pathlib.Path

    # ------------------------------------------------------------------ session lifecycle
    def open(self, *, institution: str = CITYU, headers: dict[str, str] | None = None) -> dict:
        response = self.client.post(
            "/api/integrations/canvas/local-sessions",
            json={"institution_key": institution},
            headers=headers or AUTH,
        )
        assert response.status_code == 201, response.text
        return response.json()

    def claim(self, code: str, *, user: str | None = None, **overrides) -> Any:
        payload = {
            "code": code,
            "canvas_user_id": "4242",
            "canvas_display_name": "Student One",
            "host_label": "test-laptop",
        }
        payload.update(overrides)
        return self.client.post(
            "/api/integrations/canvas/local-sessions/claim",
            json=payload,
            headers=self.as_user(user),
        )

    def as_user(self, user: str | None) -> dict[str, str]:
        """Become `user` for the following calls; `None` leaves the current identity alone.

        Impersonation is explicit and so is going back (`reset_user`): the verifier is shared state,
        and a test that switched to another user without switching back would run every later call
        as the wrong person — which is how the first version of these tests produced a false
        "another user may use the code" failure.
        """
        if user is not None:
            self.app.state.auth_verifier.user_id = user
        return AUTH

    def reset_user(self) -> None:
        self.app.state.auth_verifier.user_id = USER

    def discover(self, session_id: str, courses: list[dict] | None = None, *, user=None) -> Any:
        return self.client.post(
            f"/api/integrations/canvas/local-sessions/{session_id}/discovery",
            json={"courses": COURSES if courses is None else courses},
            headers=self.as_user(user),
        )

    def select(self, session_id: str, course_ids: list[str], *, user=None) -> Any:
        return self.client.post(
            f"/api/integrations/canvas/local-sessions/{session_id}/selection",
            json={"canvas_course_ids": course_ids},
            headers=self.as_user(user),
        )

    def upload(
        self,
        session_id: str,
        *,
        course_id: str = "560",
        file_id: str = "f-1",
        name: str = "notes.md",
        content: bytes = MARKDOWN,
        declared_size: int | None = None,
        declared_sha256: str | None = None,
        user=None,
    ) -> Any:
        return self.client.post(
            f"/api/integrations/canvas/local-sessions/{session_id}/files",
            data={
                "canvas_course_id": course_id,
                "canvas_file_id": file_id,
                "display_name": name,
                "declared_size": str(len(content) if declared_size is None else declared_size),
                "declared_sha256": (
                    hashlib.sha256(content).hexdigest()
                    if declared_sha256 is None
                    else declared_sha256
                ),
                "source_updated_at": "2026-01-02T03:04:05Z",
            },
            files={"file": (name, content, "application/octet-stream")},
            headers=self.as_user(user),
        )

    def status(self, session_id: str, *, user=None) -> Any:
        return self.client.get(
            f"/api/integrations/canvas/local-sessions/{session_id}",
            headers=self.as_user(user),
        )

    def finish(self, session_id: str, *, user=None) -> Any:
        return self.client.post(
            f"/api/integrations/canvas/local-sessions/{session_id}/finish",
            headers=self.as_user(user),
        )

    def cancel(self, session_id: str, *, user=None) -> Any:
        return self.client.post(
            f"/api/integrations/canvas/local-sessions/{session_id}/cancel",
            headers=self.as_user(user),
        )

    # ------------------------------------------------------------------ database readers
    def query(self, sql: str, parameters: tuple = ()) -> list[sqlite3.Row]:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        try:
            return list(connection.execute(sql, parameters).fetchall())
        finally:
            connection.close()

    def execute(self, sql: str, parameters: tuple = ()) -> None:
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(sql, parameters)
            connection.commit()
        finally:
            connection.close()

    def claimed_session(self, *, user: str | None = None) -> str:
        """A session ready to receive a discovery: open, claimed, and returned by id."""
        opened = self.open()
        assert self.claim(opened["code"]).status_code == 200
        return str(opened["sessionId"])

    def selected_session(self, course_ids: tuple[str, ...] = ("560",)) -> str:
        session_id = self.claimed_session()
        assert self.discover(session_id).status_code == 200
        assert self.select(session_id, list(course_ids)).status_code == 200
        return session_id


def error_code(response) -> str:
    """The typed code from the app's error envelope, or "" when the response was a success."""
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 - a non-JSON body is not an error envelope
        return ""
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        return str(body["error"].get("code", ""))
    return ""


def build(
    tmp_path: pathlib.Path,
    *,
    bridge_enabled: bool = True,
    max_files: int | None = None,
) -> Bridge:
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        ui_web_dir=tmp_path / "no-web-build",
        app_env="test",
        rag_provider_mode="deterministic",
        auth_test_user_id=USER,
        v3_enabled=True,
        canvas_local_bridge_enabled=bridge_enabled,
        **({} if max_files is None else {"user_course_max_files": max_files}),
    )
    app = create_app(settings=settings)
    return Bridge(
        app=app,
        client=TestClient(app),
        settings=settings,
        database=tmp_path / "rag.sqlite3",
    )


@pytest.fixture()
def bridge(tmp_path) -> Bridge:
    return build(tmp_path)


# ---------------------------------------------------------------------------- no credential at all
def test_no_column_of_the_local_bridge_could_hold_a_credential(bridge: Bridge) -> None:
    """The schema is where "the token never reaches CourseJesus" is actually enforced.

    `code_hash` is checked explicitly: it is a SHA-256 of the one-time code, which is the only thing
    about a credential this service ever holds.
    """
    offenders: list[str] = []
    for table in ("canvas_local_sessions", "canvas_local_files"):
        for row in bridge.query(f"PRAGMA table_info({table})"):
            column = str(row["name"]).casefold()
            markers = ("token", "secret", "password", "access", "refresh")
            if any(marker in column for marker in markers):
                offenders.append(f"{table}.{row['name']}")
    assert offenders == [], f"a column could hold a credential: {offenders}"

    row = bridge.query("SELECT sql FROM sqlite_master WHERE name='canvas_local_sessions'")[0]
    assert "code_hash TEXT NOT NULL UNIQUE" in row["sql"]
    assert "token" not in row["sql"].casefold().replace("token_status", "")


def test_a_request_that_carries_a_credential_is_refused_not_ignored(bridge: Bridge) -> None:
    """A bridge (or an attacker) that posts a token must be told no, not silently tolerated."""
    for payload in (
        {"institution_key": CITYU, "token": "canvas-pat-1234567890"},
        {"institution_key": CITYU, "personal_access_token": "x"},
        {"institution_key": CITYU, "canvas_base_url": "https://evil.example", "pat": "x"},
    ):
        response = bridge.client.post(
            "/api/integrations/canvas/local-sessions", json=payload, headers=AUTH
        )
        assert response.status_code == 422, (payload, response.text)

    opened = bridge.open()
    claim = bridge.client.post(
        "/api/integrations/canvas/local-sessions/claim",
        json={
            "code": opened["code"],
            "canvas_user_id": "4242",
            "token": "canvas-pat-1234567890",
        },
        headers=AUTH,
    )
    assert claim.status_code == 422, claim.text
    # …and the session is untouched: a refused claim must not consume the code.
    assert bridge.claim(opened["code"]).status_code == 200


def test_the_code_is_returned_once_and_stored_only_as_a_hash(bridge: Bridge) -> None:
    opened = bridge.open()
    code = opened["code"]
    row = bridge.query("SELECT * FROM canvas_local_sessions WHERE id=?", (opened["sessionId"],))[0]
    assert row["code_hash"] == hash_code(code)
    assert code not in json.dumps(dict(row), default=str)

    # Reading the session back (the page polls it) never returns the code again.
    status = bridge.status(str(opened["sessionId"]))
    assert status.status_code == 200
    assert "code" not in status.json()
    assert code not in status.text
    assert code not in json.dumps(bridge.claim(code).json())


def test_the_capability_route_says_whether_the_bridge_is_available(bridge: Bridge) -> None:
    response = bridge.client.get("/api/integrations/canvas/local-sessions/capability", headers=AUTH)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schemaReady"] is True
    assert body["localBridgeEnabled"] is True

    disabled = build(pathlib.Path(bridge.database).parent / "disabled", bridge_enabled=False)
    body = disabled.client.get(
        "/api/integrations/canvas/local-sessions/capability", headers=AUTH
    ).json()
    assert body["localBridgeEnabled"] is False


def test_an_unregistered_school_is_refused_with_its_name(bridge: Bridge) -> None:
    response = bridge.client.post(
        "/api/integrations/canvas/local-sessions",
        json={"institution_key": "some-other-university"},
        headers=AUTH,
    )
    assert response.status_code == 400
    assert error_code(response) == "CANVAS_UNKNOWN_INSTITUTION"


# ---------------------------------------------------------------------------- session ownership
def test_a_code_can_only_be_claimed_once(bridge: Bridge) -> None:
    opened = bridge.open()
    assert bridge.claim(opened["code"]).status_code == 200
    replay = bridge.claim(opened["code"])
    assert replay.status_code == 409
    assert error_code(replay) == "LOCAL_SESSION_ALREADY_CLAIMED"


def test_another_user_cannot_use_the_code_or_read_the_session(bridge: Bridge) -> None:
    opened = bridge.open()
    session_id = str(opened["sessionId"])

    stolen = bridge.claim(opened["code"], user=OTHER_USER)
    assert stolen.status_code == 404, stolen.text
    assert error_code(stolen) == "LOCAL_SESSION_NOT_FOUND"
    assert bridge.status(session_id, user=OTHER_USER).status_code == 404
    bridge.reset_user()

    # The owner's session is untouched by the attempt.
    assert bridge.claim(opened["code"]).status_code == 200
    assert bridge.status(session_id).status_code == 200


def test_an_expired_session_refuses_a_claim_and_says_so(bridge: Bridge) -> None:
    opened = bridge.open()
    session_id = str(opened["sessionId"])
    bridge.execute(
        "UPDATE canvas_local_sessions SET expires_at='2000-01-01T00:00:00.000Z' WHERE id=?",
        (session_id,),
    )
    stale = bridge.claim(opened["code"])
    assert stale.status_code == 410
    assert error_code(stale) == "LOCAL_SESSION_EXPIRED"
    assert (
        bridge.query("SELECT status FROM canvas_local_sessions WHERE id=?", (session_id,))[0][
            "status"
        ]
        == "EXPIRED"
    )


def test_a_second_user_gets_their_own_course_for_the_same_canvas_course(
    bridge: Bridge,
) -> None:
    first = bridge.selected_session()
    assert bridge.upload(first).status_code == 201
    first_target = bridge.status(first).json()["files"][0]["targetCourseId"]

    # The second user opens and works their *own* session: the same Canvas course id, a different
    # CourseJesus user, therefore a different private course.
    bridge.as_user(OTHER_USER)
    second = bridge.claimed_session()
    assert bridge.discover(second).status_code == 200
    assert bridge.select(second, ["560"]).status_code == 200
    uploaded = bridge.upload(second)
    assert uploaded.status_code == 201, uploaded.text
    bridge.reset_user()

    assert uploaded.json()["targetCourseId"] != first_target
    courses = bridge.query("SELECT id, owner_user_id FROM courses WHERE id LIKE 'canvas-local-%'")
    owners = sorted(str(row["owner_user_id"]) for row in courses)
    assert owners == [USER, OTHER_USER], owners


# ---------------------------------------------------------------------------- discovery/selection
def test_only_discovered_courses_can_be_selected(bridge: Bridge) -> None:
    session_id = bridge.claimed_session()
    assert bridge.discover(session_id).status_code == 200

    unknown = bridge.select(session_id, ["560", "9999"])
    assert unknown.status_code == 400
    assert error_code(unknown) == "LOCAL_DISCOVERY_UNKNOWN_COURSE"
    assert unknown.json()["error"]["details"]["unknown"] == ["9999"]

    # Nothing was written by the refused selection.
    assert bridge.status(session_id).json()["selectedCourseIds"] == []
    assert bridge.select(session_id, ["560"]).status_code == 200


def test_a_file_for_a_course_that_was_not_selected_is_refused(bridge: Bridge) -> None:
    session_id = bridge.selected_session(("560",))
    refused = bridge.upload(session_id, course_id="240")
    assert refused.status_code == 403
    assert error_code(refused) == "LOCAL_COURSE_NOT_SELECTED"
    assert bridge.query("SELECT COUNT(*) AS n FROM canvas_local_files")[0]["n"] == 0
    assert bridge.query("SELECT COUNT(*) AS n FROM documents")[0]["n"] == 0


def test_a_session_without_a_selection_cannot_receive_files(bridge: Bridge) -> None:
    session_id = bridge.claimed_session()
    assert bridge.discover(session_id).status_code == 200
    early = bridge.upload(session_id)
    assert early.status_code == 409
    assert error_code(early) == "LOCAL_SESSION_WRONG_STATE"


def test_files_may_only_arrive_between_selection_and_finish(bridge: Bridge) -> None:
    session_id = bridge.selected_session()
    assert bridge.upload(session_id).status_code == 201
    assert bridge.finish(session_id).status_code == 200

    after = bridge.upload(session_id, file_id="f-2")
    assert after.status_code == 409
    assert error_code(after) == "LOCAL_SESSION_WRONG_STATE"


# ---------------------------------------------------------------------------- the bytes are checked
def test_a_declared_digest_that_does_not_match_the_bytes_is_refused(bridge: Bridge) -> None:
    session_id = bridge.selected_session()
    refused = bridge.upload(session_id, declared_sha256="0" * 64)
    assert refused.status_code == 409
    assert error_code(refused) == "LOCAL_FILE_HASH_MISMATCH"
    assert bridge.query("SELECT COUNT(*) AS n FROM canvas_local_files")[0]["n"] == 0
    assert bridge.query("SELECT COUNT(*) AS n FROM documents")[0]["n"] == 0


def test_a_declared_size_that_does_not_match_the_bytes_is_refused(bridge: Bridge) -> None:
    session_id = bridge.selected_session()
    refused = bridge.upload(session_id, declared_size=len(MARKDOWN) + 1)
    assert refused.status_code == 409
    assert error_code(refused) == "LOCAL_FILE_SIZE_MISMATCH"
    assert bridge.query("SELECT COUNT(*) AS n FROM canvas_local_files")[0]["n"] == 0


@pytest.mark.parametrize(
    "name",
    [
        "../../etc/passwd",
        "..\\..\\windows\\system32\\config",
        "sub/dir/notes.md",
        "notes\x00.md",
        "..",
    ],
)
def test_a_filename_that_is_a_path_is_refused(bridge: Bridge, name: str) -> None:
    session_id = bridge.selected_session()
    refused = bridge.upload(session_id, name=name)
    assert refused.status_code == 400, (name, refused.text)
    assert error_code(refused) == "LOCAL_FILE_NAME_UNSAFE"
    assert bridge.query("SELECT COUNT(*) AS n FROM canvas_local_files")[0]["n"] == 0


# ---------------------------------------------------------------------------- the real import
def test_a_file_becomes_a_document_in_the_users_own_private_course(bridge: Bridge) -> None:
    session_id = bridge.selected_session()
    response = bridge.upload(session_id)
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert receipt["status"] == "INDEXED"
    assert receipt["duplicate"] is False

    course = bridge.query("SELECT * FROM courses WHERE id=?", (receipt["targetCourseId"],))[0]
    assert course["owner_user_id"] == USER
    assert course["course_type"] == "user"
    assert course["visibility"] == "private"
    assert course["publication_status"] == "private"
    assert course["published_at"] is None

    document = bridge.query(
        "SELECT * FROM documents WHERE course_id=?", (receipt["targetCourseId"],)
    )[0]
    assert document["id"] == receipt["documentId"]
    assert document["chunk_count"] > 0
    # The file itself was written under this user's storage area, not into a shared one.
    stored = pathlib.Path(str(document["stored_path"]))
    assert stored.exists() and stored.is_file()
    assert USER in stored.as_posix() or str(document["id"]) in stored.name


def test_re_uploading_the_same_bytes_returns_the_first_receipt(bridge: Bridge) -> None:
    session_id = bridge.selected_session()
    first = bridge.upload(session_id).json()

    again = bridge.upload(session_id)
    assert again.status_code == 201
    assert again.json()["duplicate"] is True
    assert again.json()["documentId"] == first["documentId"]
    assert bridge.query("SELECT COUNT(*) AS n FROM canvas_local_files")[0]["n"] == 1
    assert bridge.query("SELECT COUNT(*) AS n FROM documents")[0]["n"] == 1


def test_the_same_file_id_with_new_bytes_is_a_new_version_not_a_skip(bridge: Bridge) -> None:
    """The Canvas file id alone must never mean "already imported"."""
    session_id = bridge.selected_session()
    first = bridge.upload(session_id, file_id="f-9").json()

    changed = MARKDOWN + b"Edited.\n"
    second = bridge.upload(session_id, file_id="f-9", content=changed)
    assert second.status_code == 201, second.text
    assert second.json()["duplicate"] is False
    assert second.json()["documentId"] != first["documentId"]
    assert bridge.query("SELECT COUNT(*) AS n FROM canvas_local_files")[0]["n"] == 2


def test_two_files_with_the_same_name_but_different_ids_are_two_documents(bridge: Bridge) -> None:
    session_id = bridge.selected_session()
    one = bridge.upload(session_id, file_id="f-1", name="notes.md").json()
    other = bridge.upload(
        session_id, file_id="f-2", name="notes.md", content=MARKDOWN + b"\nTutorial 2.\n"
    ).json()
    assert other["documentId"] != one["documentId"]
    assert bridge.query("SELECT COUNT(*) AS n FROM canvas_local_files")[0]["n"] == 2


def test_a_file_no_loader_can_read_is_stored_but_never_indexed(bridge: Bridge) -> None:
    session_id = bridge.selected_session()
    archive = bridge.upload(
        session_id, file_id="f-z", name="slides.zip", content=b"PK\x03\x04not really a zip"
    )
    assert archive.status_code == 201, archive.text
    assert archive.json()["status"] in {"DOWNLOAD_ONLY", "REJECTED"}
    assert bridge.query("SELECT COUNT(*) AS n FROM documents WHERE chunk_count > 0")[0]["n"] == 0


def test_finishing_reports_a_warning_when_a_file_was_not_indexed(bridge: Bridge) -> None:
    session_id = bridge.selected_session()
    assert bridge.upload(session_id).status_code == 201
    assert (
        bridge.upload(
            session_id, file_id="f-z", name="slides.zip", content=b"PK\x03\x04nope"
        ).status_code
        == 201
    )

    finished = bridge.finish(session_id)
    assert finished.status_code == 200, finished.text
    body = finished.json()
    assert body["status"] in {"COMPLETED", "COMPLETED_WITH_WARNINGS"}
    counts = body["counts"]
    assert counts.get("INDEXED") == 1
    assert sum(counts.values()) == 2

    status = bridge.status(session_id).json()
    assert status["status"] == body["status"]
    assert len(status["files"]) == 2
    assert status["completedAt"]


def test_cancelling_keeps_what_was_already_imported(bridge: Bridge) -> None:
    session_id = bridge.selected_session()
    receipt = bridge.upload(session_id).json()

    cancelled = bridge.cancel(session_id)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"

    # The user's own material is theirs: cancelling stops the import, it does not delete a course.
    assert bridge.query("SELECT COUNT(*) AS n FROM documents")[0]["n"] == 1
    kept = bridge.query(
        "SELECT COUNT(*) AS n FROM courses WHERE id=?", (receipt["targetCourseId"],)
    )[0]["n"]
    assert kept == 1
    assert bridge.upload(session_id, file_id="f-2").status_code == 409


def test_a_retry_after_a_crash_does_not_duplicate_documents(bridge: Bridge) -> None:
    """The bridge may resend a file it is not sure about; the server must be idempotent."""
    session_id = bridge.selected_session()
    first = bridge.upload(session_id).json()
    for _ in range(2):
        again = bridge.upload(session_id)
        assert again.status_code == 201
        assert again.json()["documentId"] == first["documentId"]
    assert bridge.query("SELECT COUNT(*) AS n FROM documents")[0]["n"] == 1


def test_the_private_course_quota_is_the_real_one_and_not_skipped(tmp_path) -> None:
    """The bridge goes through the ingestion service, so the deployment's quota applies to it.

    The limit is the deployment's `USER_COURSE_MAX_FILES`. With it set to one, the second file in
    the same private course must be refused with the real quota code rather than silently stored.
    """
    bridge = build(tmp_path, max_files=1)
    session_id = bridge.selected_session()
    assert bridge.upload(session_id, file_id="f-1").status_code == 201

    second = bridge.upload(session_id, file_id="f-2", content=MARKDOWN + b"\nsecond\n")
    assert second.status_code == 201, second.text
    assert second.json()["status"] == "REJECTED"
    assert "COURSE_FILE_QUOTA_EXCEEDED" in second.json()["reason"]
    assert bridge.query("SELECT COUNT(*) AS n FROM documents")[0]["n"] == 1
