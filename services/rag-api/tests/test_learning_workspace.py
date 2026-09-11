from pathlib import Path

from fastapi import Request
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


class Identity:
    def authenticate(self, request: Request) -> str | None:
        return {"Bearer a": "a", "Bearer b": "b", "Bearer admin": "admin"}.get(
            request.headers.get("authorization", "")
        )


def client_at(path: Path) -> TestClient:
    app = create_app(
        settings=Settings(
            database_path=path / "rag.db",
            upload_dir=path / "uploads",
            app_env="test",
            rag_provider_mode="deterministic",
            admin_user_ids="admin",
            v3_enabled=True,
        ),
        auth_verifier=Identity(),
    )
    return TestClient(app)


def join(client: TestClient, who: str = "a") -> dict:
    client.headers["Authorization"] = "Bearer " + who
    response = client.post("/api/learning/workspaces", json={"course_id": "cs3481"})
    assert response.status_code == 200, response.text
    return response.json()


def test_private_workspace_files_are_not_official_or_admin_readable(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        client.headers["Authorization"] = "Bearer admin"
        assert (
            client.post("/api/courses", json={"id": "cs3481", "name": "CS3481"}).status_code == 201
        )
        workspace = join(client)
        assert join(client)["id"] == workspace["id"]
        endpoint = f"/api/learning/workspaces/{workspace['id']}/documents"
        upload = client.post(
            endpoint, files={"file": ("我的资料.txt", "matrix 我的例子".encode(), "text/plain")}
        )
        assert upload.status_code == 202, upload.text
        document = upload.json()["document"]
        url = f"/api/learning/documents/{document['id']}/content"
        result = client.get(url)
        assert result.status_code == 200
        assert result.content == "matrix 我的例子".encode()
        assert "no-store" in result.headers["cache-control"]
        assert client.head(url).status_code == 200
        assert client.get(url, headers={"Range": "bytes=0-2"}).status_code == 206
        assert len(client.get(endpoint).json()["data"]) == 1
        assert client.get("/api/courses/cs3481/documents").json()["total"] == 0
        for who in ("b", "admin"):
            client.headers["Authorization"] = "Bearer " + who
            for verb in (client.get, client.head):
                assert verb(url).status_code == 404
            assert client.get(url, headers={"Range": "bytes=0-2"}).status_code == 404
            assert client.get(endpoint).status_code == 404
            assert client.get(f"/api/courses/{document['courseId']}/documents").status_code == 404
        client.headers.pop("Authorization")
        assert client.get(url).status_code == 401


def test_v3_reserves_hidden_workspace_course_id_namespace(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        client.headers["Authorization"] = "Bearer a"
        response = client.post(
            "/api/courses",
            json={"id": "ws-forged-private-corpus", "name": "Not a workspace"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "RESERVED_COURSE_ID"


def test_workspace_is_durable_and_missing_original_is_explicit(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        client.headers["Authorization"] = "Bearer admin"
        client.post("/api/courses", json={"id": "cs3481", "name": "CS3481"})
        workspace = join(client)
    with client_at(tmp_path) as restarted:
        assert join(restarted)["id"] == workspace["id"]
        with restarted.app.state.database.connect() as db:
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_feature_defaults_off(tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(
            database_path=tmp_path / "x.db",
            upload_dir=tmp_path / "u",
            app_env="test",
            rag_provider_mode="deterministic",
        ),
        auth_verifier=Identity(),
    )
    with TestClient(app) as client:
        created = client.post(
            "/api/courses",
            headers={"Authorization": "Bearer a"},
            json={"id": "private-course", "name": "Private"},
        )
        assert created.status_code == 201, created.text
        legacy_namespace = client.post(
            "/api/courses",
            headers={"Authorization": "Bearer a"},
            json={"id": "ws-existing-v2-course", "name": "Existing V2 course"},
        )
        assert legacy_namespace.status_code == 201, legacy_namespace.text
        listed = client.get(
            "/api/courses",
            headers={"Authorization": "Bearer a"},
        )
        assert listed.status_code == 200, listed.text
        assert sorted(course["id"] for course in listed.json()["items"]) == [
            "private-course",
            "ws-existing-v2-course",
        ]
        csv_upload = client.post(
            "/api/courses/private-course/documents",
            headers={"Authorization": "Bearer a"},
            files={"file": ("v3-only.csv", b"name,value\na,1\n", "text/csv")},
        )
        assert csv_upload.status_code == 400
        assert csv_upload.json()["error"]["code"] == "UNSUPPORTED_EXTENSION"
        assert (
            client.post(
                "/api/learning/workspaces",
                headers={"Authorization": "Bearer a"},
                json={"course_id": "cs3481"},
            ).status_code
            == 404
        )
        with app.state.database.connect() as connection:
            versions = [
                row[0]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )
            ]
            workspace_table = connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'learning_workspaces'"
            ).fetchone()
        assert versions == list(range(1, 11))
        assert workspace_table is None
