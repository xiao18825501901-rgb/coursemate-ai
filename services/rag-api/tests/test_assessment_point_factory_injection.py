import json
import time

from fastapi.testclient import TestClient
from test_assessment_point_sources import seeded
from test_deterministic_graph_point_publication import graph_case
from test_learning_workspace import Identity

from app.config import Settings
from app.learning.assessment_point_catalog_models import VerifiedCatalog
from app.learning.assessment_point_configuration import AssessmentPointPolicyService
from app.main import create_app


class Reader:
    def read_with_targets_for(self, source, language):
        assert language == "en"
        points = []
        targets = {}
        for index in range(2):
            point_id = f"point-{index + 1}"
            target_id = f"target-{index + 1}"
            points.append(
                {
                    "point_id": point_id,
                    "canonical_key": point_id,
                    "objective": f"Observable objective {index + 1}",
                    "constraints": [f"Condition {index + 1}"],
                    "scoring_evidence": [f"Evidence {index + 1}"],
                    "source_refs": [
                        {
                            "source_id": f"evidence-{index + 1}",
                            "document_id": "document",
                            "document_version": "version",
                            "locator": f"section:{index + 1}",
                            "scope_key": f"course:{source.course_id}",
                        }
                    ],
                    "allowed_forms": ["SHORT_TEXT"],
                    "sequence": index,
                    "validation_receipt_id": "TEST_ONLY-review",
                    "status": "VERIFIED",
                    "weight": 1,
                    "weight_receipt_id": None,
                }
            )
            targets[point_id] = (target_id,)
        catalog = VerifiedCatalog.model_validate(
            {
                "catalog_id": "TEST_ONLY-catalog",
                "scope": {
                    "owner_id": source.owner_user_id,
                    "course_id": source.course_id,
                    "node_id": source.node_id,
                    "spec_version": str(source.spec_version),
                    "source_snapshot": source.identity(),
                },
                "points": points,
                "validation_receipt_id": "TEST_ONLY-review",
            }
        )
        return catalog, targets


def test_create_app_injects_dynamic_policy_without_changing_legacy_default(tmp_path):
    app = create_app(
        settings=Settings(
            _env_file=None,
            database_path=tmp_path / "rag.sqlite3",
            upload_dir=tmp_path / "uploads",
            app_env="test",
            rag_provider_mode="deterministic",
            v3_enabled=True,
        ),
        auth_verifier=Identity(),
        assessment_point_policy=AssessmentPointPolicyService(Reader()),
    )
    with TestClient(app) as client:
        created = client.post(
            "/api/courses",
            headers={"Authorization": "Bearer a"},
            json={"id": "cs3481", "name": "CS3481"},
        )
        assert created.status_code == 201, created.text
        workspace, node, _, _ = seeded(client)
        endpoint = (
            f"/api/learning/workspaces/{workspace['id']}/assessments/setup/{node['id']}"
        )
        dynamic = client.get(endpoint, params={"content_language": "en"})
        legacy = client.get(endpoint)

    assert dynamic.status_code == 200
    assert dynamic.json()["policy_version"] == "cj.assessment.points.v1"
    assert dynamic.json()["minimum_questions"] == 2
    assert dynamic.json()["maximum_questions"] == 4
    assert legacy.status_code == 200
    assert legacy.json()["minimum_questions"] == 5


def test_create_app_mounts_bounded_graph_policy_only_when_enabled(tmp_path):
    app = create_app(
        settings=Settings(
            _env_file=None,
            database_path=tmp_path / "rag.sqlite3",
            upload_dir=tmp_path / "uploads",
            app_env="test",
            rag_provider_mode="deterministic",
            v3_enabled=True,
            assessment_point_policy_enabled=True,
        ),
        auth_verifier=Identity(),
    )
    with TestClient(app) as client:
        created = client.post(
            "/api/courses",
            headers={"Authorization": "Bearer a"},
            json={"id": "cs3481", "name": "CS3481"},
        )
        assert created.status_code == 201, created.text
        workspace, node, _source = graph_case(client)
        setup = client.get(
            f"/api/learning/workspaces/{workspace['id']}/assessments/setup/{node['id']}",
            params={"content_language": "en"},
        )

    assert setup.status_code == 200, setup.text
    assert setup.json()["policy_version"] == "cj.assessment.points.v1"
    assert setup.json()["status"] == "READY"
    assert setup.json()["minimum_questions"] == 1
    assert setup.json()["maximum_questions"] == 2


