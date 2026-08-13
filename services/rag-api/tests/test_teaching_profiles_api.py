from collections.abc import Iterator
from pathlib import Path

from fastapi import Request
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


class FakeEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


class FakeAnswerProvider:
    def __init__(self) -> None:
        self.instructions: list[str] = []

    def stream_answer(self, *, question: str, context: str, instructions: str) -> Iterator[str]:
        self.instructions.append(instructions)
        yield "A teaching answer."


class FakeAuthVerifier:
    def authenticate(self, request: Request) -> str | None:
        return {
            "Bearer user-a": "user-a",
            "Bearer user-b": "user-b",
        }.get(request.headers.get("authorization", ""))


def client_for(tmp_path: Path, provider: FakeAnswerProvider) -> TestClient:
    return TestClient(
        create_app(
            settings=Settings(
                database_path=tmp_path / "rag.sqlite3",
                upload_dir=tmp_path / "uploads",
            ),
            embedding_provider=FakeEmbeddingProvider(),
            answer_provider=provider,
            auth_verifier=FakeAuthVerifier(),
        )
    )


def profile_payload(goal: str) -> dict[str, object]:
    return {
        "language": "zh-CN",
        "studentLevel": "beginner",
        "learningGoal": goal,
        "teachingStyles": ["intuition-first", "worked-examples"],
        "answerDepth": "detailed",
        "examplePreference": "worked",
        "exercisePolicy": "always",
        "examOrientation": True,
        "citationPreference": "detailed",
        "mathDetailLevel": "full",
        "terminologyStyle": "bilingual",
        "customRequirements": "先讲 Why，再讲公式。",
    }


def test_prompt_builder_returns_typed_editable_preview(tmp_path: Path) -> None:
    provider = FakeAnswerProvider()
    with client_for(tmp_path, provider) as client:
        response = client.post(
            "/api/teaching-profiles/preview",
            json={"requirement": "我基础不好，要准备考试，请详细讲例题。"},
            headers={"Authorization": "Bearer user-a"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["language"] == "zh-CN"
    assert body["studentLevel"] == "beginner"
    assert body["examOrientation"] is True
    assert body["answerDepth"] == "detailed"
    assert "worked-examples" in body["teachingStyles"]
    assert "Platform" not in body["generatedPrompt"]


def test_profiles_are_versioned_and_owner_scoped(tmp_path: Path) -> None:
    provider = FakeAnswerProvider()
    with client_for(tmp_path, provider) as client:
        created = client.post(
            "/api/courses",
            json={"id": "private-course", "name": "Private Course"},
            headers={"Authorization": "Bearer user-a"},
        )
        first = client.post(
            "/api/courses/private-course/teaching-profiles",
            json=profile_payload("Pass the midterm"),
            headers={"Authorization": "Bearer user-a"},
        )
        second = client.post(
            "/api/courses/private-course/teaching-profiles",
            json=profile_payload("Master the final"),
            headers={"Authorization": "Bearer user-a"},
        )
        hidden = client.get(
            "/api/courses/private-course/teaching-profiles",
            headers={"Authorization": "Bearer user-b"},
        )

    assert created.status_code == 201
    assert first.json()["version"] == 1
    assert second.json()["version"] == 2
    assert hidden.status_code == 404


def test_conversation_keeps_the_profile_version_it_started_with(tmp_path: Path) -> None:
    provider = FakeAnswerProvider()
    with client_for(tmp_path, provider) as client:
        headers = {"Authorization": "Bearer user-a"}
        client.post(
            "/api/courses",
            json={"id": "private-course", "name": "Private"},
            headers=headers,
        )
        client.post(
            "/api/courses/private-course/teaching-profiles",
            json=profile_payload("Version one goal"),
            headers=headers,
        )
        first = client.post(
            "/api/qa/chat",
            json={"courseId": "private-course", "question": "Hello"},
            headers=headers,
        )
        conversation_id = first.text.split('"conversationId":"', 1)[1].split('"', 1)[0]
        client.post(
            "/api/courses/private-course/teaching-profiles",
            json=profile_payload("Version two goal"),
            headers=headers,
        )
        client.post(
            "/api/qa/chat",
            json={
                "courseId": "private-course",
                "conversationId": conversation_id,
                "question": "Hello again",
            },
            headers=headers,
        )

    assert "Version one goal" in provider.instructions[0]
    assert "Version one goal" in provider.instructions[1]
    assert "Version two goal" not in provider.instructions[1]


def test_owner_can_restore_historical_profile_as_new_audited_version(tmp_path: Path) -> None:
    provider = FakeAnswerProvider()
    with client_for(tmp_path, provider) as client:
        headers = {"Authorization": "Bearer user-a"}
        client.post(
            "/api/courses",
            json={"id": "private-course", "name": "Private"},
            headers=headers,
        )
        client.post(
            "/api/courses/private-course/teaching-profiles",
            json=profile_payload("Original goal"),
            headers=headers,
        )
        client.post(
            "/api/courses/private-course/teaching-profiles",
            json=profile_payload("Replacement goal"),
            headers=headers,
        )
        restored = client.post(
            "/api/courses/private-course/teaching-profiles/1/restore",
            headers=headers,
        )
        versions = client.get(
            "/api/courses/private-course/teaching-profiles",
            headers=headers,
        )
        foreign = client.post(
            "/api/courses/private-course/teaching-profiles/1/restore",
            headers={"Authorization": "Bearer user-b"},
        )
        missing = client.post(
            "/api/courses/private-course/teaching-profiles/99/restore",
            headers=headers,
        )

    assert restored.status_code == 201
    assert restored.json()["version"] == 3
    assert restored.json()["learningGoal"] == "Original goal"
    assert [item["version"] for item in versions.json()["items"]] == [3, 2, 1]
    assert foreign.status_code == 404
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "PROFILE_NOT_FOUND"
