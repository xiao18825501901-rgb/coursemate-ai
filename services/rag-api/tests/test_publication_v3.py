import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


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


def v3_client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            settings=Settings(
                app_env="test",
                rag_provider_mode="deterministic",
                database_path=tmp_path / "rag.sqlite3",
                upload_dir=tmp_path / "uploads",
                admin_user_ids="admin-author,admin-reviewer",
                v3_enabled=True,
            ),
            embedding_provider=FakeEmbeddingProvider(),
            auth_verifier=FakeAuthVerifier(),
        )
    )


def create_private_course_with_document(client: TestClient) -> tuple[str, str]:
    created = client.post(
        "/api/courses",
        json={"id": "share-me", "name": "Share me", "description": "Frozen copy"},
        headers={"Authorization": "Bearer owner"},
    )
    assert created.status_code == 201, created.text
    uploaded = client.post(
        "/api/courses/share-me/documents",
        files={"file": ("notes.md", b"# Reviewed notes\n\nExact source.", "text/markdown")},
        headers={"Authorization": "Bearer owner"},
    )
    assert uploaded.status_code == 202, uploaded.text
    assert uploaded.json()["job"]["status"] in {"queued", "processing", "completed"}
    with client.app.state.database.connect() as connection:
        version_id = connection.execute(
            "SELECT id FROM document_versions WHERE document_id=?",
            (uploaded.json()["document"]["id"],),
        ).fetchone()["id"]
    return uploaded.json()["document"]["id"], version_id


def seed_official_tree(client: TestClient) -> None:
    created = client.post(
        "/api/courses",
        json={"id": "cs3481", "name": "CS3481"},
        headers={"Authorization": "Bearer admin-author"},
    )
    assert created.status_code == 201, created.text
    items = [
        {
            "item_id": "definition",
            "requirement": "REQUIRED",
            "objective": "Define rasterization",
            "acceptance": "Explain the pipeline with one course example",
            "evidence_ids": [],
        }
    ]
    encoded = json.dumps(items, ensure_ascii=False, sort_keys=True)
    with client.app.state.database.connect() as connection:
        connection.execute(
            "INSERT INTO knowledge_nodes("
            "id,course_id,owner_user_id,title,description,major,kind,status) "
            "VALUES('rasterization','cs3481',NULL,'Rasterization',"
            "'Raster graphics pipeline','CS','ATOMIC','CANDIDATE')"
        )
        connection.execute(
            "INSERT INTO teaching_specs(node_id,version,content_json,content_hash) "
            "VALUES('rasterization',1,?,?)",
            (encoded, hashlib.sha256(encoded.encode()).hexdigest()),
        )
        connection.execute(
            "INSERT INTO knowledge_tree_versions("
            "id,course_id,workspace_id,owner_user_id,tree_kind,version,status,title,"
            "change_reason,content_hash) VALUES("
            "'official-cs3481-v1','cs3481',NULL,NULL,'OFFICIAL',1,'DRAFT',"
            "'CS3481 reviewed map','Initial reviewed subset',?)",
            ("c" * 64,),
        )
        connection.execute(
            "INSERT INTO knowledge_tree_memberships("
            "tree_version_id,node_id,parent_node_id,ordinal,teaching_spec_version) "
            "VALUES('official-cs3481-v1','rasterization',NULL,0,1)"
        )


