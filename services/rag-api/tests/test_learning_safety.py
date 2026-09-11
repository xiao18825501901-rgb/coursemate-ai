import sqlite3
from pathlib import Path

import pytest
from test_learning_journey import setup_workspace
from test_learning_workspace import client_at, join

from app.learning.compiler import validate_unit
from app.learning.models import TeachingPlan, TeachingUnitOutput
from app.learning.testing import fixture_output


def test_deletion_and_publication_cannot_remove_workspace_privacy(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace, _ = setup_workspace(client)
        corpus = workspace["private_course_id"]
        with client.app.state.database.connect() as db:
            with pytest.raises(sqlite3.IntegrityError):
                db.execute("DELETE FROM courses WHERE id='cs3481'")
            with pytest.raises(sqlite3.IntegrityError):
                db.execute("UPDATE courses SET visibility='public' WHERE id=?", (corpus,))
        for who in ("a", "b", "admin"):
            client.headers["Authorization"] = "Bearer " + who
            response = client.post("/api/courses", json={"id": corpus, "name": "Collision"})
            assert response.status_code == 422
        client.headers["Authorization"] = "Bearer admin"
        assert client.delete(f"/api/admin/courses/{corpus}/publication").status_code == 404
        assert client.delete("/api/courses/cs3481").status_code == 409
        client.headers["Authorization"] = "Bearer b"
        assert client.get(f"/api/learning/workspaces/{workspace['id']}").status_code == 404


def test_unavailable_original_and_foreign_metadata_have_safe_errors(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace, _ = setup_workspace(client)
        uploaded = client.post(
            f"/api/learning/workspaces/{workspace['id']}/documents",
            files={"file": ("中文.txt", b"Example content", "text/plain")},
        ).json()
        doc_id = uploaded["document"]["id"]
        with client.app.state.database.connect() as db:
            version_path = Path(
                db.execute(
                    "SELECT stored_path FROM document_versions WHERE document_id=?",
                    (doc_id,),
                ).fetchone()["stored_path"]
            )
            db.execute(
                "UPDATE documents SET stored_path=? WHERE id=?",
                (str(tmp_path / "absent.txt"), doc_id),
            )
        # Mutable legacy metadata cannot substitute bytes under an immutable version.
        assert client.get(f"/api/learning/documents/{doc_id}/content").content == b"Example content"
        version_path.unlink()
        metadata = client.get(f"/api/learning/documents/{doc_id}").json()
        assert metadata["original_status"] == "ORIGINAL_UNAVAILABLE"
        assert metadata["preview"] == {
            "kind": "DOWNLOAD_ONLY",
            "available": False,
            "reason": "ORIGINAL_UNAVAILABLE",
        }
        assert client.get(f"/api/learning/documents/{doc_id}/content").status_code == 410
        client.headers["Authorization"] = "Bearer b"
        for suffix in ("", "/content"):
            missing = client.get(f"/api/learning/documents/missing{suffix}")
            denied = client.get(f"/api/learning/documents/{doc_id}{suffix}")
            assert denied.json() == missing.json()
        denied_job = client.get(f"/api/ingestion-jobs/{uploaded['job']['id']}")
        assert denied_job.json() == client.get("/api/ingestion-jobs/missing").json()


def test_union_retrieval_does_not_cross_workspace(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace, _ = setup_workspace(client)
        client.post(
            f"/api/learning/workspaces/{workspace['id']}/documents",
            files={
                "file": (
                    "my.txt",
                    b"UNIQUE_SECRET_MARKER matrix private teaching",
                    "text/plain",
                )
            },
        )
        other = join(client, "b")
        learning = client.app.state.learning
        from app.learning.workspaces import workspace_for

        own_hits = learning.evidence(workspace_for(learning.db, workspace["id"], "a"), "matrix")
        other_hits = learning.evidence(workspace_for(learning.db, other["id"], "b"), "matrix")
        assert any("UNIQUE_SECRET_MARKER" in h["content"] for h in own_hits)
        assert not any("UNIQUE_SECRET_MARKER" in h["content"] for h in other_hits)


def test_retrieval_filters_on_frozen_source_before_candidate_selection(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace, _ = setup_workspace(client)
        uploaded = client.post(
            f"/api/learning/workspaces/{workspace['id']}/documents",
            files={
                "file": (
                    "private.txt",
                    b"FROZEN_PRIVATE_MARKER hypergraph tutoring",
                    "text/plain",
                )
            },
        )
        document_id = uploaded.json()["document"]["id"]
        with client.app.state.database.connect() as db:
            db.execute(
                "UPDATE documents SET course_id='cs3481' WHERE id=?",
                (document_id,),
            )
            db.execute(
                "UPDATE chunks SET course_id='cs3481' WHERE document_id=?",
                (document_id,),
            )

        other = join(client, "b")
        learning = client.app.state.learning
        from app.learning.workspaces import workspace_for

        other_hits = learning.evidence(
            workspace_for(learning.db, other["id"], "b"), "hypergraph"
        )
        assert not any("FROZEN_PRIVATE_MARKER" in hit["content"] for hit in other_hits)


@pytest.mark.parametrize(
    "mutation",
    ["unknown_item", "unknown_section", "title_only", "false_anchor"],
)
def test_coverage_rejects_invalid_completed_content(mutation: str) -> None:
    plan = TeachingPlan.model_validate(
        fixture_output(
            "TeachingPlan",
            {
                "preference": "",
                "node_id": "n",
                "spec_version": 1,
                "eligible": [{"item_id": "r"}],
                "bridge_id": None,
            },
        )
    )
    data = fixture_output(
        "TeachingUnitOutput",
        {"plan": plan.model_dump(), "return_anchor": None},
    )
    if mutation == "unknown_item":
        data["coverage_proposals"][0]["item_id"] = "forged"
    elif mutation == "unknown_section":
        data["coverage_proposals"][0]["section_ids"] = ["not_saved"]
    elif mutation == "title_only":
        data["sections"][0]["title"] = data["sections"][0]["content"]
    else:
        data["return_anchor"] = "someone-elses-step"
    with pytest.raises(ValueError):
        validate_unit(
            TeachingUnitOutput.model_validate(data),
            plan=plan,
            node_ids={"n"},
            return_anchor=None,
        )


def test_failed_or_unknown_model_output_is_not_retried_or_learned(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        base = f"/api/learning/workspaces/{workspace['id']}"
        counter = []

        def fail(*args, **kwargs):
            counter.append(1)
            raise TimeoutError("unknown provider outcome")

        client.app.state.learning.provider.generate = fail
        payload = {
            "operation_id": "timeout-1",
            "revision": client.get(base + "/state").json()["revision"],
            "question": "2+3",
            "node_ids": [node["id"]],
        }
        assert client.post(base + "/solutions", json=payload).status_code == 502
        assert client.post(base + "/solutions", json=payload).status_code == 409
        assert len(counter) == 1
        state = client.get(base + "/state").json()
        assert not state["solutions"] and not state["units"]
        assert state["nodes"][0]["progress"] == "NOT_STARTED"
