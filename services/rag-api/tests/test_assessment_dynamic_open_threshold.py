from contextlib import nullcontext
from types import SimpleNamespace

from app.learning.models import AssessmentStartInput, PointSlotSelection
from app.learning.orchestrator import LearningOrchestrator


class Assessments:
    def _atomic_node(self, _db, _workspace, node_id):
        return {"id": node_id}

    def freeze_configuration(self, *_args, **_kwargs):
        return {"id": "point-config"}, ()

    def select_configuration(self, *_args, **_kwargs):
        return [
            {"family_id": "family-1"},
            {"family_id": "family-2"},
        ], ()

    def start(self, _db, _workspace, node_id, *, configuration_id):
        assert configuration_id == "point-config"
        return {"id": "dynamic-session", "node_id": node_id}


def test_ready_dynamic_configuration_opens_below_legacy_five_threshold(monkeypatch):
    subject = object.__new__(LearningOrchestrator)
    subject.db = SimpleNamespace(connect=lambda: nullcontext(object()))
    subject.assessments = Assessments()
    subject.cursor = lambda *_args, **_kwargs: None
    subject.prepare_pool = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("legacy pool preparation must not gate a ready dynamic configuration")
    )
    subject.prepare_configured_pool = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("a ready configuration must not be prepared again")
    )
    subject.operate = (
        lambda _workspace_id, _owner, _request, _kind, _prepare, save, **_kwargs: save(
            object(), {"id": "workspace"}, None
        )
    )
    monkeypatch.setattr(
        "app.learning.orchestrator.workspace_for",
        lambda *_args, **_kwargs: {"id": "workspace", "course_id": "course"},
    )
    request = AssessmentStartInput(
        operation_id="dynamic-open",
        revision=1,
        node_id="node",
        client_intent_id="intent",
        content_language="en",
        slots=[
            PointSlotSelection(
                slot_id=f"slot-{index}",
                question_type="SHORT_TEXT",
                task_form="concept",
                primary_point_id=f"point-{index}",
                independently_scored_parts=1,
            )
            for index in (1, 2)
        ],
    )

    result = subject.start_assessment("workspace", "owner", request)

    assert result["id"] == "dynamic-session"