def test_v3_course_publication_freezes_a_scoped_review_snapshot(tmp_path: Path) -> None:
    with v3_client(tmp_path) as client:
        document_id, version_id = create_private_course_with_document(client)
        submitted = client.post(
            "/api/courses/share-me/publication-requests",
            json={
                "shareMaterialsConsent": True,
                "rightsConfirmation": True,
                "consentVersion": "v1",
            },
            headers={"Authorization": "Bearer owner"},
        )
        assert submitted.status_code == 201, submitted.text
        request_id = submitted.json()["id"]

        generic_private_browse = client.get(
            "/api/courses/share-me/documents",
            headers={"Authorization": "Bearer admin-author"},
        )
        generic_admin_list = client.get(
            "/api/courses",
            headers={"Authorization": "Bearer admin-author"},
        )
        snapshot = client.get(
            f"/api/admin/publication-requests/{request_id}/snapshot",
            headers={"Authorization": "Bearer admin-reviewer"},
        )
        scoped_content = client.get(
            f"/api/admin/publication-requests/{request_id}/documents/{version_id}/content",
            headers={"Authorization": "Bearer admin-reviewer"},
        )
        locked = client.patch(
            "/api/courses/share-me",
            json={"name": "Changed while pending"},
            headers={"Authorization": "Bearer owner"},
        )

    assert submitted.json()["snapshotId"].startswith("snapshot_")
    assert len(submitted.json()["snapshotHash"]) == 64
    assert submitted.json()["resourceCount"] >= 2
    assert generic_private_browse.status_code == 404
    assert "share-me" not in {item["id"] for item in generic_admin_list.json()["items"]}
    assert snapshot.status_code == 200, snapshot.text
    assert snapshot.json()["id"] == submitted.json()["snapshotId"]
    resources = snapshot.json()["resources"]
    frozen_document = next(item for item in resources if item["kind"] == "DOCUMENT_VERSION")
    assert frozen_document["id"] == version_id
    assert frozen_document["displayName"] == "notes.md"
    assert frozen_document["metadata"]["documentId"] == document_id
    assert "storedPath" not in frozen_document["metadata"]
    assert "ownerUserId" not in frozen_document["metadata"]
    assert scoped_content.status_code == 200
    assert scoped_content.content == b"# Reviewed notes\n\nExact source."
    assert scoped_content.headers["cache-control"] == "private, no-store"
    assert locked.status_code == 409
    assert locked.json()["error"]["code"] == "PUBLICATION_REVIEW_LOCKED"


def test_owner_withdrawal_revokes_an_approved_course_release(tmp_path: Path) -> None:
    with v3_client(tmp_path) as client:
        _, version_id = create_private_course_with_document(client)
        submitted = client.post(
            "/api/courses/share-me/publication-requests",
            json={
                "shareMaterialsConsent": True,
                "rightsConfirmation": True,
                "consentVersion": "v1",
            },
            headers={"Authorization": "Bearer owner"},
        )
        request_id = submitted.json()["id"]
        approved = client.post(
            f"/api/admin/publication-requests/{request_id}/review",
            json={"decision": "approve", "reviewNote": "Exact snapshot reviewed."},
            headers={"Authorization": "Bearer admin-reviewer"},
        )
        visible_before = client.get(
            "/api/courses", headers={"Authorization": "Bearer other"}
        )
        withdrawn = client.delete(
            "/api/courses/share-me/publication-requests/current",
            headers={"Authorization": "Bearer owner"},
        )
        hidden_after = client.get(
            "/api/courses", headers={"Authorization": "Bearer other"}
        )
        stale_review_access = client.get(
            f"/api/admin/publication-requests/{request_id}/documents/{version_id}/content",
            headers={"Authorization": "Bearer admin-reviewer"},
        )
        editable_after = client.patch(
            "/api/courses/share-me",
            json={"name": "Editable after withdrawal"},
            headers={"Authorization": "Bearer owner"},
        )
        with client.app.state.database.connect() as connection:
            release = connection.execute(
                "SELECT status,cache_generation FROM publication_releases "
                "WHERE subject_kind='COURSE' AND request_id=?",
                (request_id,),
            ).fetchone()
        deleted = client.delete(
            "/api/courses/share-me",
            headers={"Authorization": "Bearer owner"},
        )
        with client.app.state.database.connect() as connection:
            retained_private_publication_rows = sum(
                connection.execute(query, (request_id,)).fetchone()[0]
                for query in (
                    "SELECT COUNT(*) FROM publication_review_snapshots WHERE request_id=?",
                    "SELECT COUNT(*) FROM publication_releases WHERE request_id=?",
                    "SELECT COUNT(*) FROM publication_audit_events WHERE request_id=?",
                )
            )

    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert visible_before.json()["total"] == 1
    assert withdrawn.status_code == 204
    assert hidden_after.json()["total"] == 0
    assert stale_review_access.status_code == 404
    assert editable_after.status_code == 200
    assert tuple(release) == ("WITHDRAWN", 2)
    assert deleted.status_code == 204
    assert retained_private_publication_rows == 0


