import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from test_learning_journey import setup_workspace
from test_learning_workspace import client_at, join


def private_node(
    client,
    workspace_id: str,
    title: str,
    *,
    kind: str = "ATOMIC",
) -> dict:
    items = (
        [
            {
                "item_id": "principle",
                "requirement": "REQUIRED",
                "objective": f"Explain {title}",
                "acceptance": f"Teach and apply {title} with a complete example",
                "evidence_ids": [],
            }
        ]
        if kind == "ATOMIC"
        else []
    )
    response = client.post(
        f"/api/learning/workspaces/{workspace_id}/nodes",
        json={
            "title": title,
            "description": f"Scope for {title}",
            "major": "CS",
            "kind": kind,
            "items": items,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def plan(
    client,
    workspace_id: str,
    memberships: list[dict],
    prerequisites: list[dict] | None = None,
    *,
    operation_id: str,
) -> object:
    revision = client.get(
        f"/api/learning/workspaces/{workspace_id}/state"
    ).json()["revision"]
    return client.post(
        f"/api/learning/workspaces/{workspace_id}/plans",
        json={
            "operation_id": operation_id,
            "revision": revision,
            "title": "My learning order",
            "change_reason": "Explicit learner plan update",
            "memberships": memberships,
            "prerequisites": prerequisites or [],
        },
    )


def test_migration_014_backfills_normalized_specs_and_is_repeatable(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        database = client.app.state.database
        database.initialize()
        with database.connect() as connection:
            versions = [
                row[0]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )
            ]
            item = connection.execute(
                "SELECT requirement,objective,acceptance,ordinal "
                "FROM teaching_items WHERE node_id=? AND spec_version=1 AND item_id='principle'",
                (node["id"],),
            ).fetchone()
            metadata = connection.execute(
                "SELECT status FROM teaching_spec_metadata WHERE node_id=? AND version=1",
                (node["id"],),
            ).fetchone()
            workspace_rows = connection.execute(
                "SELECT COUNT(*) FROM learning_workspaces WHERE id=?",
                (workspace["id"],),
            ).fetchone()[0]

        assert versions == list(range(1, 15))
        assert tuple(item) == (
            "REQUIRED",
            "Explain addition",
            "Explain combining counts with an example",
            0,
        )
        assert metadata["status"] == "PRIVATE_ACTIVE"
        assert workspace_rows == 1


def test_composite_node_has_no_spec_and_cannot_be_taught_directly(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        client.headers["Authorization"] = "Bearer admin"
        client.post("/api/courses", json={"id": "cs3481", "name": "CS3481"})
        workspace = join(client)
        composite = private_node(client, workspace["id"], "Foundations", kind="COMPOSITE")

        assert composite["kind"] == "COMPOSITE"
        assert composite["spec_version"] is None
        assert composite["items"] == []
        snapshot = client.get(
            f"/api/learning/workspaces/{workspace['id']}/knowledge"
        )
        assert snapshot.status_code == 200, snapshot.text
        state = next(
            node for node in snapshot.json()["registry"] if node["id"] == composite["id"]
        )["state"]
        assert state["learning"]["status"] == "NOT_STARTED"
        assert state["assessment"] == {
            "status": "NOT_ASSESSED",
            "raw_score": None,
            "grade_label": None,
        }

        current_revision = client.get(
            f"/api/learning/workspaces/{workspace['id']}/state"
        ).json()["revision"]
        teaching = client.post(
            f"/api/learning/workspaces/{workspace['id']}/units",
            json={
                "operation_id": "teach-composite",
                "revision": current_revision,
                "node_id": composite["id"],
            },
        )
        assert teaching.status_code == 422
        assert teaching.json()["error"]["code"] == "ATOMIC_REQUIRED"


def test_personalized_tree_reuses_nodes_and_projects_two_independent_axes(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace, atomic = setup_workspace(client)
        root = private_node(client, workspace["id"], "Foundations", kind="COMPOSITE")
        created = plan(
            client,
            workspace["id"],
            [
                {"node_id": root["id"], "parent_node_id": None, "ordinal": 0},
                {"node_id": atomic["id"], "parent_node_id": root["id"], "ordinal": 0},
            ],
            operation_id="plan-v1",
        )
        assert created.status_code == 200, created.text
        assert created.json()["version"] == 1
        assert {member["node_id"] for member in created.json()["members"]} == {
            root["id"],
            atomic["id"],
        }

        taught = client.post(
            f"/api/learning/workspaces/{workspace['id']}/units",
            json={
                "operation_id": "teach-atomic",
                "revision": created.json()["revision"],
                "node_id": atomic["id"],
            },
        )
        assert taught.status_code == 200, taught.text
        assert taught.json()["progress"] == "LEARNED"

        snapshot = client.get(
            f"/api/learning/workspaces/{workspace['id']}/knowledge"
        ).json()
        assert snapshot["selected_tree"] == "PERSONALIZED"
        members = {
            member["node_id"]: member for member in snapshot["personalized_tree"]["members"]
        }
        for node_id in (root["id"], atomic["id"]):
            assert members[node_id]["state"]["learning"]["status"] == "LEARNED"
            assert members[node_id]["state"]["assessment"]["status"] == "NOT_ASSESSED"
            assert members[node_id]["state"]["assessment"]["raw_score"] is None

        second_atomic = private_node(client, workspace["id"], "Subtraction")
        updated = plan(
            client,
            workspace["id"],
            [
                {"node_id": root["id"], "parent_node_id": None, "ordinal": 0},
                {"node_id": second_atomic["id"], "parent_node_id": root["id"], "ordinal": 0},
                {"node_id": atomic["id"], "parent_node_id": root["id"], "ordinal": 1},
            ],
            operation_id="plan-v2",
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["version"] == 2
        snapshot = client.get(
            f"/api/learning/workspaces/{workspace['id']}/knowledge"
        ).json()
        members = {
            member["node_id"]: member for member in snapshot["personalized_tree"]["members"]
        }
        assert members[atomic["id"]]["state"]["learning"]["status"] == "LEARNED"
        assert members[second_atomic["id"]]["state"]["learning"]["status"] == "NOT_STARTED"
        assert members[root["id"]]["state"]["learning"]["status"] == "LEARNING"
        with client.app.state.database.connect() as connection:
            statuses = [
                tuple(row)
                for row in connection.execute(
                    "SELECT version,status FROM knowledge_tree_versions "
                    "WHERE workspace_id=? ORDER BY version",
                    (workspace["id"],),
                )
            ]
            node_count = connection.execute(
                "SELECT COUNT(*) FROM knowledge_nodes WHERE id IN (?,?,?)",
                (root["id"], atomic["id"], second_atomic["id"]),
            ).fetchone()[0]
        assert statuses == [(1, "RETIRED"), (2, "ACTIVE")]
        assert node_count == 3


def test_tree_validator_rejects_orphans_cycles_atomic_parents_and_private_leaks(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace, first = setup_workspace(client)
        second = private_node(client, workspace["id"], "Second")
        root = private_node(client, workspace["id"], "Root", kind="COMPOSITE")
        other_root = private_node(client, workspace["id"], "Other root", kind="COMPOSITE")

        cases = [
            (
                "atomic-parent",
                [
                    {"node_id": first["id"], "parent_node_id": None, "ordinal": 0},
                    {"node_id": root["id"], "parent_node_id": first["id"], "ordinal": 0},
                ],
                [],
                "ATOMIC_PARENT",
            ),
            (
                "orphan",
                [
                    {"node_id": first["id"], "parent_node_id": "missing", "ordinal": 0},
                ],
                [],
                "TREE_ORPHAN",
            ),
            (
                "tree-cycle",
                [
                    {"node_id": root["id"], "parent_node_id": other_root["id"], "ordinal": 0},
                    {"node_id": other_root["id"], "parent_node_id": root["id"], "ordinal": 0},
                ],
                [],
                "TREE_CYCLE",
            ),
            (
                "prerequisite-cycle",
                [
                    {"node_id": first["id"], "parent_node_id": None, "ordinal": 0},
                    {"node_id": second["id"], "parent_node_id": None, "ordinal": 1},
                ],
                [
                    {"node_id": first["id"], "prerequisite_node_id": second["id"]},
                    {"node_id": second["id"], "prerequisite_node_id": first["id"]},
                ],
                "PREREQUISITE_CYCLE",
            ),
        ]
        for operation_id, memberships, prerequisites, code in cases:
            response = plan(
                client,
                workspace["id"],
                memberships,
                prerequisites,
                operation_id=operation_id,
            )
            assert response.status_code == 422, (operation_id, response.text)
            assert response.json()["error"]["code"] == code

        other_workspace = join(client, "b")
        other_node = private_node(client, other_workspace["id"], "Private B")
        client.headers["Authorization"] = "Bearer a"
        leaked = plan(
            client,
            workspace["id"],
            [{"node_id": other_node["id"], "parent_node_id": None, "ordinal": 0}],
            operation_id="foreign-node",
        )
        assert leaked.status_code == 404
        assert leaked.json()["error"]["code"] == "NODE_NOT_FOUND"


def test_official_tree_is_hidden_until_explicit_reviewed_publication(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        client.headers["Authorization"] = "Bearer admin"
        client.post("/api/courses", json={"id": "cs3481", "name": "CS3481"})
        workspace = join(client)
        content = json.dumps(
            [
                {
                    "item_id": "definition",
                    "requirement": "REQUIRED",
                    "objective": "Define density-based clustering",
                    "acceptance": "Give the definition and one valid application",
                    "evidence_ids": [],
                }
            ],
            ensure_ascii=False,
            sort_keys=True,
        )
        with client.app.state.database.connect() as connection:
            connection.execute(
                "INSERT INTO knowledge_nodes("
                "id,course_id,owner_user_id,title,description,major,kind,status) "
                "VALUES('canonical-dbscan','cs3481',NULL,'DBSCAN','Density clustering',"
                "'CS','ATOMIC','CANDIDATE')"
            )
            connection.execute(
                "INSERT INTO teaching_specs VALUES('canonical-dbscan',1,?,?)",
                (content, hashlib.sha256(content.encode()).hexdigest()),
            )
            connection.execute(
                "INSERT INTO knowledge_tree_versions("
                "id,course_id,workspace_id,owner_user_id,tree_kind,version,status,title,"
                "change_reason,content_hash) VALUES("
                "'official-tree-v1','cs3481',NULL,NULL,'OFFICIAL',1,'DRAFT','CS3481 map',"
                "'Manual reviewed fixture',?)",
                ("a" * 64,),
            )
            connection.execute(
                "INSERT INTO knowledge_tree_memberships("
                "tree_version_id,node_id,parent_node_id,ordinal,teaching_spec_version) "
                "VALUES('official-tree-v1','canonical-dbscan',NULL,0,1)"
            )

        hidden = client.get(
            f"/api/learning/workspaces/{workspace['id']}/knowledge"
        ).json()
        assert hidden["official_tree"]["status"] == "NO_REVIEWED_TREE"
        assert "canonical-dbscan" not in {node["id"] for node in hidden["registry"]}

        with client.app.state.database.connect() as connection:
            connection.execute(
                "UPDATE knowledge_nodes SET status='PUBLISHED' WHERE id='canonical-dbscan'"
            )
            connection.execute(
                "UPDATE teaching_spec_metadata SET status='PUBLISHED' "
                "WHERE node_id='canonical-dbscan' AND version=1"
            )
            connection.execute(
                "UPDATE knowledge_tree_versions SET status='PUBLISHED',"
                "reviewed_by_user_id='admin',reviewed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                "WHERE id='official-tree-v1'"
            )

        visible = client.get(
            f"/api/learning/workspaces/{workspace['id']}/knowledge"
        ).json()
        assert visible["official_tree"]["status"] == "PUBLISHED"
        assert visible["official_tree"]["version"] == 1
        assert visible["official_tree"]["members"][0]["node_id"] == "canonical-dbscan"
        assert "canonical-dbscan" in {node["id"] for node in visible["registry"]}

        with (
            client.app.state.database.connect() as connection,
            pytest.raises(sqlite3.IntegrityError, match="immutable"),
        ):
            connection.execute(
                "UPDATE knowledge_tree_memberships SET ordinal=1 "
                "WHERE tree_version_id='official-tree-v1'"
            )

        with (
            client.app.state.database.connect() as connection,
            pytest.raises(sqlite3.IntegrityError, match="review metadata"),
        ):
            connection.execute(
                "UPDATE knowledge_tree_versions SET reviewed_by_user_id='other-reviewer' "
                "WHERE id='official-tree-v1'"
            )


def test_official_tree_publication_fails_when_spec_metadata_is_missing(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        client.headers["Authorization"] = "Bearer admin"
        client.post("/api/courses", json={"id": "cs3481", "name": "CS3481"})
        content = json.dumps(
            [
                {
                    "item_id": "definition",
                    "requirement": "REQUIRED",
                    "objective": "Define a graph",
                    "acceptance": "Give a definition and one example",
                    "evidence_ids": [],
                }
            ],
            sort_keys=True,
        )
        with client.app.state.database.connect() as connection:
            connection.execute(
                "INSERT INTO knowledge_nodes("
                "id,course_id,owner_user_id,title,description,major,kind,status) "
                "VALUES('canonical-graph','cs3481',NULL,'Graph','Graph theory','CS',"
                "'ATOMIC','CANDIDATE')"
            )
            connection.execute(
                "INSERT INTO teaching_specs VALUES('canonical-graph',1,?,?)",
                (content, hashlib.sha256(content.encode()).hexdigest()),
            )
            connection.execute(
                "INSERT INTO knowledge_tree_versions("
                "id,course_id,workspace_id,owner_user_id,tree_kind,version,status,title,"
                "change_reason,content_hash) VALUES("
                "'official-missing-metadata','cs3481',NULL,NULL,'OFFICIAL',1,'DRAFT',"
                "'CS3481 map','Missing metadata fixture',?)",
                ("b" * 64,),
            )
            connection.execute(
                "INSERT INTO knowledge_tree_memberships("
                "tree_version_id,node_id,parent_node_id,ordinal,teaching_spec_version) "
                "VALUES('official-missing-metadata','canonical-graph',NULL,0,1)"
            )
            connection.execute(
                "UPDATE knowledge_nodes SET status='PUBLISHED' WHERE id='canonical-graph'"
            )
            connection.execute(
                "DELETE FROM teaching_spec_metadata "
                "WHERE node_id='canonical-graph' AND version=1"
            )
            with pytest.raises(sqlite3.IntegrityError, match="reviewed nodes and specs"):
                connection.execute(
                    "UPDATE knowledge_tree_versions SET status='PUBLISHED',"
                    "reviewed_by_user_id='admin',reviewed_at='2026-09-12T00:00:00Z' "
                    "WHERE id='official-missing-metadata'"
                )


def test_same_named_private_nodes_never_merge_across_users(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        client.headers["Authorization"] = "Bearer admin"
        client.post("/api/courses", json={"id": "cs3481", "name": "CS3481"})
        workspace_a = join(client, "a")
        node_a = private_node(client, workspace_a["id"], "Stress")
        workspace_b = join(client, "b")
        node_b = private_node(client, workspace_b["id"], "Stress")
        assert node_a["id"] != node_b["id"]

        client.headers["Authorization"] = "Bearer a"
        registry_a = client.get(
            f"/api/learning/workspaces/{workspace_a['id']}/knowledge"
        ).json()["registry"]
        client.headers["Authorization"] = "Bearer b"
        registry_b = client.get(
            f"/api/learning/workspaces/{workspace_b['id']}/knowledge"
        ).json()["registry"]
        assert [node["id"] for node in registry_a if node["title"] == "Stress"] == [node_a["id"]]
        assert [node["id"] for node in registry_b if node["title"] == "Stress"] == [node_b["id"]]


def test_new_private_spec_preserves_historical_learned_version(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        base = f"/api/learning/workspaces/{workspace['id']}"
        revision = client.get(base + "/state").json()["revision"]
        taught = client.post(
            base + "/units",
            json={
                "operation_id": "teach-spec-v1",
                "revision": revision,
                "node_id": node["id"],
            },
        )
        assert taught.status_code == 200, taught.text
        created = client.post(
            base + f"/nodes/{node['id']}/specs",
            json={
                "operation_id": "spec-v2",
                "revision": taught.json()["revision"],
                "change_reason": "Add a newly required boundary case",
                "items": [
                    {
                        "item_id": "principle",
                        "requirement": "REQUIRED",
                        "objective": "Explain addition",
                        "acceptance": "Explain combining counts with an example",
                        "evidence_ids": [],
                    },
                    {
                        "item_id": "boundary",
                        "requirement": "REQUIRED",
                        "objective": "Explain the zero boundary",
                        "acceptance": "Apply addition when one count is zero",
                        "evidence_ids": [],
                    },
                ],
            },
        )
        assert created.status_code == 200, created.text
        assert created.json()["version"] == 2

        snapshot = client.get(base + "/knowledge").json()
        current = next(item for item in snapshot["registry"] if item["id"] == node["id"])
        assert current["state"]["learning"]["spec_version"] == 2
        assert current["state"]["learning"]["status"] == "NOT_STARTED"
        assert current["state"]["learning"]["historical_learned_spec_versions"] == [1]

        state = client.get(base + "/state").json()
        matching_nodes = [item for item in state["nodes"] if item["id"] == node["id"]]
        assert len(matching_nodes) == 1
        assert matching_nodes[0]["progress"] == "NOT_STARTED"
        assert "owner_user_id" not in matching_nodes[0]

        first_v2_unit = client.post(
            base + "/units",
            json={
                "operation_id": "teach-spec-v2-first",
                "revision": created.json()["revision"],
                "node_id": node["id"],
            },
        )
        assert first_v2_unit.status_code == 200, first_v2_unit.text
        assert first_v2_unit.json()["progress"] == "LEARNING"
        second_v2_unit = client.post(
            base + "/units",
            json={
                "operation_id": "teach-spec-v2-second",
                "revision": first_v2_unit.json()["revision"],
                "node_id": node["id"],
            },
        )
        assert second_v2_unit.status_code == 200, second_v2_unit.text
        assert second_v2_unit.json()["progress"] == "LEARNED"

        final = client.get(base + "/knowledge").json()
        current = next(item for item in final["registry"] if item["id"] == node["id"])
        assert current["state"]["learning"]["spec_version"] == 2
        assert current["state"]["learning"]["status"] == "LEARNED"
        assert current["state"]["learning"]["historical_learned_spec_versions"] == [1]
        with client.app.state.database.connect() as connection:
            journeys = [
                tuple(row)
                for row in connection.execute(
                    "SELECT spec_version,status FROM learning_journeys WHERE node_id=? "
                    "ORDER BY spec_version",
                    (node["id"],),
                )
            ]
            assert journeys == [(1, "LEARNED"), (2, "LEARNED")]


def test_database_rejects_workspace_owner_and_private_tree_mismatches(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace_a, node_a = setup_workspace(client)
        workspace_b = join(client, "b")
        node_b = private_node(client, workspace_b["id"], "Private B")
        database = client.app.state.database

        with (
            database.connect() as connection,
            pytest.raises(sqlite3.IntegrityError, match="workspace identity"),
        ):
            connection.execute(
                "INSERT INTO knowledge_tree_versions("
                "id,course_id,workspace_id,owner_user_id,tree_kind,version,status,title,"
                "change_reason,content_hash) VALUES("
                "'bad-owner-tree','cs3481',?,'b','PERSONALIZED',1,'DRAFT','Bad tree',"
                "'Mismatch fixture',?)",
                (workspace_a["id"], "c" * 64),
            )

        with database.connect() as connection:
            connection.execute(
                "INSERT INTO knowledge_tree_versions("
                "id,course_id,workspace_id,owner_user_id,tree_kind,version,status,title,"
                "change_reason,content_hash) VALUES("
                "'draft-a','cs3481',?,'a','PERSONALIZED',1,'DRAFT','A tree',"
                "'Membership fixture',?)",
                (workspace_a["id"], "d" * 64),
            )
            with pytest.raises(sqlite3.IntegrityError, match="authorized tree source"):
                connection.execute(
                    "INSERT INTO knowledge_tree_memberships("
                    "tree_version_id,node_id,parent_node_id,ordinal,teaching_spec_version) "
                    "VALUES('draft-a',?,NULL,0,1)",
                    (node_b["id"],),
                )
            connection.execute(
                "INSERT INTO knowledge_tree_memberships("
                "tree_version_id,node_id,parent_node_id,ordinal,teaching_spec_version) "
                "VALUES('draft-a',?,NULL,0,1)",
                (node_a["id"],),
            )


def test_tree_read_fails_closed_if_legacy_data_contains_foreign_private_node(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace_a, node_a = setup_workspace(client)
        workspace_b = join(client, "b")
        node_b = private_node(client, workspace_b["id"], "Never disclose this title")
        client.headers["Authorization"] = "Bearer a"
        created = plan(
            client,
            workspace_a["id"],
            [{"node_id": node_a["id"], "parent_node_id": None, "ordinal": 0}],
            operation_id="valid-before-corruption",
        )
        assert created.status_code == 200, created.text

        # Simulate a row created by an older/broken writer. The production migration keeps
        # enforcement enabled; only this disposable test database drops it to exercise defense
        # in depth on the read path.
        with client.app.state.database.connect() as connection:
            connection.execute("DROP TRIGGER validate_tree_membership_insert")
            connection.execute("DROP TRIGGER lock_tree_membership_insert")
            connection.execute(
                "INSERT INTO knowledge_tree_memberships("
                "tree_version_id,node_id,parent_node_id,ordinal,teaching_spec_version) "
                "VALUES(?,?,NULL,1,1)",
                (created.json()["id"], node_b["id"]),
            )

        response = client.get(
            f"/api/learning/workspaces/{workspace_a['id']}/knowledge"
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "TREE_SOURCE_UNAVAILABLE"
        assert node_b["id"] not in response.text
        assert "Never disclose this title" not in response.text
