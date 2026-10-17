from types import SimpleNamespace

import pytest

from app.errors import ApiError
from app.learning.assessments import AssessmentService


class Result:
    def __init__(self, *, one=None, rows=()) -> None:
        self.one = one
        self.rows = list(rows)

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.rows


class PointSelectionConnection:
    def execute(self, sql, _params=()):
        if "SELECT policy_version,spec_version FROM assessment_configurations" in sql:
            return Result(
                one={"policy_version": "cj.assessment.points.v1", "spec_version": 3}
            )
        if "FROM assessment_configuration_questions" in sql:
            return Result(rows=[])
        raise AssertionError(sql)


def point_slot():
    return SimpleNamespace(
        slot_key="slot-1",
        ordinal=1,
        question_type="SHORT_TEXT",
        task_form="concept",
        marks=100,
        marks_basis_points=10_000,
        primary_point_id="point-1",
    )


def test_point_configuration_never_substitutes_a_type_compatible_legacy_question():
    service = AssessmentService(SimpleNamespace())
    service.configuration_slots = lambda *_args: (point_slot(),)  # type: ignore[method-assign]
    service._eligible_pool = lambda *_args: [  # type: ignore[method-assign]
        {
            "id": "legacy-ready",
            "question_type": "SHORT_TEXT",
            "family_id": "legacy-family",
        }
    ]
    workspace = {
        "id": "workspace",
        "owner_user_id": "owner",
        "course_id": "course",
    }
    node = {"id": "node", "spec_version": 3}

    with pytest.raises(ApiError) as raised:
        service.select_configuration(
            PointSelectionConnection(), workspace, node, "point-config"
        )

    assert raised.value.code == "ASSESSMENT_CONFIGURATION_POOL_INSUFFICIENT"
    assert "point" in raised.value.message.lower()


def test_generated_point_question_requires_current_ready_verifier():
    calls = []
    service = AssessmentService(
        SimpleNamespace(),
        point_ready_verifier=lambda workspace, node, question_id: calls.append(
            (workspace["id"], node["id"], question_id)
        )
        or False,
    )
    service._question_engine_revision_is_current = lambda *_args: True  # type: ignore[method-assign]
    service._rubric = lambda *_args: [object()]  # type: ignore[method-assign]
    connection = SimpleNamespace(
        execute=lambda *_args: Result(
            rows=[
                {"id": "legacy-ready"},
                {"id": "pointqe_generated"},
                {"id": "pointdet_generated"},
            ]
        )
    )
    workspace = {
        "id": "workspace",
        "owner_user_id": "owner",
        "course_id": "course",
    }
    node = {"id": "node", "spec_version": 3}

    eligible = service._eligible_pool(connection, workspace, node)

    assert [row["id"] for row in eligible] == ["legacy-ready"]
    assert calls == [
        ("workspace", "node", "pointqe_generated"),
        ("workspace", "node", "pointdet_generated"),
    ]