def test_official_tree_and_specs_require_exact_independent_review_and_withdrawal(
    tmp_path: Path,
) -> None:
    with v3_client(tmp_path) as client:
        seed_official_tree(client)
        workspace = client.post(
            "/api/learning/workspaces",
            json={"course_id": "cs3481"},
            headers={"Authorization": "Bearer owner"},
        ).json()
        drafts = client.get(
            "/api/admin/knowledge-publication-drafts",
            headers={"Authorization": "Bearer admin-author"},
        )
        submitted = client.post(
            "/api/admin/knowledge-publication-requests",
            json={"treeVersionId": "official-cs3481-v1"},
            headers={"Authorization": "Bearer admin-author"},
        )
        assert submitted.status_code == 201, submitted.text
        request_id = submitted.json()["id"]
        snapshot = client.get(
            f"/api/admin/knowledge-publication-requests/{request_id}/snapshot",
            headers={"Authorization": "Bearer admin-reviewer"},
        )
        self_review = client.post(
            f"/api/admin/knowledge-publication-requests/{request_id}/review",
            json={"decision": "approve", "reviewNote": "Self review"},
            headers={"Authorization": "Bearer admin-author"},
        )
        with (
            client.app.state.database.connect() as connection,
            pytest.raises(sqlite3.IntegrityError, match="locked by publication review"),
        ):
            connection.execute(
                "UPDATE knowledge_tree_memberships SET ordinal=1 "
                "WHERE tree_version_id='official-cs3481-v1'"
            )
        with (
            client.app.state.database.connect() as connection,
            pytest.raises(sqlite3.IntegrityError, match="locked by publication review"),
        ):
            connection.execute(
                "UPDATE knowledge_nodes SET description='Changed after submission' "
                "WHERE id='rasterization'"
            )
        approved = client.post(
            f"/api/admin/knowledge-publication-requests/{request_id}/review",
            json={"decision": "approve", "reviewNote": "Tree and exact Spec reviewed."},
            headers={"Authorization": "Bearer admin-reviewer"},
        )
        visible = client.get(
            f"/api/learning/workspaces/{workspace['id']}/knowledge",
            headers={"Authorization": "Bearer owner"},
        )
        withdrawn = client.delete(
            f"/api/admin/knowledge-publication-requests/{request_id}",
            headers={"Authorization": "Bearer admin-reviewer"},
        )
        hidden = client.get(
            f"/api/learning/workspaces/{workspace['id']}/knowledge",
            headers={"Authorization": "Bearer owner"},
        )
        with client.app.state.database.connect() as connection:
            statuses = connection.execute(
                "SELECT tree.status,node.status,spec.status "
                "FROM knowledge_tree_versions AS tree "
                "JOIN knowledge_tree_memberships AS member ON member.tree_version_id=tree.id "
                "JOIN knowledge_nodes AS node ON node.id=member.node_id "
                "JOIN teaching_spec_metadata AS spec ON spec.node_id=member.node_id "
                "AND spec.version=member.teaching_spec_version "
                "WHERE tree.id='official-cs3481-v1'"
            ).fetchone()
            release = connection.execute(
                "SELECT status,cache_generation FROM publication_releases "
                "WHERE subject_kind='OFFICIAL_KNOWLEDGE' AND request_id=?",
                (request_id,),
            ).fetchone()

    assert drafts.status_code == 200
    assert drafts.json()["items"][0]["treeVersionId"] == "official-cs3481-v1"
    assert submitted.json()["status"] == "pending"
    assert submitted.json()["snapshotId"].startswith("snapshot_")
    assert snapshot.status_code == 200
    kinds = {item["kind"] for item in snapshot.json()["resources"]}
    assert {"TREE_VERSION", "KNOWLEDGE_NODE", "TEACHING_SPEC"} <= kinds
    assert self_review.status_code == 409
    assert self_review.json()["error"]["code"] == "INDEPENDENT_REVIEW_REQUIRED"
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert visible.json()["official_tree"]["status"] == "PUBLISHED"
    assert withdrawn.status_code == 204
    assert hidden.json()["official_tree"]["status"] == "NO_REVIEWED_TREE"
    assert tuple(statuses) == ("RETIRED", "PUBLISHED", "PUBLISHED")
    assert tuple(release) == ("WITHDRAWN", 2)