def test_enabled_graph_policy_completes_real_http_assessment_with_zero_model_calls(
    tmp_path,
):
    app = create_app(
        settings=Settings(
            _env_file=None,
            database_path=tmp_path / "rag.sqlite3",
            upload_dir=tmp_path / "uploads",
            app_env="test",
            rag_provider_mode="deterministic",
            v3_enabled=True,
            assessment_point_policy_enabled=True,
        ),
        auth_verifier=Identity(),
    )
    with TestClient(app) as client:
        created = client.post(
            "/api/courses",
            headers={"Authorization": "Bearer a"},
            json={"id": "cs3481", "name": "CS3481"},
        )
        assert created.status_code == 201, created.text
        workspace, node, _source = graph_case(client)
        base = f"/api/learning/workspaces/{workspace['id']}"
        setup = client.get(
            base + f"/assessments/setup/{node['id']}",
            params={"content_language": "en"},
        )
        assert setup.status_code == 200, setup.text
        setup_body = setup.json()
        configured = client.post(
            base + "/assessments",
            json={
                "operation_id": "graph-http-configure",
                "revision": client.get(base + "/state").json()["revision"],
                "node_id": node["id"],
                "client_intent_id": "graph-http-intent",
                "intent_action": "CONFIGURE",
                "content_language": "en",
                "slots": setup_body["default_slots"],
            },
        )
        assert configured.status_code == 200, configured.text
        configured_body = configured.json()
        configuration_id = configured_body["configuration_id"]
        assert configured_body["policy_version"] == "cj.assessment.points.v1"
        assert configured_body["content_language"] == "en"
        assert configured_body["client_intent_id"] == "graph-http-intent"

        deadline = time.monotonic() + 5
        status = configured_body
        while status["status"] != "READY" and time.monotonic() < deadline:
            time.sleep(0.05)
            polled = client.get(
                base + f"/assessments/preparations/{configuration_id}"
            )
            assert polled.status_code == 200, polled.text
            status = polled.json()
        assert status["status"] == "READY", status
        assert status["prepared_questions"] == 1

        opened = client.post(
            base + "/assessments",
            json={
                "operation_id": "graph-http-open",
                "revision": client.get(base + "/state").json()["revision"],
                "node_id": node["id"],
                "client_intent_id": "graph-http-intent",
                "intent_action": "OPEN",
                "configuration_id": configuration_id,
                "content_language": "en",
            },
        )
        assert opened.status_code == 200, opened.text
        session = opened.json()
        assert session["status"] == "IN_PROGRESS"
        assert len(session["questions"]) == 1
        assert "answer_key" not in session["questions"][0]
        assert "reference_solution" not in session["questions"][0]

        question = session["questions"][0]
        with client.app.state.database.connect() as db:
            answer_row = db.execute(
                "SELECT answer_json FROM assessment_question_revisions WHERE id=?",
                (question["question_revision_id"],),
            ).fetchone()
            model_calls = db.execute("SELECT COUNT(*) FROM generic_llm_calls").fetchone()[0]
        answer = json.loads(answer_row["answer_json"])["reference_answer"]
        submitted = client.post(
            base + f"/assessments/{session['id']}/submit",
            json={
                "operation_id": "graph-http-submit",
                "revision": client.get(base + "/state").json()["revision"],
                "answers": [
                    {
                        "blueprint_item_id": question["id"],
                        "answer": answer,
                    }
                ],
            },
        )
        assert submitted.status_code == 200, submitted.text
        history = client.get(base + f"/assessments/{session['id']}")

    assert submitted.json()["status"] == "GRADED"
    assert submitted.json()["raw_score"] == 100
    assert history.status_code == 200, history.text
    assert history.json()["status"] == "GRADED"
    assert history.json()["raw_score"] == 100
    assert model_calls == 0


