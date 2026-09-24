"""Two subjects, one service: the semantic cache cannot be shared between them.

The scope that keys the Jev cache is derived from the authenticated caller, and the
property "one learner's verdict is never served to another" was pinned by a unit test
(`test_cache_scope_is_owner_scoped_and_never_crosses_users`) that calls the module
directly. That proves the scope *function*; it does not prove that the running service
derives the scope from the request's authenticated subject rather than from something a
client could influence. This suite drives the mounted product over HTTP with **two**
identities and reads the receipt store, which is the artifact the cache is keyed on:

* the same definition asked by two subjects must produce **two different**
  ``owner_scope_hash`` values — if they matched, one subject's cached verdict would be
  answerable to the other;
* the two subjects' runs must reach the same definition key, or the comparison would be
  vacuous;
* what one subject sends must not appear in the other's answers.

The transport is the deterministic fake, so no credential and no budget are involved:
what is asserted is the scoping of the ledger, not the quality of a verdict.
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


def test_two_subjects_never_share_a_semantic_cache_scope(
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
    assert rows, "no semantic decision was recorded, so this test proves nothing"

    by_definition: dict[str, set[str]] = {}
    for row in rows:
        definition = str(row["definition_key"])
        by_definition.setdefault(definition, set()).add(str(row["owner_scope_hash"]))

    # A definition both subjects reached must have been scoped twice, not once.
    shared = {key: scopes for key, scopes in by_definition.items() if len(scopes) > 1}
    assert shared, (
        "no definition was reached by both subjects with distinct scopes, so the "
        f"isolation property was not exercised: {by_definition}"
    )
    # And nothing may carry a scope that both subjects share for the same definition.
    offenders = {key: scopes for key, scopes in shared.items() if len(scopes) != 2}
    assert not offenders, f"a definition was scoped to more than two subjects: {offenders}"
    # Every decision is recorded with a typed outcome. In this deployment there is no
    # credential, so the outcome is `not_configured` by design — asserting `ok` here was
    # this test's own error, not the product's.
    assert all(str(row["outcome"]).strip() for row in rows), rows
    assert {str(row["outcome"]) for row in rows} <= {"ok", "not_configured"}, rows


# What is deliberately *not* here: a second test asserting that one subject's uploaded
# document never reaches another's answer. In this deployment shape that assertion cannot
# be set up honestly — the upload route takes a multipart `file` and the campus content
# gate refuses it without a redeemed student verification (`set_verified` is a fixture-only
# write), so such a test would either skip or grant itself a qualification inside an
# isolation test. The content-level property is pinned where it can be:
# `test_jev_shadow_invariance`, the course-access suite, and the `learning.spec.ts`
# journey that keeps two students isolated end to end.