def test_overlay_shares_only_explicit_private_versions_and_revokes_future_access(
    tmp_path: Path,
) -> None:
    with v3_client(tmp_path) as client:
        seed_official_tree(client)
        workspace = client.post(
            "/api/learning/workspaces",
            json={"course_id": "cs3481"},
            headers={"Authorization": "Bearer owner"},
        ).json()
        selected_upload = client.post(
            f"/api/learning/workspaces/{workspace['id']}/documents",
            files={
                "file": (
                    "selected.md",
                    b"# Selected private note\n\nShare only this exact source.",
                    "text/markdown",
                )
            },
            headers={"Authorization": "Bearer owner"},
        )
        hidden_upload = client.post(
            f"/api/learning/workspaces/{workspace['id']}/documents",
            files={"file": ("hidden.md", b"# Never share\n\nPrivate.", "text/markdown")},
            headers={"Authorization": "Bearer owner"},
        )
        selected_node = client.post(
            f"/api/learning/workspaces/{workspace['id']}/nodes",
            json={
                "title": "My raster note",
                "description": "Private model-assisted explanation",
                "major": "CS",
                "kind": "ATOMIC",
                "items": [
                    {
                        "item_id": "private-definition",
                        "requirement": "REQUIRED",
                        "objective": "Explain my raster note",
                        "acceptance": "Give a complete private example",
                        "evidence_ids": [],
                    }
                ],
            },
            headers={"Authorization": "Bearer owner"},
        ).json()
        hidden_node = client.post(
            f"/api/learning/workspaces/{workspace['id']}/nodes",
            json={
                "title": "Unselected secret node",
                "description": "Must remain private",
                "major": "CS",
                "kind": "ATOMIC",
                "items": [
                    {
                        "item_id": "secret",
                        "requirement": "REQUIRED",
                        "objective": "Keep this private",
                        "acceptance": "Never enter another user's package",
                        "evidence_ids": [],
                    }
                ],
            },
            headers={"Authorization": "Bearer owner"},
        ).json()
        with client.app.state.database.connect() as connection:
            selected_version = connection.execute(
                "SELECT id FROM document_versions WHERE document_id=?",
                (selected_upload.json()["document"]["id"],),
            ).fetchone()["id"]
            hidden_version = connection.execute(
                "SELECT id FROM document_versions WHERE document_id=?",
                (hidden_upload.json()["document"]["id"],),
            ).fetchone()["id"]
            connection.execute(
                "INSERT INTO material_evidence("
                "id,node_id,document_version_id,owner_user_id,source_scope,"
                "locator_type,locator_value) VALUES("
                "'selected-evidence',?,?,?,'WORKSPACE_PRIVATE','section','1')",
                (selected_node["id"], selected_version, "owner"),
            )
            connection.execute(
                "INSERT INTO conversations("
                "id,owner_user_id,course_id,title,preferred_language) "
                "VALUES('private-chat','owner','cs3481','SECRET CHAT','auto')"
            )
            connection.execute(
                "INSERT INTO messages(id,conversation_id,role,content) "
                "VALUES('private-message','private-chat','user','NEVER PUBLISH THIS CHAT')"
            )
        submitted = client.post(
            f"/api/learning/workspaces/{workspace['id']}/overlay-publication-requests",
            json={
                "nodeIds": [selected_node["id"]],
                "documentVersionIds": [selected_version],
                "artifactIds": [],
                "evidenceIds": ["selected-evidence"],
                "shareSelectedContentConsent": True,
                "rightsConfirmation": True,
                "consentVersion": "v1",
            },
            headers={"Authorization": "Bearer owner"},
        )
        assert submitted.status_code == 201, submitted.text
        request_id = submitted.json()["id"]
        pending_public = client.get(
            f"/api/shared-overlays/{request_id}",
            headers={"Authorization": "Bearer other"},
        )
        generic_admin_browse = client.get(
            f"/api/learning/document-versions/{selected_version}",
            headers={"Authorization": "Bearer admin-reviewer"},
        )
        review_snapshot = client.get(
            f"/api/admin/overlay-publication-requests/{request_id}/snapshot",
            headers={"Authorization": "Bearer admin-reviewer"},
        )
        approved = client.post(
            f"/api/admin/overlay-publication-requests/{request_id}/review",
            json={"decision": "approve", "reviewNote": "Selected package only."},
            headers={"Authorization": "Bearer admin-reviewer"},
        )
        shared = client.get(
            f"/api/shared-overlays/{request_id}",
            headers={"Authorization": "Bearer other"},
        )
        scoped_content = client.get(
            f"/api/shared-overlays/{request_id}/documents/{selected_version}/content",
            headers={"Authorization": "Bearer other"},
        )
        still_not_global = client.get(
            f"/api/learning/document-versions/{selected_version}",
            headers={"Authorization": "Bearer other"},
        )
        withdrawn = client.delete(
            f"/api/learning/workspaces/{workspace['id']}/overlay-publication-requests/current",
            headers={"Authorization": "Bearer owner"},
        )
        revoked_package = client.get(
            f"/api/shared-overlays/{request_id}",
            headers={"Authorization": "Bearer other"},
        )
        revoked_content = client.get(
            f"/api/shared-overlays/{request_id}/documents/{selected_version}/content",
            headers={"Authorization": "Bearer other"},
        )
        with client.app.state.database.connect() as connection:
            release = connection.execute(
                "SELECT status,cache_generation FROM publication_releases "
                "WHERE subject_kind='OVERLAY' AND request_id=?",
                (request_id,),
            ).fetchone()

    assert pending_public.status_code == 404
    assert generic_admin_browse.status_code == 404
    assert review_snapshot.status_code == 200
    serialized_review = review_snapshot.text
    assert selected_node["id"] in serialized_review
    assert selected_version in serialized_review
    assert "selected-evidence" in serialized_review
    assert hidden_node["id"] not in serialized_review
    assert hidden_version not in serialized_review
    assert "SECRET CHAT" not in serialized_review
    assert "NEVER PUBLISH THIS CHAT" not in serialized_review
    assert approved.status_code == 200, approved.text
    assert shared.status_code == 200
    assert shared.headers["cache-control"] == "private, no-store"
    assert shared.json()["workspaceId"] is None
    assert "workspaceId" not in shared.json()["summary"]
    assert scoped_content.content == b"# Selected private note\n\nShare only this exact source."
    assert scoped_content.headers["cache-control"] == "private, no-store"
    assert still_not_global.status_code == 404
    assert withdrawn.status_code == 204
    assert revoked_package.status_code == 404
    assert revoked_content.status_code == 404
    assert tuple(release) == ("WITHDRAWN", 2)


