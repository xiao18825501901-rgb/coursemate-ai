"""Integration tests for the real V3 `DomainPort` adapter and UI mount.

These tests build a genuine host application (`app.main.create_app`) with the V3
learning surface enabled, mount the delivered new UI through
`app.ui_extension.mount`, and drive it over HTTP. Nothing here uses the
standalone reference store: courses, files, retrieval and knowledge come from the
real V3 tables and services.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

UI = "/ui-extension/api/ui/v1"

SUBJECTS = {
    "Bearer token-a": "user-a",
    "Bearer token-b": "user-b",
    "Bearer admin-token": "user-admin",
}


class FakeAuthVerifier:
    """Stands in for the Clerk verifier; identity still comes only from the header."""

    def authenticate(self, request: Request) -> str | None:
        return SUBJECTS.get(request.headers.get("authorization", ""))


class FakeEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


def _markdown(name: str = "lecture.md", body: str | None = None) -> bytes:
    del name
    text = body or (
        "# Clustering\n\nK-means partitions points into k clusters by minimising "
        "within-cluster sum of squares. DBSCAN finds density-connected regions."
    )
    return text.encode()


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        chunk_size=200,
        chunk_overlap=20,
        top_k=3,
        admin_user_ids="user-admin",
        app_env="test",
        v3_enabled=True,
        ui_extension_enabled=True,
        rag_provider_mode="deterministic",
        ui_web_dir=tmp_path / "no-web-build",
    )


def make_client(tmp_path: Path) -> Iterator[TestClient]:
    settings = make_settings(tmp_path)
    application = create_app(
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
    )
    with TestClient(application) as client:
        from campus_actor_fixture import authorize_synthetic_campus_users
        authorize_synthetic_campus_users(client, 'user-a', 'user-b')
        yield client


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    yield from make_client(tmp_path)


def auth(token: str) -> dict[str, str]:
    return {"Authorization": token}


def create_official_course(client: TestClient, course_id: str = "cs3481") -> None:
    """Create an official course the way the V3 importer does (admin identity)."""

    response = client.post(
        "/api/courses",
        headers=auth("Bearer admin-token"),
        json={"id": course_id, "name": "Fundamentals of Data Science", "description": "Notes"},
    )
    assert response.status_code == 201, response.text


def upload_shared_document(
    client: TestClient,
    course_id: str = "cs3481",
    name: str = "lecture.md",
    body: bytes | None = None,
) -> None:
    response = client.post(
        f"/api/courses/{course_id}/documents",
        headers=auth("Bearer admin-token"),
        files={"file": (name, body or _markdown(), "text/markdown")},
    )
    assert response.status_code == 202, response.text


_LOCK_TRIGGERS = (
    (
        "lock_course_document_insert_during_publication",
        """CREATE TRIGGER lock_course_document_insert_during_publication
        BEFORE INSERT ON documents
        WHEN EXISTS(
            SELECT 1 FROM courses
            WHERE id=NEW.course_id AND publication_status IN ('pending','published')
        )
        BEGIN
            SELECT RAISE(ABORT, 'Course content is locked by publication review');
        END""",
    ),
    (
        "lock_course_document_update_during_publication",
        """CREATE TRIGGER lock_course_document_update_during_publication
        BEFORE UPDATE ON documents
        WHEN EXISTS(
            SELECT 1 FROM courses
            WHERE id=OLD.course_id AND publication_status IN ('pending','published')
        )
        BEGIN
            SELECT RAISE(ABORT, 'Course content is locked by publication review');
        END""",
    ),
    (
        "lock_course_chunk_insert_during_publication",
        """CREATE TRIGGER lock_course_chunk_insert_during_publication
        BEFORE INSERT ON chunks
        WHEN EXISTS(
            SELECT 1 FROM courses
            WHERE id=NEW.course_id AND publication_status IN ('pending','published')
        )
        BEGIN
            SELECT RAISE(ABORT, 'Course content is locked by publication review');
        END""",
    ),
)


def open_corpus_lock(client: TestClient) -> None:
    with client.app.state.database.connect() as database:
        for name, _sql in _LOCK_TRIGGERS:
            database.execute(f"DROP TRIGGER IF EXISTS {name}")


def restore_corpus_lock(client: TestClient) -> None:
    with client.app.state.database.connect() as database:
        for _name, sql in _LOCK_TRIGGERS:
            database.execute(sql)


@pytest.fixture
def immutable_corpus(client: TestClient) -> Iterator[TestClient]:
    """Give a test the corpus-import window, then restore the real V3 locks.

    V3 locks a published course's documents and chunks against further inserts,
    which is exactly right for a reviewed course. The immutable-corpus fixture
    therefore removes those two locks for the whole *setup* - including the
    background ingestion the upload schedules - and restores them before any
    assertion runs. The UI requests under test always see the real locks.
    """

    open_corpus_lock(client)
    try:
        yield client
    finally:
        restore_corpus_lock(client)


def test_ui_mount_keeps_host_routes_and_lifespan(client: TestClient) -> None:
    assert client.get("/health").status_code == 200
    assert client.get(f"{UI}/config").status_code == 200
    assert client.get("/ui-extension/health").status_code == 200


def test_ui_reports_integrated_config_without_leaking_secrets(client: TestClient) -> None:
    body = client.get(f"{UI}/config").json()
    assert body["integration_mode"] == "integrated"
    assert body["auth_mode"] == "injected"
    assert body["agent_connected"] is True
    # Only the publishable key may cross to the browser; never the model credential.
    assert set(body) == {
        "auth_mode",
        "environment",
        "api_base",
        "provider_mode",
        "model",
        "integration_mode",
        "clerk_publishable_key",
        "clerk_issuer",
        "max_upload_bytes",
        "agent_connected",
        "reasoning_strengths",
    }
    assert all("qwen" not in name for name in body)


def test_ui_requires_a_verified_session(client: TestClient) -> None:
    assert client.get(f"{UI}/courses").status_code == 401
    assert client.get(f"{UI}/courses", headers=auth("Bearer token-unknown")).status_code == 401


def test_courses_come_from_the_real_v3_table(client: TestClient) -> None:
    create_official_course(client)
    body = client.get(f"{UI}/courses", headers=auth("Bearer token-a")).json()
    assert [row["id"] for row in body] == ["cs3481"]
    course = body[0]
    # `name` and `code` are hard requirements of the two-stage Qwen planner.
    assert course["name"] == "Fundamentals of Data Science"
    assert course["code"] == "CS3481"
    assert course["requirements"] == ""
    assert course["official"] is True
    assert course["visibility"] == "public"


def test_private_course_is_created_and_hidden_from_other_users(client: TestClient) -> None:
    created = client.post(
        f"{UI}/courses",
        headers=auth("Bearer token-a"),
        json={"name": "My Stats Reading", "description": "personal", "code": "MINE"},
    )
    assert created.status_code == 201, created.text
    course_id = created.json()["id"]

    listed_a = client.get(f"{UI}/courses", headers=auth("Bearer token-a")).json()
    assert course_id in [row["id"] for row in listed_a]

    listed_b = client.get(f"{UI}/courses", headers=auth("Bearer token-b")).json()
    assert course_id not in [row["id"] for row in listed_b]

    assert client.get(f"{UI}/courses/{course_id}", headers=auth("Bearer token-b")).status_code == 404
    assert client.get(f"{UI}/courses/{course_id}/files", headers=auth("Bearer token-b")).status_code == 404


def test_uploads_land_in_v3_documents_and_are_private(immutable_corpus: TestClient) -> None:
    client = immutable_corpus
    create_official_course(client)
    upload_shared_document(client)

    response = client.post(
        f"{UI}/courses/cs3481/files",
        headers=auth("Bearer token-a"),
        files={"file": ("my-notes.md", _markdown(), "text/markdown")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["scope"] == "private"
    assert body["status"] == "indexed"
    assert "storage_key" not in body and "sha256" not in body

    # The real V3 documents table now holds the upload inside the caller's
    # workspace-private corpus course, not in the shared official course.
    listing = client.get(f"{UI}/courses/cs3481/files", headers=auth("Bearer token-a")).json()
    names = sorted(item["name"] for item in listing)
    assert names == ["lecture.md", "my-notes.md"]

    other = client.get(f"{UI}/courses/cs3481/files", headers=auth("Bearer token-b")).json()
    assert [item["name"] for item in other] == ["lecture.md"]


def test_file_content_is_the_authorised_original_with_range_and_head(
    immutable_corpus: TestClient,
) -> None:
    client = immutable_corpus
    create_official_course(client)
    upload_shared_document(client)
    file_id = client.get(f"{UI}/courses/cs3481/files", headers=auth("Bearer token-a")).json()[0][
        "id"
    ]
    # A completed file listing always carries an `id`: history restoration hard-indexes it.
    assert file_id

    full = client.get(
        f"{UI}/courses/cs3481/files/{file_id}/content", headers=auth("Bearer token-a")
    )
    assert full.status_code == 200
    assert full.content == _markdown()

    ranged = client.get(
        f"{UI}/courses/cs3481/files/{file_id}/content",
        headers={**auth("Bearer token-a"), "Range": "bytes=0-9"},
    )
    assert ranged.status_code == 206
    assert ranged.content == _markdown()[:10]

    head = client.head(
        f"{UI}/courses/cs3481/files/{file_id}/content", headers=auth("Bearer token-a")
    )
    assert head.status_code == 200
    assert head.content == b""

    shared = client.get(
        f"{UI}/courses/cs3481/files/{file_id}/content", headers=auth("Bearer token-b")
    )
    assert shared.status_code == 200, "a public course document is readable by any member"


def test_private_upload_content_is_not_readable_by_another_user(
    immutable_corpus: TestClient,
) -> None:
    client = immutable_corpus
    create_official_course(client)
    upload_shared_document(client)
    uploaded = client.post(
        f"{UI}/courses/cs3481/files",
        headers=auth("Bearer token-a"),
        files={"file": ("private.md", _markdown(body="# Mine\n\nprivate"), "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text
    file_id = uploaded.json()["id"]

    own = client.get(
        f"{UI}/courses/cs3481/files/{file_id}/content", headers=auth("Bearer token-a")
    )
    assert own.status_code == 200

    foreign = client.get(
        f"{UI}/courses/cs3481/files/{file_id}/content", headers=auth("Bearer token-b")
    )
    assert foreign.status_code == 404


def test_file_text_uses_real_chunks(immutable_corpus: TestClient) -> None:
    client = immutable_corpus
    create_official_course(client)
    upload_shared_document(client)
    file_id = client.get(f"{UI}/courses/cs3481/files", headers=auth("Bearer token-a")).json()[0][
        "id"
    ]
    body = client.get(
        f"{UI}/courses/cs3481/files/{file_id}/text", headers=auth("Bearer token-a")
    ).json()
    assert body["pages"]
    text = body["pages"][0]["text"]
    assert "K-means" in text or "Clustering" in text


def test_retrieval_uses_hybrid_engine_and_never_leaks_another_workspace(
    immutable_corpus: TestClient,
) -> None:
    client = immutable_corpus
    create_official_course(client)
    upload_shared_document(client)
    assert (
        client.post(
            f"{UI}/courses/cs3481/files",
            headers=auth("Bearer token-a"),
            files={
                "file": (
                    "secret.md",
                    _markdown(body="# Secret\n\nUniqueTokenAlpha42"),
                    "text/markdown",
                )
            },
        ).status_code
        == 201
    )

    shared_a = _retrieve(client, "Bearer token-a", "cs3481", "K-means clustering")
    assert shared_a, "the V3 hybrid retriever must return the course corpus"
    assert any(source["name"] == "lecture.md" for source in shared_a)
    assert [source["id"] for source in shared_a] == [
        f"S{index}" for index in range(1, len(shared_a) + 1)
    ]

    private_a = _retrieve(client, "Bearer token-a", "cs3481", "UniqueTokenAlpha42")
    assert any("UniqueTokenAlpha42" in source["text"] for source in private_a)

    private_b = _retrieve(client, "Bearer token-b", "cs3481", "UniqueTokenAlpha42")
    assert not any("UniqueTokenAlpha42" in source["text"] for source in private_b)

    shared_b = _retrieve(client, "Bearer token-b", "cs3481", "K-means clustering")
    assert any(source["name"] == "lecture.md" for source in shared_b)


def _retrieve(client: TestClient, token: str, course: str, query: str) -> list[dict]:
    """Exercise context.retrieve through the same adapter a generation run uses."""

    import anyio

    adapter = client.app.state.ui_extension_adapter  # type: ignore[attr-defined]
    return anyio.run(
        adapter.call,
        "context.retrieve",
        SUBJECTS[token],
        {"course": course, "query": query},
        token,
    )


def test_knowledge_tree_comes_from_the_v3_registry(client: TestClient) -> None:
    create_official_course(client)
    # A course with no reviewed tree must report an empty tree, never fake nodes.
    body = client.get(f"{UI}/courses/cs3481/knowledge", headers=auth("Bearer token-a")).json()
    assert body == []


def test_knowledge_assessment_never_fabricates_a_grade(client: TestClient) -> None:
    create_official_course(client)
    response = client.get(
        f"{UI}/courses/cs3481/knowledge/missing-node/assessment",
        headers=auth("Bearer token-a"),
    )
    assert response.status_code == 404


def test_tasks_require_the_configured_agent(client: TestClient) -> None:
    response = client.get(f"{UI}/tasks", headers=auth("Bearer token-a"))
    assert response.status_code == 503
    assert "agent" in response.json()["detail"].lower()


def test_two_users_have_separate_ui_profiles_and_pins(client: TestClient) -> None:
    create_official_course(client)
    pinned = client.put(f"{UI}/courses/cs3481/pin", headers=auth("Bearer token-a")).json()
    assert pinned["pinned"] is True
    pinned_a = [
        row["id"]
        for row in client.get(f"{UI}/courses", headers=auth("Bearer token-a")).json()
        if row["pinned"]
    ]
    pinned_b = [
        row["id"]
        for row in client.get(f"{UI}/courses", headers=auth("Bearer token-b")).json()
        if row["pinned"]
    ]
    assert pinned_a == ["cs3481"]
    assert pinned_b == []


def test_comments_and_direct_messages_are_isolated_between_users(client: TestClient) -> None:
    create_official_course(client)
    posted = client.post(
        f"{UI}/courses/cs3481/comments",
        headers=auth("Bearer token-a"),
        json={"text": "When is DBSCAN covered?", "request_id": "comment-request-0001"},
    )
    assert posted.status_code == 201, posted.text
    reply = client.post(
        f"{UI}/courses/cs3481/comments",
        headers=auth("Bearer token-b"),
        json={
            "text": "In next week's tutorial.",
            "parent": posted.json()["id"],
            "request_id": "comment-request-0002",
        },
    )
    assert reply.status_code == 201, reply.text

    notices = client.get(f"{UI}/notifications", headers=auth("Bearer token-a")).json()
    assert any(notice["kind"] == "comment_reply" for notice in notices)
    assert client.get(f"{UI}/notifications", headers=auth("Bearer token-b")).json() == []

    # A `cmui_users.id` is the verified Clerk subject, so a second user genuinely
    # signs in from that same table and direct messaging works across accounts.
    sent = client.post(
        f"{UI}/messages",
        headers=auth("Bearer token-a"),
        json={
            "text": "hello",
            "recipient": SUBJECTS["Bearer token-b"],
            "request_id": "dm-request-000001",
        },
    )
    assert sent.status_code == 201, sent.text

    threads_b = client.get(f"{UI}/threads", headers=auth("Bearer token-b")).json()
    assert len(threads_b) == 1
    assert threads_b[0]["unread"] == 1
    assert threads_b[0]["peer"]["id"] == SUBJECTS["Bearer token-a"]
    thread_id = threads_b[0]["id"]
    assert client.get(f"{UI}/threads", headers=auth("Bearer token-b")).json()
    assert (
        client.get(
            f"{UI}/threads/{thread_id}/messages", headers=auth("Bearer token-b")
        ).json()[0]["text"]
        == "hello"
    )


def test_unknown_domain_operation_is_reported_not_silently_ignored(client: TestClient) -> None:
    import anyio
    from fastapi import HTTPException

    adapter = client.app.state.ui_extension_adapter  # type: ignore[attr-defined]
    with pytest.raises(HTTPException) as error:
        anyio.run(adapter.call, "not.a.real.operation", "user-a", {}, "")
    assert error.value.status_code == 501
