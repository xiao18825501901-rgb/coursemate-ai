"""Soft semantic routing must not call or cache the retired TypeSafe provider.

The owner-approved OpenJev transition removed TypeSafe/Jev from optional routing,
reranking and classification. Those soft paths now use deterministic routing and must
not create a provider receipt or semantic cache entry at all. Hard Question Engine
quality gates retain their separate fail-closed, owner-scoped receipt contract.

This suite drives the mounted product over HTTP with two identities and proves that
ordinary teaching completes while the retired soft provider remains completely unused.
The dedicated gateway tests continue to pin owner-scoped cache isolation for hard gates.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database
from app.main import create_app

UI = "/ui-extension/api/ui/v1"
A = {"Authorization": "Bearer token-a"}
B = {"Authorization": "Bearer token-b"}
ADMIN = {"Authorization": "Bearer admin-token"}
SUBJECTS = {
    "Bearer token-a": "user-a",
    "Bearer token-b": "user-b",
    "Bearer admin-token": "user-admin",
}


class FakeAuthVerifier:
    def authenticate(self, request: Request) -> str | None:
        return SUBJECTS.get(request.headers.get("authorization", ""))


class FakeEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("CMUI_PROVIDER_MODE", "test")
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        admin_user_ids="user-admin",
        app_env="test",
        v3_enabled=True,
        ui_extension_enabled=True,
        rag_provider_mode="deterministic",
        ui_web_dir=tmp_path / "no-web-build",
    )
    application = create_app(
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
    )
    with TestClient(application) as test_client:
        from campus_actor_fixture import authorize_synthetic_campus_users

        authorize_synthetic_campus_users(test_client, "user-a")
        authorize_synthetic_campus_users(test_client, "user-b")
        yield test_client


def _ask(client: TestClient, headers: dict[str, str], text: str, request_id: str) -> dict[str, Any]:
    """One teach run for one subject, waited to a terminal state."""
    conversation = client.post(
        f"{UI}/conversations",
        headers=headers,
        json={"course": "cs3481", "lane": "teach"},
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]
    started = client.post(
        f"{UI}/conversations/{conversation_id}/runs",
        headers=headers,
        json={"text": text, "request_id": request_id},
    )
    assert started.status_code == 202, started.text
    run_id = started.json()["id"]
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        row = client.get(f"{UI}/runs/{run_id}", headers=headers).json()
        if row["status"] in {"completed", "failed", "cancelled"}:
            assert row["status"] == "completed", row
            return row
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} did not finish")


def _receipts(database: Database) -> list[dict[str, Any]]:
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT definition_key, owner_scope_hash, caller_role, outcome "
            "FROM jev_decision_receipts ORDER BY created_at"
        ).fetchall()
    return [dict(row) for row in rows]


def test_two_subjects_soft_semantic_routing_creates_no_provider_cache_scope(
    client: TestClient, tmp_path: Path
) -> None:
    created = client.post(
        "/api/courses",
        headers=ADMIN,
        json={"id": "cs3481", "name": "Fundamentals of Data Science", "description": "Notes"},
    )
    assert created.status_code == 201, created.text

    question = "请从零教我理解聚类"
    _ask(client, A, question, "isolation-a-0001")
    _ask(client, B, question, "isolation-b-0001")

    database = Database(
        Settings(
            database_path=tmp_path / "rag.sqlite3",
            upload_dir=tmp_path / "uploads",
            v3_enabled=True,
        )
    )
    rows = _receipts(database)
    assert rows == [], (
        "ordinary teaching must use deterministic soft routing and must not call, "
        f"receipt, or cache the retired TypeSafe provider: {rows}"
    )


# What is deliberately *not* here: a second test asserting that one subject's uploaded
# document never reaches another's answer. In this deployment shape that assertion cannot
# be set up honestly — the upload route takes a multipart `file` and the campus content
# gate refuses it without a redeemed student verification (`set_verified` is a fixture-only
# write), so such a test would either skip or grant itself a qualification inside an
# isolation test. The content-level property is pinned where it can be:
# `test_jev_shadow_invariance`, the course-access suite, and the `learning.spec.ts`
# journey that keeps two students isolated end to end.