def test_overlay_submission_rejects_foreign_or_implicit_private_content(
    tmp_path: Path,
) -> None:
    with v3_client(tmp_path) as client:
        seed_official_tree(client)
        owner_workspace = client.post(
            "/api/learning/workspaces",
            json={"course_id": "cs3481"},
            headers={"Authorization": "Bearer owner"},
        ).json()
        other_workspace = client.post(
            "/api/learning/workspaces",
            json={"course_id": "cs3481"},
            headers={"Authorization": "Bearer other"},
        ).json()
        foreign_upload = client.post(
            f"/api/learning/workspaces/{other_workspace['id']}/documents",
            files={"file": ("foreign.md", b"# Other user's note", "text/markdown")},
            headers={"Authorization": "Bearer other"},
        )
        with client.app.state.database.connect() as connection:
            foreign_version = connection.execute(
                "SELECT id FROM document_versions WHERE document_id=?",
                (foreign_upload.json()["document"]["id"],),
            ).fetchone()["id"]
        foreign = client.post(
            f"/api/learning/workspaces/{owner_workspace['id']}/overlay-publication-requests",
            json={
                "nodeIds": [],
                "documentVersionIds": [foreign_version],
                "artifactIds": [],
                "evidenceIds": [],
                "shareSelectedContentConsent": True,
                "rightsConfirmation": True,
                "consentVersion": "v1",
            },
            headers={"Authorization": "Bearer owner"},
        )
        forbidden_implicit_chat = client.post(
            f"/api/learning/workspaces/{owner_workspace['id']}/overlay-publication-requests",
            json={
                "nodeIds": [],
                "documentVersionIds": [],
                "artifactIds": [],
                "evidenceIds": [],
                "conversationIds": ["private-chat"],
                "shareSelectedContentConsent": True,
                "rightsConfirmation": True,
                "consentVersion": "v1",
            },
            headers={"Authorization": "Bearer owner"},
        )

    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "OVERLAY_RESOURCE_NOT_FOUND"
    assert forbidden_implicit_chat.status_code == 422
    assert forbidden_implicit_chat.json()["error"]["code"] == "VALIDATION_ERROR"


