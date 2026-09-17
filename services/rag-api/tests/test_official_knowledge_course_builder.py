"""M6D4 course builder: bulk, resumable, one-final-tree semantics.

All deterministic/fake provider; zero live model calls. Reuses the same
official-corpus fixture as the M6D1 builder tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import ApiError
from app.main import create_app
from app.models import (
    OfficialKnowledgeCourseBuild,
    OfficialKnowledgeCoursePlan,
)
from app.services.official_knowledge_course_builder import OfficialKnowledgeCourseBuilder
from app.services.official_knowledge_draft_builder import OfficialKnowledgeDraftBuilder

GENERATE = "/api/admin/courses/{course_id}/official-knowledge-drafts/generate"


class FakeEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


class FakeAuthVerifier:
    def authenticate(self, request: Request) -> str | None:
        return {
            "Bearer owner": "owner",
            "Bearer admin-author": "admin-author",
            "Bearer admin-reviewer": "admin-reviewer",
        }.get(request.headers.get("authorization", ""))


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = Settings(
        app_env="test",
        rag_provider_mode="deterministic",
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        admin_user_ids="admin-author,admin-reviewer",
        v3_enabled=True,
    )
    application = create_app(
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
    )
    with TestClient(application) as test_client:
        yield test_client


def seed_official_corpus(client: TestClient, course_id: str = "cs3481") -> str:
    created = client.post(
        "/api/courses",
        json={"id": course_id, "name": "CS3481 Fundamentals of Data Science"},
        headers={"Authorization": "Bearer admin-author"},
    )
    assert created.status_code == 201, created.text
    with client.app.state.database.connect() as connection:
        connection.execute(
            "UPDATE courses SET publication_status='draft' WHERE id=?", (course_id,)
        )
    uploaded = client.post(
        f"/api/courses/{course_id}/documents",
        files={
            "file": (
                "clustering.md",
                b"# Clustering\n\nDBSCAN groups density-reachable points and "
                b"labels the remainder as noise. K-means partitions points into "
                b"k clusters by minimising the within-cluster sum of squares.",
                "text/markdown",
            )
        },
        headers={"Authorization": "Bearer admin-author"},
    )
    assert uploaded.status_code == 202, uploaded.text
    with client.app.state.database.connect() as connection:
        connection.execute(
            "UPDATE courses SET publication_status='published' WHERE id=?", (course_id,)
        )
        version_id = connection.execute(
            "SELECT id FROM document_versions WHERE document_id=?",
            (uploaded.json()["document"]["id"],),
        ).fetchone()["id"]
    return str(version_id)


def builder_for(client: TestClient) -> OfficialKnowledgeCourseBuilder:
    app = client.app
    node_builder = OfficialKnowledgeDraftBuilder(
        app.state.database, app.state.settings, app.state.learning
    )
    return OfficialKnowledgeCourseBuilder(
        app.state.database, app.state.settings, app.state.learning, node_builder
    )


def sample_plan() -> dict:
    return {
        "modules": [
            {
                "module_key": "clustering-module",
                "title": "Clustering",
                "description": "Partitioning and density-based clustering.",
                "major": "CS",
                "parent_key": None,
                "prerequisites": [],
            }
        ],
        "nodes": [
            {
                "node_key": "kmeans",
                "title": "K-means",
                "description": "Centroid partitioning.",
                "major": "CS",
                "parent_key": "clustering-module",
                "prerequisites": [],
                "evidence_queries": ["k-means partition sum of squares"],
            },
            {
                "node_key": "dbscan",
                "title": "DBSCAN",
                "description": "Density-reachable grouping.",
                "major": "CS",
                "parent_key": "clustering-module",
                "prerequisites": ["kmeans"],
                "evidence_queries": ["DBSCAN density reachable noise"],
            },
        ],
    }


def build_payload(**overrides: object) -> dict:
    payload: dict = {
        "operation_id": "m6d4-test",
        "plan": sample_plan(),
        "max_model_calls_per_batch": 2,
        "max_reserved_output_tokens_per_batch": 8000,
        "dry_run": False,
    }
    payload.update(overrides)
    return payload


def build(client: TestClient, **overrides: object) -> object:
    payload = OfficialKnowledgeCourseBuild.model_validate(build_payload(**overrides))
    return builder_for(client).build("cs3481", payload, admin_user_id="admin-author")


def test_dry_run_writes_nothing_and_makes_no_calls(client: TestClient) -> None:
    seed_official_corpus(client)
    with client.app.state.database.connect() as c:
        before = {
            t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("knowledge_nodes", "knowledge_tree_versions", "teaching_specs",
                      "material_evidence", "official_knowledge_generation_plans",
                      "learning_model_call_reservations")
        }
    result = build(client, dry_run=True)
    assert result.dry_run is True
    assert result.model_calls_made == 0
    assert result.progress.node_total == 2
    with client.app.state.database.connect() as c:
        after = {
            t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in before
        }
    assert before == after


def test_build_accumulates_into_one_final_tree(client: TestClient) -> None:
    seed_official_corpus(client)
    result = build(client)
    assert result.existing_finalized is False
    assert result.final_tree_version_id
    assert result.progress.status == "FINALIZED"
    assert result.progress.node_completed == 2
    assert result.model_calls_made == 4  # 2 nodes x 2 calls
    assert result.reserved_output_tokens_booked == 16000
    with client.app.state.database.connect() as c:
        trees = c.execute(
            "SELECT * FROM knowledge_tree_versions WHERE tree_kind='OFFICIAL' AND status='DRAFT'"
        ).fetchall()
        assert len(trees) == 1
        tree = trees[0]
        assert tree["workspace_id"] is None and tree["owner_user_id"] is None
        assert tree["corpus_fingerprint"]
        members = c.execute(
            "SELECT m.node_id,m.parent_node_id,m.ordinal,m.teaching_spec_version,"
            "n.kind,n.status,n.owner_user_id "
            "FROM knowledge_tree_memberships m JOIN knowledge_nodes n ON n.id=m.node_id "
            "WHERE m.tree_version_id=? ORDER BY m.ordinal,m.node_id",
            (tree["id"],),
        ).fetchall()
        assert len(members) == 3  # 1 module + 2 atomic
        module = next(m for m in members if m["kind"] == "COMPOSITE")
        atomics = [m for m in members if m["kind"] == "ATOMIC"]
        assert module["teaching_spec_version"] is None
        assert all(m["parent_node_id"] == module["node_id"] for m in atomics)
        assert all(m["teaching_spec_version"] == 1 for m in atomics)
        assert all(m["owner_user_id"] is None and m["status"] == "CANDIDATE" for m in members)
        edges = c.execute(
            "SELECT node_id,prerequisite_node_id FROM knowledge_prerequisite_edges "
            "WHERE tree_version_id=?", (tree["id"],)
        ).fetchall()
        assert len(edges) == 1  # dbscan -> kmeans
        # no publication rows, nothing published
        assert c.execute("SELECT COUNT(*) FROM official_knowledge_publication_requests").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM publication_releases").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM knowledge_nodes WHERE status='PUBLISHED'").fetchone()[0] == 0


def test_rerun_same_plan_is_idempotent_with_zero_new_calls(client: TestClient) -> None:
    seed_official_corpus(client)
    first = build(client)
    second = build(client)
    assert second.existing_finalized is True
    assert second.final_tree_version_id == first.final_tree_version_id
    assert second.model_calls_made == 0
    assert second.reserved_output_tokens_booked == 0
    with client.app.state.database.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM learning_model_call_reservations").fetchone()[0] == 4
        assert c.execute("SELECT COUNT(*) FROM knowledge_tree_versions WHERE tree_kind='OFFICIAL'").fetchone()[0] == 1


def test_resume_after_failure_reuses_completed_nodes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_official_corpus(client)
    learning = client.app.state.learning
    real_generate = learning.generate
    calls = {"count": 0}

    def failing_generate(*args, **kwargs):  # noqa: ANN002, ANN003
        calls["count"] += 1
        if calls["count"] == 3:  # second node's first provider call
            raise ApiError(500, "SIMULATED_PROVIDER_FAILURE", "Synthetic failure.")
        return real_generate(*args, **kwargs)

    monkeypatch.setattr(learning, "generate", failing_generate)
    with pytest.raises(ApiError, match="Synthetic failure"):
        build(client)
    with client.app.state.database.connect() as c:
        plan = c.execute(
            "SELECT * FROM official_knowledge_generation_plans WHERE course_id='cs3481' "
            "AND status='GENERATING'"
        ).fetchone()
        assert plan is not None
        progress = json.loads(plan["progress_json"])
        assert set(progress) == {"kmeans"}  # first node completed before failure
        assert c.execute("SELECT COUNT(*) FROM knowledge_tree_versions").fetchone()[0] == 0

    monkeypatch.undo()
    result = build(client)
    assert result.existing_finalized is False
    assert result.progress.node_completed == 2
    assert result.final_tree_version_id
    # Resume generated only the remaining node: 2 calls (1 node x 2 calls).
    assert result.model_calls_made == 2


def test_plan_validation_rejects_bad_graphs(client: TestClient) -> None:
    seed_official_corpus(client)
    # module with no children (plan model validation fails before any work)
    plan = sample_plan()
    plan["nodes"][0]["parent_key"] = None
    plan["nodes"][1]["parent_key"] = None
    with pytest.raises(Exception, match="child"):
        OfficialKnowledgeCourseBuild.model_validate(build_payload(plan=plan))
    # node parent referencing an unknown module
    plan = sample_plan()
    plan["nodes"][0]["parent_key"] = "missing-module"
    with pytest.raises(Exception, match="parent must be a plan module"):
        OfficialKnowledgeCourseBuild.model_validate(build_payload(plan=plan))
    # cycle through prerequisites (references valid; DB graph check catches the
    # cycle at finalize time, so this stays a model-level smoke)
    plan = sample_plan()
    plan["nodes"][0]["prerequisites"] = ["dbscan"]
    plan["nodes"][1]["prerequisites"] = ["kmeans"]
    payload = OfficialKnowledgeCourseBuild.model_validate(build_payload(plan=plan))
    assert payload.plan.nodes[0].prerequisites == ["dbscan"]


def test_private_evidence_is_rejected_for_course_nodes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_official_corpus(client)
    learning = client.app.state.learning

    def fake_evidence(workspace, query, scope="union"):  # noqa: ANN001
        return [
            {
                "id": "private-chunk",
                "document_id": "private-doc",
                "document_version_id": "missing-version",
                "document_version": "0" * 64,
                "locator_type": "markdown-heading",
                "locator_value": "Private",
                "content": "Private content must never become official evidence.",
                "scope": "official",
                "source_scope": "OWNER_COURSE",
            }
        ]

    monkeypatch.setattr(learning, "evidence", fake_evidence)
    with pytest.raises(ApiError, match="No official corpus chunks"):
        build(client)
    with client.app.state.database.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM knowledge_nodes").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM knowledge_tree_versions").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM learning_model_call_reservations").fetchone()[0] == 0


def test_finalized_snapshot_payload_is_valid(client: TestClient) -> None:
    seed_official_corpus(client)
    result = build(client)
    from app.services.publication_snapshots import official_knowledge_snapshot_payload

    with client.app.state.database.connect() as c:
        summary, resources = official_knowledge_snapshot_payload(
            c, result.final_tree_version_id
        )
    kinds = {r["kind"] for r in resources}
    assert {"TREE_VERSION", "KNOWLEDGE_NODE", "TEACHING_SPEC", "MATERIAL_EVIDENCE"} <= kinds
    assert summary["memberCount"] == 3


def test_single_node_builder_api_unchanged(client: TestClient) -> None:
    seed_official_corpus(client)
    response = client.post(
        GENERATE.format(course_id="cs3481"),
        json={
            "operationId": "m6d4-single",
            "maxNodes": 1,
            "maxModelCalls": 2,
            "maxReservedOutputTokens": 8000,
            "dryRun": False,
        },
        headers={"Authorization": "Bearer admin-author"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["existingDraft"] is False
    assert len(response.json()["nodeIds"]) == 1
