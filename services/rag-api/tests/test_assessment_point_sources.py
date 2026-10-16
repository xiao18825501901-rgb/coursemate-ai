"""Actual source/Spec authority for point compilation, not semantic qualification."""

import json

import pytest
from test_learning_journey import setup_workspace
from test_learning_workspace import client_at

from app.errors import ApiError


def seeded(client):
    workspace, _ = setup_workspace(client)
    uploaded = client.post(
        f"/api/learning/workspaces/{workspace['id']}/documents",
        files={
            "file": (
                "bounds.txt",
                b"A core point counts itself. Epsilon includes the boundary.",
                "text/plain",
            )
        },
    )
    assert uploaded.status_code == 202, uploaded.text
    document_id = uploaded.json()["document"]["id"]
    with client.app.state.database.connect() as db:
        chunk = db.execute(
            "SELECT id FROM chunks WHERE document_id=? ORDER BY ordinal", (document_id,)
        ).fetchone()
        assert chunk is not None
    result = client.post(
        f"/api/learning/workspaces/{workspace['id']}/nodes",
        json={
            "title": "Density bounds",
            "description": "Authorized synthetic definition",
            "major": "CS",
            "kind": "ATOMIC",
            "items": [
                {
                    "item_id": "bounds",
                    "requirement": "REQUIRED",
                    "objective": "Explain epsilon boundary and self-counting",
                    "acceptance": "State both conditions exactly",
                    "evidence_ids": [chunk["id"]],
                }
            ],
        },
    )
    assert result.status_code == 200, result.text
    return workspace, result.json(), document_id, str(chunk["id"])


def reader():
    from app.learning.assessment_point_sources import freeze_point_sources, verify_point_sources

    return freeze_point_sources, verify_point_sources


def read(client, workspace, node, **kwargs):
    freeze, _ = reader()
    return freeze(
        client.app.state.database,
        workspace_id=workspace["id"],
        owner="a",
        node_id=node["id"],
        **kwargs,
    )


def test_source_freeze_keeps_original_spec_exact_chunk_and_conditions_without_verifying_points(
    tmp_path,
):
    with client_at(tmp_path) as client:
        workspace, node, document, chunk = seeded(client)
        snapshot = read(client, workspace, node)
        assert snapshot.owner_user_id == "a" and snapshot.spec_version == 1
        assert snapshot.targets[0].evidence_ids == [chunk]
        assert snapshot.targets[0].fragments[0].document_id == document
        assert "counts itself" in snapshot.targets[0].fragments[0].content
        assert len(snapshot.identity()) == 64
        assert "VERIFIED" not in snapshot.model_dump_json()
        _, verify = reader()
        verify(client.app.state.database, snapshot)
        with client.app.state.database.connect() as db:
            assert (
                db.execute("SELECT COUNT(*) FROM learning_model_call_reservations").fetchone()[0]
                == 0
            )


def test_required_item_without_source_refuses_whole_freeze_not_partial_catalog(tmp_path):
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        with pytest.raises(ApiError) as failed:
            read(client, workspace, node)
        assert failed.value.code == "ASSESSMENT_POINTS_NOT_READY"


def test_foreign_owner_cannot_read_source_or_spec(tmp_path):
    freeze, _ = reader()
    with client_at(tmp_path) as client:
        workspace, node, _, _ = seeded(client)
        with pytest.raises(ApiError):
            freeze(
                client.app.state.database,
                workspace_id=workspace["id"],
                owner="admin",
                node_id=node["id"],
            )


def test_revoked_material_source_stops_snapshot_reuse(tmp_path):
    _, verify = reader()
    with client_at(tmp_path) as client:
        workspace, node, _, chunk = seeded(client)
        snapshot = read(client, workspace, node)
        fragment = snapshot.targets[0].fragments[0]
        with client.app.state.database.connect() as db:
            db.execute(
                "INSERT INTO material_evidence(id,node_id,chunk_id,document_version_id,"
                "owner_user_id,source_scope,locator_type,locator_value,status) "
                "VALUES('point-source-revoked',?,?,?,'a','WORKSPACE_PRIVATE',?,?,'REVOKED')",
                (
                    node["id"],
                    chunk,
                    fragment.document_version_id,
                    fragment.locator_type,
                    fragment.locator_value,
                ),
            )
        with pytest.raises(ApiError):
            verify(client.app.state.database, snapshot)


