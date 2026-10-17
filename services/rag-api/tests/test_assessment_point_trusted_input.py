from types import SimpleNamespace

import pytest

from test_assessment_point_sources import read, seeded
from test_assessment_point_store_unit import SnapshotReader
from test_learning_workspace import client_at

from app.errors import ApiError
from app.learning.assessment_point_configuration import AssessmentPointPolicyService
from app.learning.assessment_point_dispatch import resolve_point_dispatch
from app.learning.assessment_point_store import AssessmentPointConfigurationStore
from app.learning.assessments import AssessmentService
from app.learning.question_runtime import QuestionEngineRuntime


def frozen_case(tmp_path):
    context = client_at(tmp_path)
    client = context.__enter__()
    workspace_view, node_view, _, _ = seeded(client)
    source = read(client, workspace_view, node_view)
    policy = AssessmentPointPolicyService(SnapshotReader(source))
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
            intent_id="trusted-point-input",
            content_language="en",
        )
    return context, client, workspace, node, store, configuration, slots


def test_trusted_host_builds_point_input_from_original_frozen_source(tmp_path):
    context, client, workspace, node, store, configuration, slots = frozen_case(tmp_path)
    try:
        runtime = QuestionEngineRuntime(
            database=client.app.state.database,
            provider=SimpleNamespace(),
            semantic_decisions=None,
            point_store=store,
        )
        point_input = runtime.point_question_inputs(
            owner_user_id=workspace["owner_user_id"],
            workspace_id=workspace["id"],
            course_id=workspace["course_id"],
            private_course_id=workspace["private_course_id"],
            node_id=node["id"],
            configuration_id=configuration["id"],
            slots=slots,
            content_language="en",
        )[0]
    finally:
        context.__exit__(None, None, None)

    assert point_input.configuration_id == configuration["id"]
    assert point_input.point_slot.model_dump(mode="json") == slots[0].model_dump(
        mode="json"
    )
    assert [target.item_id for target in point_input.targets] == list(
        slots[0].original_target_item_ids
    )
    assert point_input.targets[0].evidence.objective_id == point_input.targets[0].item_id
    assert point_input.point_slot.marks_basis_points == 10_000
    assert len(point_input.identity()) == 64


def test_dispatch_rejects_a_caller_modified_point_slot(tmp_path):
    context, client, workspace, node, store, configuration, slots = frozen_case(tmp_path)
    changed = slots[0].model_copy(deep=True)
    changed.verified_point.constraints.append("caller supplied condition")
    try:
        with pytest.raises(ApiError) as raised:
            resolve_point_dispatch(
                client.app.state.database,
                store,
                owner_user_id=workspace["owner_user_id"],
                workspace_id=workspace["id"],
                course_id=workspace["course_id"],
                private_course_id=workspace["private_course_id"],
                node_id=node["id"],
                configuration_id=configuration["id"],
                slots=(changed,),
                content_language="en",
            )
    finally:
        context.__exit__(None, None, None)

    assert raised.value.code == "ASSESSMENT_POINT_SLOT_MISMATCH"
