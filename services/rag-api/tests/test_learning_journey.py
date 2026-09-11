from pathlib import Path

from test_learning_workspace import client_at, join


def setup_workspace(client):
    client.headers["Authorization"] = "Bearer admin"
    client.post("/api/courses", json={"id": "cs3481", "name": "CS3481"})
    workspace = join(client)
    node = client.post(
        f"/api/learning/workspaces/{workspace['id']}/nodes",
        json={
            "title": "Addition",
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
                },
                {
                    "item_id": "extension",
                    "requirement": "OPTIONAL",
                    "objective": "Explore negatives",
                    "acceptance": "An optional example",
                    "evidence_ids": [],
                },
            ],
        },
    )
    assert node.status_code == 200, node.text
    return workspace, node.json()


def test_problem_bridge_teaching_return_survives_restart(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        base = f"/api/learning/workspaces/{workspace['id']}"
        state = client.get(base + "/state").json()
        request = {
            "operation_id": "solve-1",
            "revision": state["revision"],
            "question": "What is 2 + 3?",
            "node_ids": [node["id"]],
        }
        response = client.post(base + "/solutions", json=request)
        assert response.status_code == 200, response.text
        solution = response.json()
        assert "5" in solution["exam_answer"]
        assert solution["assistance"] == "ANSWER_EXPOSED"
        assert client.post(base + "/solutions", json=request).json() == solution
        step = solution["steps"][0]
        bridge_request = {
            "operation_id": "bridge-1",
            "revision": solution["revision"],
            "step_id": step["id"],
            "node_id": node["id"],
        }
        bridge = client.post(base + "/bridges", json=bridge_request).json()
        assert bridge["problem_snapshot"]["question"] == "What is 2 + 3?"
        assert bridge["solution_version"] == 1
        result = client.post(
            base + "/units",
            json={
                "operation_id": "teach-1",
                "revision": bridge["revision"],
                "node_id": node["id"],
                "bridge_id": bridge["id"],
            },
        )
        assert result.status_code == 200, result.text
        unit = result.json()
        assert unit["progress"] == "LEARNED"
        assert unit["grade"] == "NOT_ASSESSED"
        state = client.get(base + "/state").json()
        assert state["bridges"][0]["status"] == "READY_TO_RETURN"
        back = client.post(
            base + f"/bridges/{bridge['id']}/return",
            json={"operation_id": "return-1", "revision": state["revision"]},
        )
        assert back.status_code == 200, back.text
        assert back.json()["return_anchor"] == f"step-{step['id']}"
    with client_at(tmp_path) as restarted:
        restarted.headers["Authorization"] = "Bearer a"
        state = restarted.get(base + "/state").json()
        assert state["cursor"]["step_id"] == step["id"]
        assert state["units"][0]["id"] == unit["id"]
        assert state["nodes"][0]["progress"] == "LEARNED"
        for who in ("b", "admin"):
            restarted.headers["Authorization"] = "Bearer " + who
            assert restarted.get(base + "/state").status_code == 404


def test_stale_revision_and_foreign_node_are_rejected(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        base = f"/api/learning/workspaces/{workspace['id']}"
        state = client.get(base + "/state").json()
        request = {
            "operation_id": "solve",
            "revision": state["revision"],
            "question": "2+3",
            "node_ids": ["invented"],
        }
        assert client.post(base + "/solutions", json=request).status_code in (404, 422)
        state = client.get(base + "/state").json()
        request.update(operation_id="valid", revision=state["revision"], node_ids=[node["id"]])
        assert client.post(base + "/solutions", json=request).status_code == 200
        request["operation_id"] = "stale"
        assert client.post(base + "/solutions", json=request).status_code == 409


def test_model_result_cannot_overwrite_a_newer_workspace_revision(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        base = f"/api/learning/workspaces/{workspace['id']}"
        state = client.get(base + "/state").json()
        learning = client.app.state.learning
        original_generate = learning.provider.generate

        def generate_after_concurrent_change(*args, **kwargs):
            with learning.db.connect() as connection:
                connection.execute(
                    "UPDATE learning_workspaces SET revision=revision+1 WHERE id=?",
                    (workspace["id"],),
                )
            return original_generate(*args, **kwargs)

        learning.provider.generate = generate_after_concurrent_change
        response = client.post(
            base + "/solutions",
            json={
                "operation_id": "stale-model-result",
                "revision": state["revision"],
                "question": "2+3",
                "node_ids": [node["id"]],
            },
        )

        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "REVISION_CONFLICT"
        with learning.db.connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM learning_solutions").fetchone()[0] == 0
            operation = connection.execute(
                "SELECT status FROM learning_operations WHERE workspace_id=? AND id=?",
                (workspace["id"], "stale-model-result"),
            ).fetchone()
        assert operation["status"] == "FAILED"


def test_return_operation_identity_includes_bridge_path(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        base = f"/api/learning/workspaces/{workspace['id']}"

        def solve_and_bridge(index: int, revision: int) -> dict:
            solution = client.post(
                base + "/solutions",
                json={
                    "operation_id": f"solve-{index}",
                    "revision": revision,
                    "question": "2+3",
                    "node_ids": [node["id"]],
                },
            ).json()
            return client.post(
                base + "/bridges",
                json={
                    "operation_id": f"bridge-{index}",
                    "revision": solution["revision"],
                    "step_id": solution["steps"][0]["id"],
                    "node_id": node["id"],
                },
            ).json()

        revision = client.get(base + "/state").json()["revision"]
        first = solve_and_bridge(1, revision)
        second = solve_and_bridge(2, first["revision"])
        payload = {
            "operation_id": "return-same-id",
            "revision": second["revision"],
        }
        returned = client.post(
            base + f"/bridges/{first['id']}/return",
            json=payload,
        )
        assert returned.status_code == 200, returned.text

        replayed_on_other_path = client.post(
            base + f"/bridges/{second['id']}/return",
            json=payload,
        )
        assert replayed_on_other_path.status_code == 409
        assert replayed_on_other_path.json()["error"]["code"] == "OPERATION_REUSED"
