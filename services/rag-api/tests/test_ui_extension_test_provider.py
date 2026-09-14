"""The labelled `test` provider mode completes runs without a billable model.

The browser acceptance server selects it via `CMUI_PROVIDER_MODE=test`; this
suite proves the same selection path in-process: settings validation keeps the
mode out of production, and the mounted extension completes problem runs with
server-derived step anchors, so the browser suite's step/bridge assertions are
backed by a deterministic provider contract.
"""

from __future__ import annotations

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
    "Bearer admin-token": "user-admin",
}


class FakeAuthVerifier:
    def authenticate(self, request: Request) -> str | None:
        return SUBJECTS.get(request.headers.get("authorization", ""))


class FakeEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        admin_user_ids="user-admin",
        app_env="test",
        v3_enabled=True,
        ui_extension_enabled=True,
        rag_provider_mode="deterministic",
        ui_web_dir=tmp_path / "no-web-build",
    )


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # The exact variable the browser server sets; must select the TestProvider.
    monkeypatch.setenv("CMUI_PROVIDER_MODE", "test")
    application = create_app(
        settings=make_settings(tmp_path),
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
    )
    with TestClient(application) as test_client:
        yield test_client


def wait_terminal(client: TestClient, run_id: str, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = client.get(f"{UI}/runs/{run_id}", headers={"Authorization": "Bearer token-a"}).json()
        if row["status"] in {"completed", "failed", "cancelled"}:
            return row
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} did not finish in {timeout}s")


def test_config_reports_the_test_provider(client: TestClient) -> None:
    body = client.get(f"{UI}/config").json()
    assert body["provider_mode"] == "test"
    assert body["integration_mode"] == "integrated"


def test_test_provider_completes_problem_and_teach_runs(client: TestClient) -> None:
    created = client.post(
        "/api/courses",
        headers={"Authorization": "Bearer admin-token"},
        json={"id": "cs3481", "name": "Fundamentals of Data Science", "description": "Notes"},
    )
    assert created.status_code == 201, created.text

    for lane, text, expected in (
        ("problem", "怎么判断核心点？", ["审题与条件整理", "计算核心点"]),
        ("teach", "请解释核心点", "从定义出发"),
    ):
        conversation = client.post(
            f"{UI}/conversations",
            headers={"Authorization": "Bearer token-a"},
            json={"course": "cs3481", "lane": lane},
        )
        assert conversation.status_code == 201, conversation.text
        started = client.post(
            f"{UI}/conversations/{conversation.json()['id']}/runs",
            headers={"Authorization": "Bearer token-a"},
            json={"text": text, "request_id": f"test-provider-{lane}-000001"},
        )
        assert started.status_code == 202, started.text
        row = wait_terminal(client, started.json()["id"])
        assert row["status"] == "completed"
        messages = client.get(
            f"{UI}/conversations/{conversation.json()['id']}",
            headers={"Authorization": "Bearer token-a"},
        ).json()["messages"]
        assistant = next(message for message in messages if message["role"] == "assistant")
        if lane == "problem":
            assert [step["title"] for step in assistant["steps"]] == expected
        else:
            assert expected in assistant["text"]


def test_test_provider_mode_is_forbidden_in_production() -> None:
    from app.cm_update.config import Settings as UiSettings

    ui = UiSettings()
    ui.environment = "production"
    ui.auth_mode = "injected"
    ui.provider_mode = "test"
    with pytest.raises(ValueError, match="Test provider is forbidden"):
        ui.validate()
