from pathlib import Path

from test_learning_workspace import client_at, join


def _workspace(client) -> dict[str, object]:
    client.headers["Authorization"] = "Bearer admin"
    created = client.post(
        "/api/courses", json={"id": "cs3481", "name": "CS3481"}
    )
    assert created.status_code == 201, created.text
    return join(client)


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

