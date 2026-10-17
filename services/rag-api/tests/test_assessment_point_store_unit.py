from test_assessment_point_sources import read, seeded
from test_learning_workspace import client_at

from app.learning.assessment_point_catalog_models import (
    CatalogScope,
    VerifiedCatalog,
    VerifiedPoint,
)
from app.learning.assessment_point_configuration import AssessmentPointPolicyService
from app.learning.assessment_point_store import AssessmentPointConfigurationStore
from app.learning.assessments import AssessmentService


class SnapshotReader:
    def __init__(self, source) -> None:
        target = source.targets[0]
        fragment = target.fragments[0]
        point = VerifiedPoint.model_validate(
            {
                "point_id": "point-density-boundary",
                "canonical_key": "density.boundary",
                "objective": target.objective_text,
                "constraints": [target.acceptance],
                "scoring_evidence": [target.acceptance],
                "allowed_forms": ["SHORT_TEXT"],
                "sequence": 0,
                "source_refs": [
                    {
                        "source_id": fragment.evidence_id,
                        "document_id": fragment.document_id,
                        "document_version": fragment.document_version_id,
                        "locator": fragment.locator_value,
                        "scope_key": "owner:course:source",
                    }
                ],
                "validation_receipt_id": "review:controlled",
            }
        )
        self.catalog = VerifiedCatalog(
            catalog_id="catalog:controlled",
            scope=CatalogScope(
                owner_id=source.owner_user_id,
                course_id=source.course_id,
                node_id=source.node_id,
                spec_version=str(source.spec_version),
                source_snapshot=source.identity(),
            ),
            points=[point],
            validation_receipt_id="review:catalog",
        )
        self.targets = {point.point_id: (target.objective_id,)}

    def read_with_targets_for(self, source, language):
        assert source.identity() == self.catalog.scope.source_snapshot
        assert language == "en"
        return self.catalog, self.targets


def test_freeze_and_replay_persist_one_original_point_plan_without_model_calls(tmp_path) -> None:
    with client_at(tmp_path) as client:
        workspace_view, node_view, _, _ = seeded(client)
        source = read(client, workspace_view, node_view)
        policy = AssessmentPointPolicyService(SnapshotReader(source))
        store = AssessmentPointConfigurationStore(client.app.state.database, policy)
        defaults = policy.setup(source, "en")["default_slots"]

        with client.app.state.database.connect() as db:
            workspace = db.execute(
                "SELECT * FROM learning_workspaces WHERE id=?", (workspace_view["id"],)
            ).fetchone()
            node = AssessmentService._atomic_node(db, workspace, node_view["id"])
            config, items = store.freeze(
                db,
                workspace,
                node,
                defaults,
                requested_id=None,
                intent_id="intent-one-point",
                content_language="en",
            )
            replay, saved = store.freeze(
                db,
                workspace,
                node,
                defaults,
                requested_id=None,
                intent_id="intent-one-point",
                content_language="en",
            )

            assert config["id"] == replay["id"]
            assert config["status"] == "FROZEN"
            assert config["policy_version"] == "cj.assessment.points.v1"
            assert len(items) == len(saved) == 1
            assert items[0].marks_basis_points == 10_000
            assert db.execute(
                "SELECT COUNT(*) FROM assessment_point_configuration_plans"
            ).fetchone()[0] == 1
            assert db.execute(
                "SELECT COUNT(*) FROM assessment_configuration_slots WHERE configuration_id=?",
                (config["id"],),
            ).fetchone()[0] == 1
            assert db.execute(
                "SELECT COUNT(*) FROM learning_model_call_reservations"
            ).fetchone()[0] == 0


def test_existing_assessment_service_uses_point_store_only_when_explicitly_enabled(
    tmp_path,
) -> None:
    with client_at(tmp_path) as client:
        workspace_view, node_view, _, _ = seeded(client)
        source = read(client, workspace_view, node_view)
        policy = AssessmentPointPolicyService(SnapshotReader(source))
        service = AssessmentService(client.app.state.database, point_policy=policy)

        with client.app.state.database.connect() as db:
            workspace = db.execute(
                "SELECT * FROM learning_workspaces WHERE id=?", (workspace_view["id"],)
            ).fetchone()
            node = service._atomic_node(db, workspace, node_view["id"])
            setup = service.setup(
                db, workspace, node_view["id"], content_language="en"
            )
            config, items = service.freeze_configuration(
                db,
                workspace,
                node,
                setup["default_slots"],
                intent_id="service-one-point",
                content_language="en",
            )
            reread = service.configuration_slots(db, config["id"])

        assert setup["policy_version"] == "cj.assessment.points.v1"
        assert setup["minimum_questions"] == 1
        assert len(items) == len(reread) == 1
        assert reread[0].primary_point_id == "point-density-boundary"
