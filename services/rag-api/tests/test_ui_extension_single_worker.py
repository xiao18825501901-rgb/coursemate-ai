"""Single-worker safety for the generation runner, enforced by real constraints.

The runner keeps jobs in process memory, so cross-process coordination can only go
through the database. These tests run TWO mounted applications on the same UI
database and prove:

- a second process starting up reclaims only runs whose lease proves their owner
  died, and never kills a live sibling's run;
- cancellation written from another process stops the generator before it can
  write a "completed" assistant message;
- the final write is a conditional transition, so a lost race cannot overwrite a
  cancelled/failed state or insert a message afterwards;
- failed runs never retry the paid provider.
"""

from __future__ import annotations

import asyncio
import time
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
    def authenticate(self, request: Request) -> str | None:
        return SUBJECTS.get(request.headers.get("authorization", ""))


class FakeEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


class GatedProvider:
    """Yields the contract vocabulary once, then blocks until the test releases it.

    The event is created inside the application's own event loop and released
    through `call_soon_threadsafe`, because `Event.set()` from the test thread is
    not guaranteed to wake a coroutine scheduled on the portal loop.
    """

    def __init__(self) -> None:
        self._gate = None
        self.calls = 0

    async def generate(self, course, text, profile, sources, history, lane, bridge=None, **kwargs):
        self.calls += 1
        if self._gate is None:
            self._gate = asyncio.Event()
        yield {"kind": "status", "status": "planning", "label": "gated"}
        yield {"kind": "prompt", "text": "本地测试 Prompt"}
        yield {"kind": "status", "status": "generating", "label": "gated"}
        yield {"kind": "delta", "text": "正在生成…"}
        await self._gate.wait()
        yield {"kind": "delta", "text": " 已完成后半段。"}
        yield {"kind": "usage", "stage": "answer", "value": {"output_tokens": 2}}

    def release(self) -> None:
        assert self._gate is not None, "release() before the generator started"
        self._gate._loop.call_soon_threadsafe(self._gate.set)


class FailingProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, course, text, profile, sources, history, lane, bridge=None, **kwargs):
        self.calls += 1
        from app.cm_update.provider import ProviderError

        yield {"kind": "status", "status": "planning", "label": "boom"}
        raise ProviderError("TEST_PROVIDER_FAILURE")


def make_app(tmp_path: Path, provider: object) -> TestClient:
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
        ui_provider=provider,
    )
    return TestClient(application)


def seed_course(client: TestClient) -> None:
    from campus_actor_fixture import authorize_synthetic_campus_users
    authorize_synthetic_campus_users(client, 'user-a')
    created = client.post(
        "/api/courses",
        headers={"Authorization": "Bearer admin-token"},
        json={"id": "cs3481", "name": "Fundamentals of Data Science", "description": "Notes"},
    )
    assert created.status_code == 201, created.text


def start_run(client: TestClient, request_id: str) -> str:
    conversation = client.post(
        f"{UI}/conversations",
        headers={"Authorization": "Bearer token-a"},
        json={"course": "cs3481", "lane": "teach"},
    )
    assert conversation.status_code == 201, conversation.text
    started = client.post(
        f"{UI}/conversations/{conversation.json()['id']}/runs",
        headers={"Authorization": "Bearer token-a"},
        json={"text": "请讲解聚类", "request_id": request_id},
    )
    assert started.status_code == 202, started.text
    return started.json()["id"]


def ui_db(client: TestClient):
    return client.app.state.ui_extension_app.state.db


def run_row(client: TestClient, run_id: str) -> dict:
    return ui_db(client).one("SELECT * FROM cmui_runs WHERE id=?", (run_id,))


@pytest.fixture
def tmp_env(tmp_path: Path, monkeypatch) -> Iterator[Path]:
    monkeypatch.setenv("CMUI_DATA_DIR", str(tmp_path / "ui-data"))
    monkeypatch.setenv("CMUI_RUN_LEASE_GRACE", "120")
    return tmp_path


def test_sibling_startup_does_not_kill_a_live_run(tmp_env: Path) -> None:
    provider = GatedProvider()
    first = make_app(tmp_env, provider)
    with first:
        seed_course(first)
        run_id = start_run(first, "lease-live-000001")
        assert run_row(first, run_id)["status"] in {"queued", "planning", "generating"}

        # A second process starts against the same UI database.
        second = make_app(tmp_env, GatedProvider())
        with second:
            row = run_row(first, run_id)
            assert row["status"] in {"queued", "planning", "generating"}, row
            assert row["error"] is None

        # Release the provider; the first worker finishes normally.
        provider.release()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if run_row(first, run_id)["status"] == "completed":
                break
            time.sleep(0.1)
        row = run_row(first, run_id)
        assert row["status"] == "completed"
        messages = ui_db(first).all(
            "SELECT * FROM cmui_messages WHERE run=?", (run_id,)
        )
        assert [message["role"] for message in messages].count("assistant") == 1
    assert provider.calls == 1


def test_startup_reclaims_only_runs_whose_lease_expired(tmp_env: Path) -> None:
    provider = GatedProvider()
    first = make_app(tmp_env, provider)
    with first:
        seed_course(first)
        run_id = start_run(first, "lease-orphan-000002")
        # Simulate the owner's death: its heartbeat is far in the past.
        ui_db(first).execute(
            "UPDATE cmui_runs SET lease_heartbeat='0' WHERE id=?", (run_id,)
        )

        second = make_app(tmp_env, GatedProvider())
        with second:
            row = run_row(first, run_id)
            assert row["status"] == "failed"
            assert row["error"] == "SERVER_RESTARTED"

        # The dead worker's generator later resumes (test seam) and must NOT be
        # able to overwrite the reaped state or insert a message.
        provider.release()
        time.sleep(0.6)
        row = run_row(first, run_id)
        assert row["status"] == "failed"
        assistant = ui_db(first).all(
            "SELECT * FROM cmui_messages WHERE run=? AND role='assistant'", (run_id,)
        )
        assert assistant == []
    assert provider.calls == 1


def test_cancel_from_another_process_wins_the_race(tmp_env: Path) -> None:
    provider = GatedProvider()
    first = make_app(tmp_env, provider)
    with first:
        seed_course(first)
        run_id = start_run(first, "lease-cancel-000003")
        assert run_row(first, run_id)["status"] != "completed"

        second = make_app(tmp_env, GatedProvider())
        with second:
            cancelled = second.post(
                f"{UI}/runs/{run_id}/cancel", headers={"Authorization": "Bearer token-a"}
            )
            assert cancelled.status_code == 200, cancelled.text

        # The generating process sees the terminal state at its next checkpoint
        # and stops; releasing the gate must not produce a completed message.
        provider.release()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if run_row(first, run_id)["status"] in {"cancelled", "failed"}:
                break
            time.sleep(0.1)
        row = run_row(first, run_id)
        assert row["status"] == "cancelled"
        assistant = ui_db(first).all(
            "SELECT * FROM cmui_messages WHERE run=? AND role='assistant'", (run_id,)
        )
        assert assistant == []
    assert provider.calls == 1


def test_failed_run_never_retries_the_provider(tmp_env: Path) -> None:
    provider = FailingProvider()
    client = make_app(tmp_env, provider)
    with client:
        seed_course(client)
        run_id = start_run(client, "lease-fail-000004")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if run_row(client, run_id)["status"] == "failed":
                break
            time.sleep(0.1)
        row = run_row(client, run_id)
        assert row["status"] == "failed"
        assert row["error"] == "TEST_PROVIDER_FAILURE"
    assert provider.calls == 1
