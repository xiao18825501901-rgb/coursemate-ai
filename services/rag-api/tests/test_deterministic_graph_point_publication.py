import json
from types import SimpleNamespace

from test_learning_journey import setup_workspace
from test_learning_workspace import client_at

from app.learning.assessment_point_catalog_models import (
    CatalogScope,
    VerifiedCatalog,
    VerifiedPoint,
)
from app.learning.assessment_point_configuration import AssessmentPointPolicyService
from app.learning.assessment_point_store import AssessmentPointConfigurationStore
from app.learning.assessments import AssessmentService
from app.learning.deterministic_graph_point_assessment import (
    DeterministicGraphPointPublisher,
)
from app.learning.orchestrator import LearningOrchestrator
from app.learning.models import AssessmentAnswer
from app.learning.question_runtime import QuestionEngineRuntime
from app.learning.structured_calls import ModelCallClaim


GRAPH_SOURCE = (
    "In an undirected graph, the degree of a vertex is the number of incident edges. "
    "The sum of all vertex degrees equals twice the number of edges."
)


class GraphCatalogReader:
    def __init__(self, source) -> None:
        target = source.targets[0]
        fragment = target.fragments[0]
        point = VerifiedPoint.model_validate(
            {
                "point_id": "point-degree-definition",
                "canonical_key": target.objective_id,
                "objective": target.objective_text,
                "constraints": [fragment.content],
                "scoring_evidence": [target.acceptance],
                "allowed_forms": ["SHORT_TEXT"],
                "sequence": 0,
                "source_refs": [
                    {
                        "source_id": fragment.evidence_id,
                        "document_id": fragment.document_id,
                        "document_version": fragment.document_version_id,
                        "locator": f"{fragment.locator_type}:{fragment.locator_value}",
                        "scope_key": "owner:course:source",
                    }
                ],
                "validation_receipt_id": "review:controlled",
            }
        )
        self.catalog = VerifiedCatalog(
            catalog_id="catalog:graph-degree",
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
        assert language == "en"
        assert source.identity() == self.catalog.scope.source_snapshot
        return self.catalog, self.targets


def graph_case(client):
    from app.learning.assessment_point_sources import freeze_point_sources

    workspace, _ = setup_workspace(client)
    uploaded = client.post(
        f"/api/learning/workspaces/{workspace['id']}/documents",
        files={"file": ("graph.txt", GRAPH_SOURCE.encode(), "text/plain")},
    )
    assert uploaded.status_code == 202, uploaded.text
    document_id = uploaded.json()["document"]["id"]
    with client.app.state.database.connect() as db:
        chunk = db.execute(
            "SELECT id FROM chunks WHERE document_id=? ORDER BY ordinal", (document_id,)
        ).fetchone()
    node = client.post(
        f"/api/learning/workspaces/{workspace['id']}/nodes",
        json={
            "title": "Graph degree",
            "description": "Finite undirected graph degree",
            "major": "CS",
            "kind": "ATOMIC",
            "items": [
                {
                    "item_id": "vd_degree_definition_required",
                    "requirement": "REQUIRED",
                    "objective": "Define and calculate degree in an undirected graph",
                    "acceptance": "State the definition and calculate every requested degree",
                    "evidence_ids": [chunk["id"]],
                }
            ],
        },
    )
    assert node.status_code == 200, node.text
    source = freeze_point_sources(
        client.app.state.database,
        workspace_id=workspace["id"],
        owner="a",
        node_id=node.json()["id"],
    )
    return workspace, node.json(), source


def test_deterministic_graph_point_publishes_ready_with_zero_model_calls(tmp_path):
    with client_at(tmp_path) as client:
        workspace_view, node_view, source = graph_case(client)
        policy = AssessmentPointPolicyService(GraphCatalogReader(source))
        store = AssessmentPointConfigurationStore(client.app.state.database, policy)
        with client.app.state.database.connect() as db:
            workspace = db.execute(
                "SELECT * FROM learning_workspaces WHERE id=?", (workspace_view["id"],)
            ).fetchone()
            node = AssessmentService._atomic_node(db, workspace, node_view["id"])
            configuration, slots = store.freeze(
                db,
                workspace,
                node,
                policy.setup(source, "en")["default_slots"],
                requested_id=None,
                intent_id="graph-deterministic",
                content_language="en",
            )
        runtime = QuestionEngineRuntime(
            database=client.app.state.database,
            provider=SimpleNamespace(),
            semantic_decisions=None,
            point_store=store,
        )
        args = {
            "owner_user_id": workspace["owner_user_id"],
            "workspace_id": workspace["id"],
            "course_id": workspace["course_id"],
            "private_course_id": workspace["private_course_id"],
            "node_id": node["id"],
            "configuration_id": configuration["id"],
            "slots": slots,
            "content_language": "en",
        }
        point_input = runtime.point_question_inputs(**args)[0]

        def verify(claim, supplied):
            claim.verify()
            assert runtime.point_question_inputs(**args)[0].identity() == supplied.identity()

        publisher = DeterministicGraphPointPublisher(client.app.state.database, verify)
        claim = ModelCallClaim(
            request_id="deterministic-graph",
            owner_user_id=workspace["owner_user_id"],
            course_id=workspace["course_id"],
            content_language="en",
            verify=lambda: None,
        )
        result = publisher.prepare_or_read(claim, point_input)
        replay = publisher.prepare_or_read(claim, point_input)
        prepared = runtime.generate_assessment_set(
            owner_user_id=workspace["owner_user_id"],
            workspace_id=workspace["id"],
            course_id=workspace["course_id"],
            private_course_id=workspace["private_course_id"],
            node_id=node["id"],
            preparation_key=configuration["id"],
            slots=slots,
        )
        service = AssessmentService(
            client.app.state.database,
            point_policy=policy,
            point_ready_verifier=runtime.point_ready_for,
        )
        with client.app.state.database.connect() as db:
            selected, selected_slots = service.select_configuration(
                db, workspace, node, configuration["id"]
            )
            stored = {
                **dict(selected[0]),
                "answer_key": json.loads(selected[0]["answer_json"]),
            }
        with client.app.state.database.connect() as db:
            bound = db.execute(
                "SELECT question_revision_id FROM assessment_configuration_questions "
                "WHERE configuration_id=?",
                (configuration["id"],),
            ).fetchone()
            calls = db.execute("SELECT COUNT(*) FROM generic_llm_calls").fetchone()[0]

    assert result is not None and result.status == "READY"
    assert result.verification_method == "DETERMINISTIC"
    assert replay is not None and replay.idempotent is True
    assert prepared[0]["question_revision_id"] == result.question_revision_id
    assert prepared[0]["verification_status"] == "DETERMINISTIC"
    assert prepared[0]["usage"] == []
    assert selected[0]["id"] == result.question_revision_id
    assert selected_slots[0].primary_point_id == "point-degree-definition"
    assert AssessmentService._is_deterministic(stored) is True
    assert bound["question_revision_id"] == result.question_revision_id
    assert calls == 0


def test_configured_worker_prepares_graph_slot_and_reports_ready(tmp_path):
    with client_at(tmp_path) as client:
        workspace_view, node_view, source = graph_case(client)
        policy = AssessmentPointPolicyService(GraphCatalogReader(source))
        service = AssessmentService(client.app.state.database, point_policy=policy)
        store = service.point_store
        assert store is not None
        with client.app.state.database.connect() as db:
            workspace = db.execute(
                "SELECT * FROM learning_workspaces WHERE id=?", (workspace_view["id"],)
            ).fetchone()
            node = service._atomic_node(db, workspace, node_view["id"])
            configuration, _slots = store.freeze(
                db,
                workspace,
                node,
                policy.setup(source, "en")["default_slots"],
                requested_id=None,
                intent_id="graph-worker",
                content_language="en",
            )
            db.execute(
                "INSERT INTO assessment_configuration_preparations("
                "id,configuration_id,workspace_id,status,operation_id,attempt,total_slots,"
                "prepared_slots,current_stage) VALUES(?,?,?,'PREPARING',?,0,1,0,'QUEUED')",
                (
                    "graph-worker-preparation",
                    configuration["id"],
                    workspace["id"],
                    "graph-worker-operation",
                ),
            )
        subject = object.__new__(LearningOrchestrator)
        subject.db = client.app.state.database
        subject.assessments = service
        subject.question_engine = QuestionEngineRuntime(
            database=client.app.state.database,
            provider=SimpleNamespace(),
            semantic_decisions=None,
            point_store=store,
        )
        service.point_ready_verifier = subject.question_engine.point_ready_for

        result = subject.run_configured_preparation_once("worker-one")
        with client.app.state.database.connect() as db:
            slot = db.execute(
                "SELECT status,current_stage FROM assessment_configuration_slot_preparations "
                "WHERE preparation_id='graph-worker-preparation'"
            ).fetchone()
            prep = db.execute(
                "SELECT status,prepared_slots FROM assessment_configuration_preparations "
                "WHERE id='graph-worker-preparation'"
            ).fetchone()
            calls = db.execute("SELECT COUNT(*) FROM generic_llm_calls").fetchone()[0]
            session = service.start(
                db,
                workspace,
                node["id"],
                configuration_id=configuration["id"],
            )
            answer = db.execute(
                "SELECT answer_json FROM assessment_question_revisions WHERE id=?",
                (session["questions"][0]["question_revision_id"],),
            ).fetchone()
            submitted = [
                AssessmentAnswer(
                    blueprint_item_id=session["questions"][0]["id"],
                    answer=json.loads(answer["answer_json"])["reference_answer"],
                )
            ]
            graded = service.save_submission(
                db,
                workspace,
                session["id"],
                submitted,
                proposal=None,
            )
        history = service.view(workspace["id"], workspace["owner_user_id"], session["id"])

    assert result == {
        "id": "graph-worker-preparation",
        "status": "READY",
        "prepared": 1,
    }
    assert prep["status"] == "READY" and prep["prepared_slots"] == 1
    assert slot["status"] == "READY"
    assert calls == 0
    assert session["status"] == "IN_PROGRESS"
    assert len(session["questions"]) == 1
    assert "answer_key" not in session["questions"][0]
    assert "reference_solution" not in session["questions"][0]
    assert graded["status"] == "GRADED"
    assert graded["raw_score"] == 100
    assert history["id"] == session["id"]
    assert history["status"] == "GRADED"
    assert history["raw_score"] == 100
