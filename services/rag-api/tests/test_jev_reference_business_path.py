"""Module A on the real business path: the shipped adapter, real ingestion, real corpus.

`test_jev_reference_verification.py` pins the module's own contract with an offline
transport. This file pins the thing that actually matters: that the adapter a
generation run calls (`context.retrieve`) verifies the exact-locator label before it
becomes a filter, over a document whose question labels came from the real
parser/chunker rather than from a hand-written fixture row.

Three properties are checked here and nowhere else:

1. a labelled document really is produced by ingestion, so the locator has something
   correct to match;
2. a message naming a question produces a recall whose sources report *how* that
   label was verified — and with no credential present, that report says the
   deterministic reference was used and nothing was claimed;
3. a message that merely contains the word "question" plus a number in prose is not
   pinned by an invented sub-part filter.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import anyio
import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from test_ui_extension_integration import open_corpus_lock, restore_corpus_lock

from app.config import Settings
from app.main import create_app

COURSE = "cs3481"

# A document that exposes real structure: a document kind + number in the heading,
# explicit "Question N" blocks, and parenthesised sub-parts. Written as text so
# ingestion needs no PDF toolchain, while still going through the real chunker and
# structure parser.
ASSIGNMENT_MARKDOWN = b"""# Assignment 2

Question 1
(a) Compute the mean of the sample and state the same result in two ways.
(b) Compute the variance of the sample.

Question 2
Explain the central limit theorem and why it matters.
"""

DOCUMENT_NAME = "Assignment_2.md"
REFERENCE_QUERY = "Assignment_2.md Question 1(b) \u7684\u7b54\u6848\u662f\u4ec0\u4e48"
PROSE_QUERY = "What does question 5 have to do with chapter 2?"

SUBJECTS = {"Bearer token-a": "user-a", "Bearer admin-token": "user-admin"}


class FakeAuthVerifier:
    def authenticate(self, request: Request) -> str | None:
        return SUBJECTS.get(request.headers.get("authorization", ""))


class FakeEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        chunk_size=400,
        chunk_overlap=40,
        top_k=5,
        admin_user_ids="user-admin",
        app_env="test",
        v3_enabled=True,
        ui_extension_enabled=True,
        rag_provider_mode="deterministic",
        ui_web_dir=tmp_path / "no-web-build",
    )


def ingest_assignment(client: TestClient) -> None:
    created = client.post(
        "/api/courses",
        headers={"Authorization": "Bearer admin-token"},
        json={"id": COURSE, "name": "Fundamentals of Data Science", "description": "Notes"},
    )
    assert created.status_code == 201, created.text
    uploaded = client.post(
        f"/api/courses/{COURSE}/documents",
        headers={"Authorization": "Bearer admin-token"},
        files={"file": (DOCUMENT_NAME, ASSIGNMENT_MARKDOWN, "text/markdown")},
    )
    assert uploaded.status_code == 202, uploaded.text


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """The real host application, with the reviewed corpus imported first.

    A reviewed official course locks its documents and chunks against further
    inserts (migration 019) — real behaviour the shipped path must keep. The same
    corpus-import window the UI integration suite uses is therefore opened for the
    ingestion only, and closed again before any assertion, so every request under
    test sees the real locks.
    """

    application = create_app(
        settings=_settings(tmp_path),
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
    )
    with TestClient(application) as test_client:
        from campus_actor_fixture import authorize_synthetic_campus_users

        authorize_synthetic_campus_users(test_client, "user-a")
        open_corpus_lock(test_client)
        try:
            ingest_assignment(test_client)
        finally:
            restore_corpus_lock(test_client)
        yield test_client


def retrieve(client: TestClient, query: str, *, token: str = "Bearer token-a") -> list[dict]:
    """Exercise `context.retrieve` through the adapter a generation run uses."""

    adapter = client.app.state.ui_extension_adapter  # type: ignore[attr-defined]
    return anyio.run(
        adapter.call,
        "context.retrieve",
        SUBJECTS[token],
        {"course": COURSE, "query": query},
        token,
    )


def label_rows(client: TestClient) -> list[tuple[str, str | None]]:
    adapter = client.app.state.ui_extension_adapter  # type: ignore[attr-defined]
    with adapter.database.connect() as connection:
        rows = connection.execute(
            """
            SELECT json_extract(metadata_json, '$.question_number') AS number,
                   json_extract(metadata_json, '$.question_part') AS part
            FROM chunks
            WHERE json_extract(metadata_json, '$.question_number') IS NOT NULL
            """
        ).fetchall()
    return [(str(row["number"]), row["part"]) for row in rows]


def test_ingestion_produces_the_question_labels_the_locator_needs(client: TestClient) -> None:
    """If ingestion did not label the document, the rest of this file proves nothing."""
    labels = set(label_rows(client))
    assert ("1", "a") in labels, labels
    assert ("1", "b") in labels, labels


def test_a_named_question_recalls_exactly_and_reports_how_it_was_verified(
    client: TestClient,
) -> None:
    sources = retrieve(client, REFERENCE_QUERY)
    assert sources, "the labelled document must be recallable"
    assert any(source["name"] == DOCUMENT_NAME for source in sources)

    reports = [source.get("jev_reference") for source in sources]
    assert all(report is not None for report in reports), "every source carries the report"
    report = reports[0]
    assert report["questioned"] is True
    assert {field["field"] for field in report["fields"]} == {
        "question_number",
        "question_part",
    }
    assert {field["value"] for field in report["fields"]} == {"1", "b"}
    # With no TypeSafe credential configured, nothing may claim the label was
    # verified: every field degrades typed, the deterministic reference is used
    # unchanged, and both labels are on record as needing review.
    assert report["dropped"] == []
    assert report["needs_review"] == ["question_number", "question_part"]
    assert report["jev_calls"] == 2  # one bounded attempt per labelled field
    for field in report["fields"]:
        assert field["used_jev"] is False
        assert field["verdict"] is None
        assert field["status"] == "NEEDS_REVIEW"
        assert field["path"].startswith("fallback:")
        # Kept, because uncertainty may never silently remove a locator.
        assert field["trusted"] is True


def test_prose_is_not_pinned_by_an_invented_sub_part(client: TestClient) -> None:
    """`question 5 have ...` used to become the filter `question_part = 'h'`."""
    sources = retrieve(client, PROSE_QUERY)
    assert sources
    report = sources[0]["jev_reference"]
    assert report["questioned"] is True
    # Only the number is a label; the following word is prose, not a sub-part.
    assert [field["field"] for field in report["fields"]] == ["question_number"]
    assert report["fields"][0]["value"] == "5"
    assert report["dropped"] == []


def test_a_message_without_a_label_costs_nothing(client: TestClient) -> None:
    """A question that names no question is not a reference decision at all."""
    sources = retrieve(client, "\u805a\u7c7b\u5206\u6790\u662f\u4ec0\u4e48\u610f\u601d")
    assert sources
    for source in sources:
        report = source["jev_reference"]
        assert report["questioned"] is False
        assert report["fields"] == []
        assert report["dropped"] == []
        assert report["jev_calls"] == 0  # nothing was sent anywhere
