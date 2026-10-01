from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.cm_update.db import now
from app.config import Settings
from app.main import create_app

UI = "/ui-extension/api/ui/v1"
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


def auth(token: str) -> dict[str, str]:
    return {"Authorization": token}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        storage_cache_dir=tmp_path / "cache",
        app_env="test",
        v3_enabled=True,
        ui_extension_enabled=True,
        visual_engine_enabled=True,
        visual_worker_poll_seconds=60,
        rag_provider_mode="deterministic",
        admin_user_ids="user-admin",
        ui_web_dir=tmp_path / "no-web-build",
    )
    application = create_app(
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
    )
    with TestClient(application) as value:
        from campus_actor_fixture import authorize_synthetic_campus_users

        authorize_synthetic_campus_users(value, "user-a", "user-b")
        yield value


def seed_answer(
    client: TestClient, question_text: str = "Show the CPU pipeline stages"
) -> tuple[str, str]:
    created = client.post(
        "/api/courses",
        headers=auth("Bearer admin-token"),
        json={"id": "visual-course", "name": "Visual Course", "description": "Notes"},
    )
    assert created.status_code == 201, created.text
    pair_response = client.post(
        f"{UI}/pairs",
        headers=auth("Bearer token-a"),
        json={"course": "visual-course"},
    )
    assert pair_response.status_code == 201, pair_response.text
    pair_id = pair_response.json()["id"]
    ui_db = client.app.state.ui_extension_app.state.db
    conversation_id = "visual-conversation"
    message_id = "visual-answer"
    timestamp = now()
    with ui_db.connect(True) as connection:
        connection.execute(
            "INSERT INTO cmui_conversations(id,owner,course,lane,title,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (conversation_id, "user-a", "visual-course", "teach", "Visual", timestamp, timestamp),
        )
        connection.execute(
            "UPDATE cmui_pairs SET teach_conversation=? WHERE id=?",
            (conversation_id, pair_id),
        )
        connection.execute(
            "INSERT INTO cmui_messages(id,conversation,role,text,citations,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (
                "visual-question",
                conversation_id,
                "user",
                question_text,
                "[]",
                timestamp,
            ),
        )
        connection.execute(
            "INSERT INTO cmui_messages(id,conversation,role,text,citations,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (
                message_id,
                conversation_id,
                "assistant",
                "Fetch, decode, execute, write back.",
                "[]",
                timestamp,
            ),
        )
    return pair_id, message_id


def test_authenticated_visual_job_to_asset_and_cross_user_denial(client: TestClient) -> None:
    pair_id, message_id = seed_answer(client)
    created = client.post(
        f"{UI}/courses/visual-course/messages/{message_id}/visuals",
        headers=auth("Bearer token-a"),
        json={"request_id": "visual-request-0001", "pair_id": pair_id, "action": "diagram"},
    )
    assert created.status_code == 202, created.text
    job_id = created.json()["id"]

    completed = client.app.state.visual_service.run_once("test-worker")
    assert completed is not None and completed["status"] == "COMPLETED"
    status = client.get(f"{UI}/visual-jobs/{job_id}", headers=auth("Bearer token-a"))
    assert status.status_code == 200, status.text
    assert status.json()["status"] == "COMPLETED"
    assert len(status.json()["assets"]) == 1
    assert "frozen_input_json" not in status.json()
    assert "prompt_hash" not in status.json()

    asset = status.json()["assets"][0]
    content = client.get(UI + asset["content_url"], headers=auth("Bearer token-a"))
    assert content.status_code == 200
    assert content.headers["content-type"].startswith("image/svg+xml")
    assert content.content.startswith(b"<svg")

    assert (
        client.get(f"{UI}/visual-jobs/{job_id}", headers=auth("Bearer token-b")).status_code == 404
    )
    assert client.get(UI + asset["content_url"], headers=auth("Bearer token-b")).status_code == 404


def test_browser_cannot_select_workflow_provider_or_model(client: TestClient) -> None:
    pair_id, message_id = seed_answer(client)
    response = client.post(
        f"{UI}/courses/visual-course/messages/{message_id}/visuals",
        headers=auth("Bearer token-a"),
        json={
            "request_id": "visual-request-0002",
            "pair_id": pair_id,
            "action": "diagram",
            "workflow_id": "attacker-workflow",
            "provider_url": "https://attacker.invalid",
            "model": "attacker-model",
        },
    )
    assert response.status_code == 422
    with client.app.state.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM visual_jobs").fetchone()[0] == 0


def test_failed_visual_exposes_and_runs_a_deterministic_fallback(client: TestClient) -> None:
    pair_id, message_id = seed_answer(client, "Explain a gravitational lens")
    created = client.post(
        f"{UI}/courses/visual-course/messages/{message_id}/visuals",
        headers=auth("Bearer token-a"),
        json={"request_id": "visual-request-0003", "pair_id": pair_id, "action": "visual"},
    )
    assert created.status_code == 202, created.text
    job_id = created.json()["id"]
    client.app.state.visual_service.provider.set_mode(job_id, "invalid")
    failed = client.app.state.visual_service.run_once("test-worker")
    assert failed is not None and failed["status"] == "FAILED"
    projected = client.get(f"{UI}/visual-jobs/{job_id}", headers=auth("Bearer token-a"))
    assert projected.json()["fallback_available"] is True

    fallback = client.post(
        f"{UI}/visual-jobs/{job_id}/fallback",
        headers=auth("Bearer token-a"),
        json={"request_id": "visual-fallback-0001"},
    )
    assert fallback.status_code == 202, fallback.text
    completed = client.app.state.visual_service.run_once("test-worker")
    assert completed is not None and completed["renderer"] == "SVG"