def test_public_student_adapter_exposes_dynamic_point_setup_and_preserves_selection(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CMUI_PROVIDER_MODE", "test")
    app = create_app(
        settings=Settings(
            _env_file=None,
            database_path=tmp_path / "rag.sqlite3",
            upload_dir=tmp_path / "uploads",
            app_env="test",
            rag_provider_mode="deterministic",
            v3_enabled=True,
            ui_extension_enabled=True,
            ui_web_dir=tmp_path / "no-web-build",
            assessment_point_policy_enabled=True,
        ),
        auth_verifier=Identity(),
    )
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer a"
        created = client.post(
            "/api/courses",
            json={"id": "cs3481", "name": "CS3481"},
        )
        assert created.status_code == 201, created.text
        workspace, node, _source = graph_case(client)
        public = "/ui-extension/api/ui/v1"
        setup = client.get(
            public + f"/courses/cs3481/knowledge/{node['id']}/assessment/setup",
            params={"content_language": "en"},
        )
        assert setup.status_code == 200, setup.text
        setup_body = setup.json()
        started = client.post(
            public + f"/courses/cs3481/knowledge/{node['id']}/assessment/session",
            json={
                "request_id": "public-graph-configure",
                "client_intent_id": "public-graph-intent",
                "intent_action": "CONFIGURE",
                "content_language": "en",
                "slots": setup_body["default_slots"],
            },
        )
        assert started.status_code == 201, started.text
        preparation = started.json()
        configuration_id = preparation["configuration_id"]
        deadline = time.monotonic() + 5
        while preparation["status"] != "READY" and time.monotonic() < deadline:
            time.sleep(0.05)
            preparation_response = client.get(
                public
                + f"/courses/cs3481/knowledge/{node['id']}/assessment/prepare/status",
                params={"configuration_id": configuration_id},
            )
            assert preparation_response.status_code == 200, preparation_response.text
            preparation = preparation_response.json()
        assert preparation["status"] == "READY", preparation
        opened = client.post(
            public + f"/courses/cs3481/knowledge/{node['id']}/assessment/session",
            json={
                "request_id": "public-graph-open",
                "client_intent_id": "public-graph-intent",
                "intent_action": "OPEN",
                "configuration_id": configuration_id,
                "content_language": "en",
                "slots": [],
            },
        )
        assert opened.status_code == 201, opened.text
        session = opened.json()
        question = session["questions"][0]
        with client.app.state.database.connect() as db:
            answer_row = db.execute(
                "SELECT answer_json FROM assessment_question_revisions WHERE id=?",
                (question["question_revision_id"],),
            ).fetchone()
            model_calls = db.execute("SELECT COUNT(*) FROM generic_llm_calls").fetchone()[0]
        answer = json.loads(answer_row["answer_json"])["reference_answer"]
        submitted = client.post(
            public + f"/courses/cs3481/knowledge/assessment/{session['id']}/submit",
            json={
                "request_id": "public-graph-submit",
                "answers": [
                    {"blueprint_item_id": question["id"], "answer": answer}
                ],
            },
        )
        history = client.get(
            public + f"/courses/cs3481/knowledge/assessment/{session['id']}"
        )

    assert setup_body["policy_version"] == "cj.assessment.points.v1"
    assert setup_body["minimum_questions"] == 1
    assert started.json()["client_intent_id"] == "public-graph-intent"
    assert started.json()["content_language"] == "en"
    assert session["status"] == "IN_PROGRESS"
    assert "answer_key" not in question
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "GRADED"
    assert submitted.json()["raw_score"] == 100
    assert history.status_code == 200, history.text
    assert history.json()["status"] == "GRADED"
    assert history.json()["raw_score"] == 100
    assert model_calls == 0
