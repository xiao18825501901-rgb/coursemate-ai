import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_document_previews import PNG_1X1
from test_learning_journey import setup_workspace
from test_learning_workspace import client_at, join

from app.config import Settings
from app.learning.models import ProblemSolutionOutput
from app.learning.provider import LearningProvider, ProviderImage
from app.learning.testing import fixture_output


def _workspace(client) -> dict[str, object]:
    client.headers["Authorization"] = "Bearer admin"
    created = client.post(
        "/api/courses", json={"id": "cs3481", "name": "CS3481"}
    )
    assert created.status_code == 201, created.text
    return join(client)


def _private_addition_node(client, workspace_id: str, title: str) -> dict[str, Any]:
    response = client.post(
        f"/api/learning/workspaces/{workspace_id}/nodes",
        json={
            "title": title,
            "description": "Combining two counts",
            "major": "CS",
            "kind": "ATOMIC",
            "items": [
                {
                    "item_id": "principle",
                    "requirement": "REQUIRED",
                    "objective": "Explain addition",
                    "acceptance": "Explain combining counts with an example",
                    "evidence_ids": [],
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_question_index_is_incremental_version_bound_and_owner_scoped(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace = _workspace(client)
        endpoint = f"/api/learning/workspaces/{workspace['id']}/documents"
        uploaded = client.post(
            endpoint,
            files={
                "file": (
                    "Tutorial 1.txt",
                    b"Tutorial 1\n1. What is 2 + 3?\n2. Explain the result.",
                    "text/plain",
                )
            },
        )
        assert uploaded.status_code == 202, uploaded.text
        document_id = uploaded.json()["document"]["id"]

        indexed = client.get(
            f"/api/learning/workspaces/{workspace['id']}/problem-index",
            params={"scope": "mine", "question_number": "1"},
        )
        assert indexed.status_code == 200, indexed.text
        assert indexed.json()["total"] == 1
        entry = indexed.json()["items"][0]
        assert entry["question_number"] == "1"
        assert entry["question_part"] is None
        assert entry["filename"] == "Tutorial 1.txt"
        assert "What is 2 + 3?" in entry["question_text"]

        with client.app.state.database.connect() as connection:
            version = connection.execute(
                "SELECT id,sha256 FROM document_versions WHERE document_id=?",
                (document_id,),
            ).fetchone()
            indexed_row = connection.execute(
                "SELECT document_version_id FROM problem_index_entries WHERE id=?",
                (entry["id"],),
            ).fetchone()
        assert entry["document_version_id"] == version["id"]
        assert entry["document_sha256"] == version["sha256"]
        assert indexed_row["document_version_id"] == version["id"]

        # Re-running additive migrations cannot duplicate imported questions.
        client.app.state.database.initialize()
        repeated = client.get(
            f"/api/learning/workspaces/{workspace['id']}/problem-index",
            params={"scope": "mine", "question_number": "1"},
        )
        assert repeated.json()["total"] == 1

        client.headers["Authorization"] = "Bearer b"
        other_workspace = join(client, "b")
        hidden = client.get(
            f"/api/learning/workspaces/{other_workspace['id']}/problem-index",
            params={"scope": "mine", "question_number": "1"},
        )
        assert hidden.status_code == 200, hidden.text
        assert hidden.json() == {"items": [], "total": 0}


def test_solution_and_bridge_persist_validated_revision_context(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        base = f"/api/learning/workspaces/{workspace['id']}"
        revision = client.get(base + "/state").json()["revision"]
        solved = client.post(
            base + "/solutions",
            json={
                "operation_id": "solve-normalized",
                "revision": revision,
                "question": "What is 2 + 3?",
                "node_ids": [node["id"]],
            },
        )
        assert solved.status_code == 200, solved.text
        solution = solved.json()
        assert solution["problem_revision"] == 1
        assert solution["solution_revision"] == 1
        assert solution["problem_revision_id"]
        assert solution["solution_revision_id"]
        link = solution["steps"][0]["knowledge_links"][0]
        assert link == {
            "id": link["id"],
            "resolution_status": "VALIDATED",
            "node_id": node["id"],
            "spec_version": 1,
            "item_id": "principle",
            "question_text": "Why do we add these counts?",
            "reason": "This step combines quantities.",
            "unresolved_reason": None,
        }

        bridged = client.post(
            base + "/bridges",
            json={
                "operation_id": "bridge-normalized",
                "revision": solution["revision"],
                "step_id": solution["steps"][0]["id"],
                "knowledge_link_id": link["id"],
            },
        )
        assert bridged.status_code == 200, bridged.text
        bridge = bridged.json()
        assert bridge["selected_question"] == link["question_text"]
        assert bridge["knowledge_link_id"] == link["id"]
        assert bridge["problem_revision_id"] == solution["problem_revision_id"]
        assert bridge["solution_revision_id"] == solution["solution_revision_id"]
        assert bridge["target_learning_session"] == bridge["learning_session_id"]
        assert bridge["return_problem_id"] == solution["problem_id"]
        assert bridge["return_step_id"] == solution["steps"][0]["id"]

        duplicate = client.post(
            base + "/bridges",
            json={
                "operation_id": "bridge-normalized-retry",
                "revision": bridge["revision"],
                "step_id": solution["steps"][0]["id"],
                "knowledge_link_id": link["id"],
            },
        )
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["id"] == bridge["id"]

        with client.app.state.database.connect() as connection:
            problem_revision = connection.execute(
                "SELECT * FROM problem_revisions WHERE id=?",
                (solution["problem_revision_id"],),
            ).fetchone()
            solution_revision = connection.execute(
                "SELECT * FROM solution_revisions WHERE id=?",
                (solution["solution_revision_id"],),
            ).fetchone()
            saved_link = connection.execute(
                "SELECT * FROM step_knowledge_links WHERE id=?", (link["id"],)
            ).fetchone()
            context = connection.execute(
                "SELECT * FROM learning_bridge_contexts WHERE bridge_id=?",
                (bridge["id"],),
            ).fetchone()
            run = connection.execute(
                "SELECT template_version,schema_version FROM learning_model_run_evidence "
                "WHERE workspace_id=? AND operation_id='solve-normalized'",
                (workspace["id"],),
            ).fetchone()
            bridge_count = connection.execute(
                "SELECT COUNT(*) FROM learning_bridges WHERE workspace_id=?",
                (workspace["id"],),
            ).fetchone()[0]
        assert problem_revision["validation_status"] == "VALIDATED"
        assert problem_revision["input_kind"] == "TEXT"
        assert solution_revision["validation_status"] == "VALIDATED"
        assert saved_link["resolution_status"] == "VALIDATED"
        assert context["validation_status"] == "VALIDATED"
        assert context["owner_user_id"] == "a"
        assert context["course_id"] == "cs3481"
        assert tuple(run) == ("problem-v3.2", "ProblemSolutionOutput:v2")
        assert bridge_count == 1

        # A forged cross-item binding must be rejected at the database boundary.
        with (
            client.app.state.database.connect() as connection,
            pytest.raises(sqlite3.IntegrityError),
        ):
            connection.execute(
                    "INSERT INTO step_knowledge_links("
                    "id,workspace_id,solution_revision_id,step_id,ordinal,"
                    "resolution_status,node_id,spec_version,item_id,question_text,reason) "
                    "VALUES(?,?,?,?,2,'VALIDATED',?,?,?,'Forged question','Forged reason')",
                    (
                        "forged-link",
                        workspace["id"],
                        solution["solution_revision_id"],
                        solution["steps"][0]["id"],
                        node["id"],
                        1,
                        "not-an-item",
                    ),
            )


def test_indexed_question_solve_uses_exact_authorized_source_version(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        base = f"/api/learning/workspaces/{workspace['id']}"
        uploaded = client.post(
            base + "/documents",
            files={
                "file": (
                    "Tutorial 1.txt",
                    b"Tutorial 1\n1. What is 2 + 3?\n2. Explain five.",
                    "text/plain",
                )
            },
        )
        assert uploaded.status_code == 202, uploaded.text
        index = client.get(
            base + "/problem-index",
            params={"scope": "mine", "question_number": "1"},
        ).json()["items"]
        assert len(index) == 1
        entry = index[0]
        revision = client.get(base + "/state").json()["revision"]

        solved = client.post(
            base + "/solutions",
            json={
                "operation_id": "solve-indexed",
                "revision": revision,
                "problem_index_entry_id": entry["id"],
                "node_ids": [node["id"]],
            },
        )
        assert solved.status_code == 200, solved.text
        solution = solved.json()
        assert solution["input_kind"] == "INDEXED"
        assert solution["problem_index_entry_id"] == entry["id"]
        assert solution["input_document_version_id"] == entry["document_version_id"]
        assert solution["question"] == entry["question_text"]
        with client.app.state.database.connect() as connection:
            saved = connection.execute(
                "SELECT * FROM problem_revisions WHERE id=?",
                (solution["problem_revision_id"],),
            ).fetchone()
        assert saved["input_kind"] == "INDEXED"
        assert saved["problem_index_entry_id"] == entry["id"]
        assert saved["input_document_version_id"] == entry["document_version_id"]
        assert json.loads(saved["source_locator_json"])["question_number"] == "1"

        client.headers["Authorization"] = "Bearer b"
        other = join(client, "b")
        other_node = _private_addition_node(client, str(other["id"]), "B Addition")
        other_revision = client.get(
            f"/api/learning/workspaces/{other['id']}/state"
        ).json()["revision"]
        denied = client.post(
            f"/api/learning/workspaces/{other['id']}/solutions",
            json={
                "operation_id": "cross-user-index",
                "revision": other_revision,
                "problem_index_entry_id": entry["id"],
                "node_ids": [other_node["id"]],
            },
        )
        assert denied.status_code == 404
        assert denied.json()["error"]["code"] == "PROBLEM_INDEX_NOT_FOUND"


def test_image_question_is_private_version_bound_and_never_uses_a_public_url(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        base = f"/api/learning/workspaces/{workspace['id']}"
        uploaded = client.post(
            base + "/documents",
            files={"file": ("question.png", PNG_1X1, "image/png")},
        )
        assert uploaded.status_code == 202, uploaded.text
        document_id = uploaded.json()["document"]["id"]
        metadata = client.get(f"/api/learning/documents/{document_id}").json()

        captured: dict[str, object] = {}
        calls = 0
        original = client.app.state.learning.provider.generate

        def capture(*args, **kwargs):
            nonlocal calls
            calls += 1
            captured.update(kwargs)
            return original(*args, **kwargs)

        client.app.state.learning.provider.generate = capture
        revision = client.get(base + "/state").json()["revision"]
        solved = client.post(
            base + "/solutions",
            json={
                "operation_id": "solve-image",
                "revision": revision,
                "question": "Please solve the question in this image.",
                "transcription_hint": "What is 2 + 3?",
                "image_document_version_id": metadata["version_id"],
                "node_ids": [node["id"]],
            },
        )
        assert solved.status_code == 200, solved.text
        solution = solved.json()
        assert solution["input_kind"] == "IMAGE"
        assert solution["input_document_version_id"] == metadata["version_id"]
        assert solution["question_transcription"] == "[FAKE TEST FIXTURE] What is 2 + 3?"
        assert solution["visual_uncertainties"] == [
            "[FAKE TEST FIXTURE] Visual correctness was not evaluated."
        ]
        images = captured["images"]
        assert len(images) == 1
        assert images[0].content == PNG_1X1
        assert images[0].media_type == "image/png"
        assert images[0].source_version_id == metadata["version_id"]
        assert "http" not in json.dumps(solution).lower()

        with client.app.state.database.connect() as connection:
            saved = connection.execute(
                "SELECT * FROM problem_revisions WHERE id=?",
                (solution["problem_revision_id"],),
            ).fetchone()
        assert saved["input_kind"] == "IMAGE"
        assert saved["input_source_sha256"] == metadata["version"]
        assert saved["question_transcription"] == solution["question_transcription"]

        client.headers["Authorization"] = "Bearer b"
        other = join(client, "b")
        other_node = _private_addition_node(client, str(other["id"]), "B Addition")
        other_revision = client.get(
            f"/api/learning/workspaces/{other['id']}/state"
        ).json()["revision"]
        denied = client.post(
            f"/api/learning/workspaces/{other['id']}/solutions",
            json={
                "operation_id": "cross-user-image",
                "revision": other_revision,
                "question": "Solve this image.",
                "image_document_version_id": metadata["version_id"],
                "node_ids": [other_node["id"]],
            },
        )
        assert denied.status_code == 404
        assert denied.json()["error"]["code"] == "PROBLEM_IMAGE_NOT_FOUND"
        assert calls == 1

        client.headers["Authorization"] = "Bearer a"
        with client.app.state.database.connect() as connection:
            stored_path = connection.execute(
                "SELECT stored_path FROM document_versions WHERE id=?",
                (metadata["version_id"],),
            ).fetchone()[0]
        Path(stored_path).unlink()
        current_revision = client.get(base + "/state").json()["revision"]
        unavailable = client.post(
            base + "/solutions",
            json={
                "operation_id": "missing-image-source",
                "revision": current_revision,
                "question": "Solve this image.",
                "image_document_version_id": metadata["version_id"],
                "node_ids": [node["id"]],
            },
        )
        assert unavailable.status_code == 410
        assert unavailable.json()["error"]["code"] == "SOURCE_UNAVAILABLE"
        assert calls == 1


def test_unresolved_knowledge_link_is_explicit_and_cannot_open_a_bridge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unresolved(schema: str, context: dict[str, Any]) -> dict[str, Any]:
        output = fixture_output(schema, context)
        link = output["steps"][0]["knowledge_links"][0]
        link.update(
            resolution_status="UNRESOLVED",
            node_id=None,
            spec_version=None,
            item_id=None,
            unresolved_reason="No authorized atomic node can be bound reliably.",
        )
        return output

    monkeypatch.setattr("app.learning.testing.fixture_output", unresolved)
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        base = f"/api/learning/workspaces/{workspace['id']}"
        revision = client.get(base + "/state").json()["revision"]
        solved = client.post(
            base + "/solutions",
            json={
                "operation_id": "solve-unresolved",
                "revision": revision,
                "question": "What is 2 + 3?",
                "node_ids": [node["id"]],
            },
        )
        assert solved.status_code == 200, solved.text
        solution = solved.json()
        link = solution["steps"][0]["knowledge_links"][0]
        assert link["resolution_status"] == "UNRESOLVED"
        assert link["node_id"] is None
        assert link["item_id"] is None
        with client.app.state.database.connect() as connection:
            saved = connection.execute(
                "SELECT resolution_status,node_id,item_id,unresolved_reason "
                "FROM step_knowledge_links WHERE id=?",
                (link["id"],),
            ).fetchone()
        assert tuple(saved) == (
            "UNRESOLVED",
            None,
            None,
            "No authorized atomic node can be bound reliably.",
        )

        bridged = client.post(
            base + "/bridges",
            json={
                "operation_id": "bridge-unresolved",
                "revision": solution["revision"],
                "step_id": solution["steps"][0]["id"],
                "knowledge_link_id": link["id"],
            },
        )
        assert bridged.status_code == 422
        assert bridged.json()["error"]["code"] == "KNOWLEDGE_LINK_UNRESOLVED"


def test_responses_multimodal_payload_uses_private_data_uri_only() -> None:
    context = {
        "input_kind": "IMAGE",
        "question": "Solve this image.",
        "transcription_hint": "What is 2 + 3?",
        "nodes": [
            {
                "id": "addition",
                "spec_version": 1,
                "items": [{"item_id": "principle", "requirement": "REQUIRED"}],
            }
        ],
    }
    output = ProblemSolutionOutput.model_validate(
        fixture_output("ProblemSolutionOutput", context)
    )
    captured: dict[str, Any] = {}

    class Responses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                id="response-fixture",
                usage=SimpleNamespace(input_tokens=12, output_tokens=34),
                status="completed",
                output_text=output.model_dump_json(),
            )

    provider = LearningProvider(
        Settings(
            app_env="development",
            rag_provider_mode="openai",
            v3_enabled=True,
            v3_model_api_key="test-only-key",
            v3_model_base_url=(
                "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
            ),
        )
    )
    provider.client = SimpleNamespace(responses=Responses())
    image = ProviderImage(
        media_type="image/png",
        content=PNG_1X1,
        sha256=hashlib.sha256(PNG_1X1).hexdigest(),
        source_version_id="private-image-v1",
    )

    parsed, run = provider.generate(
        ProblemSolutionOutput,
        instructions="trusted problem fixture",
        context=context,
        role="problem",
        template_version="problem-v3.2",
        schema_version="ProblemSolutionOutput:v2",
        images=[image],
    )

    assert parsed == output
    assert run["protocol"] == "responses"
    assert captured["store"] is False
    assert captured["tools"] == []
    message = captured["input"][0]
    serialized = message["content"][0]["text"]
    image_url = message["content"][1]["image_url"]
    assert json.loads(serialized)["authorized_images"] == [
        {
            "source_version_id": "private-image-v1",
            "media_type": "image/png",
            "sha256": image.sha256,
            "byte_size": len(PNG_1X1),
        }
    ]
    assert "base64" not in serialized
    assert image_url.startswith("data:image/png;base64,")
    assert "http://" not in image_url and "https://" not in image_url
