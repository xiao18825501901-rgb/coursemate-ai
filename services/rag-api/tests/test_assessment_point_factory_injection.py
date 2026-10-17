from fastapi.testclient import TestClient
from test_assessment_point_sources import seeded
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
