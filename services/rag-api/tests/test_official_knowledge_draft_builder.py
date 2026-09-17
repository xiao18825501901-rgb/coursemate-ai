"""M6D1 official knowledge draft builder: corpus -> bounded draft -> OFFICIAL DRAFT.

Every test runs against the deterministic fake provider (app_env=test,
rag_provider_mode=deterministic) and a synthetic official corpus uploaded through
the real ingestion path. No live model call is possible in this mode.
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

GENERATE = "/api/admin/courses/{course_id}/official-knowledge-drafts/generate"


class FakeEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


class FakeAuthVerifier:
    def authenticate(self, request: Request) -> str | None:
        return {
            "Bearer owner": "owner",
            "Bearer other": "other",
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
    """Create an official course and one indexed OFFICIAL document version.

    A published official course locks its source set (migration 019), so the
    corpus is prepared while the course is draft and the course is published
    afterwards - the same preparation order a human gate would use.
    """

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
                b"# Clustering\n\nDBSCAN groups density-reachable points "
                b"and labels the remainder as noise.",
                "text/markdown",
            )
        },
        headers={"Authorization": "Bearer admin-author"},
    )
    assert uploaded.status_code == 202, uploaded.text
    job = client.get(
        f"/api/ingestion-jobs/{uploaded.json()['job']['id']}",
        headers={"Authorization": "Bearer admin-author"},
    )
    assert job.json()["status"] == "completed"
    with client.app.state.database.connect() as connection:
        connection.execute(
            "UPDATE courses SET publication_status='published' WHERE id=?", (course_id,)
        )
        version_id = connection.execute(
            "SELECT id FROM document_versions WHERE document_id=?",
            (uploaded.json()["document"]["id"],),
        ).fetchone()["id"]
        scope = connection.execute(
            "SELECT source_scope FROM document_versions WHERE id=?", (version_id,)
        ).fetchone()["source_scope"]
    assert scope == "OFFICIAL"
    return str(version_id)


def generate_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "operationId": "m6d1-canary",
        "maxNodes": 1,
        "maxModelCalls": 2,
        "maxReservedOutputTokens": 8000,
        "dryRun": False,
    }
    payload.update(overrides)
    return payload


def post_generate(
    client: TestClient, course_id: str = "cs3481", **overrides: object
) -> object:
    return client.post(
        GENERATE.format(course_id=course_id),
        json=generate_payload(**overrides),
        headers={"Authorization": "Bearer admin-author"},
    )


def table_counts(client: TestClient) -> dict[str, int]:
    database = client.app.state.database
    queries = {
        "nodes": "SELECT COUNT(*) FROM knowledge_nodes",
        "specs": "SELECT COUNT(*) FROM teaching_specs",
        "trees": "SELECT COUNT(*) FROM knowledge_tree_versions",
        "memberships": "SELECT COUNT(*) FROM knowledge_tree_memberships",
        "evidence": "SELECT COUNT(*) FROM material_evidence",
        "reservations": "SELECT COUNT(*) FROM learning_model_call_reservations",
        "runs": "SELECT COUNT(*) FROM learning_model_run_evidence",
        "publication_requests": (
            "SELECT COUNT(*) FROM official_knowledge_publication_requests"
        ),
        "releases": "SELECT COUNT(*) FROM publication_releases",
    }
    with database.connect() as connection:
        return {
            name: int(connection.execute(query).fetchone()[0])
            for name, query in queries.items()
        }


# 1. dryRun: zero DB writes, zero provider calls, full corpus accounting.
def test_dry_run_writes_nothing_and_makes_no_provider_calls(client: TestClient) -> None:
    seed_official_corpus(client)
    before = table_counts(client)

    response = post_generate(client, dryRun=True)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dryRun"] is True
    assert body["existingDraft"] is False
    assert body["treeVersionId"] is None
    assert body["treeVersion"] is None
    assert body["nodeIds"] == []
    assert len(body["corpusFingerprint"]) == 64
    assert body["corpus"] == {"documentCount": 1, "chunkCount": 1, "versionCount": 1}
    assert body["budget"]["plannedModelCalls"] == 2
    assert body["budget"]["plannedReservedOutputTokens"] == 8000
    assert body["budget"]["modelCallsMade"] == 0
    assert table_counts(client) == before


# 2/7/8/9/10/11: bounded generation canonicalizes one ATOMIC node with an exact
# DRAFT Spec and an OFFICIAL DRAFT tree, reservations recorded on the ledger.
def test_generate_canonicalizes_one_atomic_draft_tree(client: TestClient) -> None:
    version_id = seed_official_corpus(client)

    response = post_generate(client)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["existingDraft"] is False
    assert body["treeVersion"] == 1
    assert len(body["nodeIds"]) == 1
    node_id = body["nodeIds"][0]
    assert body["budget"]["modelCallsMade"] == 2
    assert body["budget"]["reservedOutputTokensBooked"] == 8000
    assert body["evidenceChunkCount"] >= 1
    assert len(body["evidenceRows"]) >= 1

    with client.app.state.database.connect() as connection:
        node = connection.execute(
            "SELECT * FROM knowledge_nodes WHERE id=?", (node_id,)
        ).fetchone()
        assert node is not None
        assert node["owner_user_id"] is None
        assert node["status"] == "CANDIDATE"
        assert node["course_id"] == "cs3481"
        assert node["kind"] == "ATOMIC"
        assert node["major"] == "CS"

        spec = connection.execute(
            "SELECT spec.content_json,spec.content_hash,metadata.status,"
            "metadata.created_by_user_id,metadata.change_reason "
            "FROM teaching_specs AS spec "
            "JOIN teaching_spec_metadata AS metadata "
            "ON metadata.node_id=spec.node_id AND metadata.version=spec.version "
            "WHERE spec.node_id=? AND spec.version=1",
            (node_id,),
        ).fetchone()
        assert spec is not None
        assert spec["status"] == "DRAFT"
        assert spec["created_by_user_id"] == "admin-author"
        items = json.loads(spec["content_json"])
        required = [item for item in items if item["requirement"] == "REQUIRED"]
        assert required
        assert all(item["evidence_ids"] for item in required)

        tree = connection.execute(
            "SELECT * FROM knowledge_tree_versions WHERE id=?",
            (body["treeVersionId"],),
        ).fetchone()
        assert tree is not None
        assert tree["course_id"] == "cs3481"
        assert tree["workspace_id"] is None
        assert tree["owner_user_id"] is None
        assert tree["tree_kind"] == "OFFICIAL"
        assert tree["status"] == "DRAFT"
        assert tree["corpus_fingerprint"] == body["corpusFingerprint"]
        assert len(tree["content_hash"]) == 64

        membership = connection.execute(
            "SELECT * FROM knowledge_tree_memberships WHERE tree_version_id=?",
            (body["treeVersionId"],),
        ).fetchone()
        assert membership["node_id"] == node_id
        assert membership["parent_node_id"] is None
        assert membership["teaching_spec_version"] == 1

        evidence = connection.execute(
            "SELECT * FROM material_evidence WHERE node_id=?", (node_id,)
        ).fetchall()
        assert evidence
        for row in evidence:
            assert row["source_scope"] == "OFFICIAL"
            assert row["owner_user_id"] is None
            assert row["status"] == "ACTIVE"
            assert row["document_version_id"] == version_id
            assert row["chunk_id"]
            assert row["locator_type"]
            assert row["locator_value"]

        reservations = connection.execute(
            "SELECT * FROM learning_model_call_reservations ORDER BY created_at,id"
        ).fetchall()
        assert len(reservations) == 2
        operations: set[str] = set()
        for row in reservations:
            assert row["owner_user_id"] == "admin-author"
            assert row["course_id"] == "cs3481"
            assert row["workspace_id"]
            assert row["status"] == "COMPLETED"
            assert row["role"] == "teacher"
            assert row["reserved_output_tokens"] == client.app.state.settings.v3_max_output_tokens
            operations.add(str(row["operation_id"]))
        assert operations == {"m6d1-canary-node", "m6d1-canary-spec"}


# 3. maxModelCalls is a hard limit: a single-call budget uses the bundle schema.
def test_single_call_budget_uses_the_bundle_schema(client: TestClient) -> None:
    seed_official_corpus(client)
    response = post_generate(client, maxModelCalls=1, maxReservedOutputTokens=4000)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["budget"]["modelCallsMade"] == 1
    assert body["budget"]["reservedOutputTokensBooked"] == 4000
    with client.app.state.database.connect() as connection:
        roles = [
            row["role"]
            for row in connection.execute(
                "SELECT role FROM learning_model_call_reservations"
            )
        ]
    assert roles == ["teacher"]


# 4. maxReservedOutputTokens is a hard ceiling: a ceiling that cannot cover one
# call blocks before ANY provider call; a ceiling that cannot cover two calls
# degrades to the single-call bundle instead of over-running.
def test_reserved_token_ceiling_blocks_before_any_call(client: TestClient) -> None:
    seed_official_corpus(client)
    response = post_generate(
        client, maxModelCalls=2, maxReservedOutputTokens=3999
    )
    assert response.status_code == 429, response.text
    assert response.json()["error"]["code"] == "OFFICIAL_DRAFT_BUDGET_EXCEEDED"
    counts = table_counts(client)
    assert counts["reservations"] == 0
    assert counts["runs"] == 0
    assert counts["nodes"] == 0
    assert counts["trees"] == 0


def test_partial_ceiling_degrades_to_the_single_call_bundle(
    client: TestClient,
) -> None:
    seed_official_corpus(client)
    response = post_generate(
        client, maxModelCalls=2, maxReservedOutputTokens=7999
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["budget"]["plannedModelCalls"] == 1
    assert body["budget"]["modelCallsMade"] == 1
    assert body["budget"]["reservedOutputTokensBooked"] == 4000
    assert len(body["nodeIds"]) == 1
    with client.app.state.database.connect() as connection:
        roles = [
            row["role"]
            for row in connection.execute(
                "SELECT role FROM learning_model_call_reservations"
            )
        ]
    assert roles == ["teacher"]


# 5/6. Private evidence is rejected; nothing is canonicalized without official
# evidence. The retriever is faked to return a private workspace chunk only.
def test_private_evidence_is_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    version_id = seed_official_corpus(client)
    # Create a private workspace document to fabricate a WORKSPACE_PRIVATE binding.
    owner_course = client.post(
        "/api/courses",
        json={"id": "owner-course", "name": "Owner private"},
        headers={"Authorization": "Bearer owner"},
    )
    assert owner_course.status_code == 201, owner_course.text
    uploaded = client.post(
        "/api/courses/owner-course/documents",
        files={
            "file": (
                "private.md",
                b"# Private notes\n\nNever use this in the official tree.",
                "text/markdown",
            )
        },
        headers={"Authorization": "Bearer owner"},
    )
    assert uploaded.status_code == 202, uploaded.text
    with client.app.state.database.connect() as connection:
        private_version_id = connection.execute(
            "SELECT id FROM document_versions WHERE document_id=?",
            (uploaded.json()["document"]["id"],),
        ).fetchone()["id"]
        private_scope = connection.execute(
            "SELECT source_scope FROM document_versions WHERE id=?",
            (private_version_id,),
        ).fetchone()["source_scope"]
    assert private_scope == "OWNER_COURSE"

    learning = client.app.state.learning

    def fake_evidence(workspace, query, scope="union"):  # noqa: ANN001
        return [
            {
                "id": "private-chunk",
                "document_id": uploaded.json()["document"]["id"],
                "document_version_id": private_version_id,
                "document_version": "0" * 64,
                "locator_type": "markdown-heading",
                "locator_value": "Private notes",
                "content": "Private content must never become official evidence.",
                "scope": "official",
                "source_scope": "OWNER_COURSE",
            }
        ]

    monkeypatch.setattr(learning, "evidence", fake_evidence)
    response = post_generate(client)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "OFFICIAL_DRAFT_EVIDENCE_UNAVAILABLE"
    counts = table_counts(client)
    assert counts["nodes"] == 0
    assert counts["trees"] == 0
    assert counts["evidence"] == 0
    assert counts["reservations"] == 0
    assert version_id  # official version stayed intact


# 6b. A REQUIRED item without official evidence cannot canonicalize.
def test_required_item_without_evidence_is_rejected(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_official_corpus(client)
    import app.learning.testing as testing_module

    real_fixture = testing_module.fixture_output

    def evidence_stripped(schema: str, context: dict) -> dict:
        output = real_fixture(schema, context)
        if schema in {"OfficialNodeDraftOutput", "OfficialTeachingSpecDraftOutput"}:
            for item in output["items"]:
                item["evidence_ids"] = []
        return output

    monkeypatch.setattr(testing_module, "fixture_output", evidence_stripped)
    response = post_generate(client)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "OFFICIAL_DRAFT_EVIDENCE_REQUIRED"
    counts = table_counts(client)
    assert counts["nodes"] == 0
    assert counts["specs"] == 0
    assert counts["trees"] == 0
    assert counts["memberships"] == 0
    assert counts["evidence"] == 0


# 12/13/16. The builder's draft feeds the existing snapshot pipeline and the
# independent-review gate stays untouched.
def test_draft_feeds_snapshot_and_self_review_stays_forbidden(client: TestClient) -> None:
    seed_official_corpus(client)
    generated = post_generate(client).json()

    drafts = client.get(
        "/api/admin/knowledge-publication-drafts",
        headers={"Authorization": "Bearer admin-author"},
    )
    assert drafts.status_code == 200
    assert [item["treeVersionId"] for item in drafts.json()["items"]] == [
        generated["treeVersionId"]
    ]

    submitted = client.post(
        "/api/admin/knowledge-publication-requests",
        json={"treeVersionId": generated["treeVersionId"]},
        headers={"Authorization": "Bearer admin-author"},
    )
    assert submitted.status_code == 201, submitted.text
    request_id = submitted.json()["id"]
    snapshot = client.get(
        f"/api/admin/knowledge-publication-requests/{request_id}/snapshot",
        headers={"Authorization": "Bearer admin-reviewer"},
    )
    assert snapshot.status_code == 200, snapshot.text
    kinds = {item["kind"] for item in snapshot.json()["resources"]}
    assert {"TREE_VERSION", "KNOWLEDGE_NODE", "TEACHING_SPEC", "MATERIAL_EVIDENCE"} <= kinds
    assert all(
        item["sourceScope"] == "OFFICIAL"
        for item in snapshot.json()["resources"]
        if item["kind"] in {"TREE_VERSION", "KNOWLEDGE_NODE", "TEACHING_SPEC"}
    )

    self_review = client.post(
        f"/api/admin/knowledge-publication-requests/{request_id}/review",
        json={"decision": "approve", "reviewNote": "Self review"},
        headers={"Authorization": "Bearer admin-author"},
    )
    assert self_review.status_code == 409
    assert self_review.json()["error"]["code"] == "INDEPENDENT_REVIEW_REQUIRED"


# 14/15. The builder never submits or approves publication.
def test_builder_never_submits_or_publishes(client: TestClient) -> None:
    seed_official_corpus(client)
    generated = post_generate(client).json()

    counts = table_counts(client)
    assert counts["publication_requests"] == 0
    assert counts["releases"] == 0
    with client.app.state.database.connect() as connection:
        status = connection.execute(
            "SELECT status FROM knowledge_tree_versions WHERE id=?",
            (generated["treeVersionId"],),
        ).fetchone()["status"]
        node_statuses = [
            row["status"]
            for row in connection.execute(
                "SELECT status FROM knowledge_nodes WHERE id IN ("
                + ",".join("?" for _ in generated["nodeIds"])
                + ")",
                generated["nodeIds"],
            )
        ]
    assert status == "DRAFT"
    assert node_statuses == ["CANDIDATE"]


# 17. Idempotency: the same corpus+config rerun reuses the draft.
def test_same_corpus_rerun_reuses_the_existing_draft(client: TestClient) -> None:
    seed_official_corpus(client)
    first = post_generate(client).json()
    assert first["existingDraft"] is False

    second = post_generate(client)
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["existingDraft"] is True
    assert body["treeVersionId"] == first["treeVersionId"]
    assert body["treeVersion"] == first["treeVersion"]
    assert body["nodeIds"] == first["nodeIds"]

    counts = table_counts(client)
    assert counts["nodes"] == 1
    assert counts["trees"] == 1
    assert counts["memberships"] == 1
    assert counts["reservations"] == 2  # no additional model calls for the rerun


# 18. A mid-generation failure leaves no half official tree behind.
def test_generation_failure_leaves_no_half_tree(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_official_corpus(client)
    learning = client.app.state.learning
    real_generate = learning.generate
    calls = 0

    def failing_generate(*args, **kwargs):  # noqa: ANN002, ANN003
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ApiError(500, "SIMULATED_PROVIDER_FAILURE", "Synthetic failure.")
        return real_generate(*args, **kwargs)

    monkeypatch.setattr(learning, "generate", failing_generate)
    response = post_generate(client)
    assert response.status_code == 500, response.text
    assert response.json()["error"]["code"] == "SIMULATED_PROVIDER_FAILURE"

    counts = table_counts(client)
    assert counts["nodes"] == 0
    assert counts["specs"] == 0
    assert counts["trees"] == 0
    assert counts["memberships"] == 0
    assert counts["evidence"] == 0
    # The first reservation survives as audit evidence; nothing canonical was written.
    assert counts["reservations"] == 1


# Admin-only + official-course guards.
def test_non_admin_cannot_generate(client: TestClient) -> None:
    seed_official_corpus(client)
    response = client.post(
        GENERATE.format(course_id="cs3481"),
        json=generate_payload(),
        headers={"Authorization": "Bearer owner"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ADMIN_REQUIRED"


def test_user_course_cannot_build_an_official_draft(client: TestClient) -> None:
    created = client.post(
        "/api/courses",
        json={"id": "owner-course", "name": "Owner private"},
        headers={"Authorization": "Bearer owner"},
    )
    assert created.status_code == 201, created.text
    response = post_generate(client, course_id="owner-course")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OFFICIAL_COURSE_REQUIRED"


def test_empty_official_corpus_is_rejected(client: TestClient) -> None:
    created = client.post(
        "/api/courses",
        json={"id": "cs3481", "name": "CS3481"},
        headers={"Authorization": "Bearer admin-author"},
    )
    assert created.status_code == 201, created.text
    response = post_generate(client)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OFFICIAL_CORPUS_EMPTY"


def test_hard_ceilings_are_rejected(client: TestClient) -> None:
    seed_official_corpus(client)
    for overrides, label in (
        ({"maxNodes": 11}, "nodes"),
        ({"maxModelCalls": 21}, "calls"),
        ({"maxReservedOutputTokens": 20001}, "tokens"),
    ):
        response = post_generate(client, **overrides)
        assert response.status_code == 422, label
        assert response.json()["error"]["code"] == "VALIDATION_ERROR", label