def test_overlay_version_change_requires_withdrawal_and_a_new_review_snapshot(
    tmp_path: Path,
) -> None:
    with v3_client(tmp_path) as client:
        seed_official_tree(client)
        workspace = client.post(
            "/api/learning/workspaces",
            json={"course_id": "cs3481"},
            headers={"Authorization": "Bearer owner"},
        ).json()
        node = client.post(
            f"/api/learning/workspaces/{workspace['id']}/nodes",
            json={
                "title": "Versioned private node",
                "description": "First reviewed description",
                "major": "CS",
                "kind": "ATOMIC",
                "items": [
                    {
                        "item_id": "v1-item",
                        "requirement": "REQUIRED",
                        "objective": "Teach version one",
                        "acceptance": "Cover version one",
                        "evidence_ids": [],
                    }
                ],
            },
            headers={"Authorization": "Bearer owner"},
        ).json()
        base_payload = {
            "nodeIds": [node["id"]],
            "documentVersionIds": [],
            "artifactIds": [],
            "evidenceIds": [],
            "shareSelectedContentConsent": True,
            "rightsConfirmation": True,
            "consentVersion": "v1",
        }
        first = client.post(
            f"/api/learning/workspaces/{workspace['id']}/overlay-publication-requests",
            json=base_payload,
            headers={"Authorization": "Bearer owner"},
        )
        revision = client.get(
            f"/api/learning/workspaces/{workspace['id']}/state",
            headers={"Authorization": "Bearer owner"},
        ).json()["revision"]
        new_spec = client.post(
            f"/api/learning/workspaces/{workspace['id']}/nodes/{node['id']}/specs",
            json={
                "operation_id": "new-spec-after-submit",
                "revision": revision,
                "change_reason": "The private owner changed the selected content",
                "items": [
                    {
                        "item_id": "v2-item",
                        "requirement": "REQUIRED",
                        "objective": "Teach version two",
                        "acceptance": "Cover the revised scope",
                        "evidence_ids": [],
                    }
                ],
            },
            headers={"Authorization": "Bearer owner"},
        )
        stale_review = client.post(
            f"/api/admin/overlay-publication-requests/{first.json()['id']}/review",
            json={"decision": "approve", "reviewNote": "Must not approve stale content."},
            headers={"Authorization": "Bearer admin-reviewer"},
        )
        withdrawn = client.delete(
            f"/api/learning/workspaces/{workspace['id']}/overlay-publication-requests/current",
            headers={"Authorization": "Bearer owner"},
        )
        second = client.post(
            f"/api/learning/workspaces/{workspace['id']}/overlay-publication-requests",
            json=base_payload,
            headers={"Authorization": "Bearer owner"},
        )
        second_snapshot = client.get(
            f"/api/admin/overlay-publication-requests/{second.json()['id']}/snapshot",
            headers={"Authorization": "Bearer admin-reviewer"},
        )

    assert first.status_code == 201
    assert new_spec.status_code == 200, new_spec.text
    assert new_spec.json()["version"] == 2
    assert stale_review.status_code == 409
    assert stale_review.json()["error"]["code"] == "PUBLICATION_SNAPSHOT_STALE"
    assert withdrawn.status_code == 204
    assert second.status_code == 201
    specs = [
        resource
        for resource in second_snapshot.json()["resources"]
        if resource["kind"] == "TEACHING_SPEC"
    ]
    assert [resource["version"] for resource in specs] == ["2"]