def test_saved_spec_version_is_not_replaced_by_newer_spec(tmp_path):
    _, verify = reader()
    with client_at(tmp_path) as client:
        workspace, node, _, chunk = seeded(client)
        snapshot = read(client, workspace, node)
        with client.app.state.database.connect() as db:
            items = [
                {
                    "item_id": "other",
                    "requirement": "REQUIRED",
                    "objective": "Explain another definition",
                    "acceptance": "Check another",
                    "evidence_ids": [chunk],
                }
            ]
            db.execute(
                "INSERT INTO teaching_specs(node_id,version,content_json,content_hash) "
                "VALUES(?,2,?,?)",
                (node["id"], json.dumps(items), "b" * 64),
            )
            # Mirror the actual private Spec's separate publication metadata;
            # new version does not erase the original authorized Spec.
            db.execute(
                "UPDATE teaching_spec_metadata SET status='PRIVATE_ACTIVE' "
                "WHERE node_id=? AND version=2",
                (node["id"],),
            )
        assert read(client, workspace, node).spec_version == 2
        verify(client.app.state.database, snapshot)
        assert read(client, workspace, node, spec_version=1).identity() == snapshot.identity()


def test_changed_private_chunk_stops_freeze_reuse(tmp_path):
    _, verify = reader()
    with client_at(tmp_path) as client:
        workspace, node, _, chunk = seeded(client)
        snapshot = read(client, workspace, node)
        with client.app.state.database.connect() as db:
            db.execute("UPDATE chunks SET content='Changed conditions' WHERE id=?", (chunk,))
        with pytest.raises(ApiError):
            verify(client.app.state.database, snapshot)


def test_partial_sources_cannot_drop_an_unready_required_target(tmp_path):
    with client_at(tmp_path) as client:
        workspace, node, _, chunk = seeded(client)
        with client.app.state.database.connect() as db:
            items = [
                {
                    "item_id": "known",
                    "requirement": "REQUIRED",
                    "objective": "Explain self counting",
                    "acceptance": "State the condition",
                    "evidence_ids": [chunk],
                },
                {
                    "item_id": "missing",
                    "requirement": "REQUIRED",
                    "objective": "Explain missing rule",
                    "acceptance": "State the missing condition",
                    "evidence_ids": [],
                },
            ]
            db.execute(
                "INSERT INTO teaching_specs(node_id,version,content_json,content_hash) "
                "VALUES(?,2,?,?)",
                (node["id"], json.dumps(items), "c" * 64),
            )
        with pytest.raises(ApiError) as failed:
            read(client, workspace, node)
        assert failed.value.code == "ASSESSMENT_POINTS_NOT_READY"


def test_truncated_conditions_require_source_preparation_not_a_false_point(tmp_path):
    with client_at(tmp_path) as client:
        workspace, node, _, chunk = seeded(client)
        with client.app.state.database.connect() as db:
            db.execute("UPDATE chunks SET content=? WHERE id=?", ("condition " * 700, chunk))
        with pytest.raises(ApiError) as failed:
            read(client, workspace, node)
        assert failed.value.code == "ASSESSMENT_POINTS_SOURCE_TOO_LARGE"


def test_retired_original_spec_does_not_use_a_newer_authorized_spec(tmp_path):
    _, verify = reader()
    with client_at(tmp_path) as client:
        workspace, node, _, _ = seeded(client)
        snapshot = read(client, workspace, node)
        with client.app.state.database.connect() as db:
            db.execute(
                "UPDATE teaching_spec_metadata SET status='RETIRED' WHERE node_id=? AND version=1",
                (node["id"],),
            )
        with pytest.raises(ApiError):
            verify(client.app.state.database, snapshot)
