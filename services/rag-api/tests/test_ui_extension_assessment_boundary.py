from __future__ import annotations

import pytest

from app.errors import ApiError
from app.learning.models import PointSlotSelection
from app.ui_extension.domain import V3DomainAdapter


def test_invalid_assessment_submission_becomes_structured_422_not_pydantic_500() -> None:
    """The refreshed UI boundary must never leak Pydantic validation as HTTP 500."""

    domain = object.__new__(V3DomainAdapter)
    domain.learning = object()
    domain._course_row = lambda _course, _subject: {"id": "ge2324"}  # type: ignore[method-assign]
    domain._workspace_for_node = lambda _course, _subject: {"id": "workspace-1"}  # type: ignore[method-assign]

    with pytest.raises(ApiError) as raised:
        domain._assessment_submit(
            "owner-1",
            {
                "course": "ge2324",
                "session": "session-1",
                "request_id": "submit-invalid-1",
                "answers": [],
                "unified_answer": "",
                "attachments": [],
                "confirm_unanswered": [],
            },
        )

    assert raised.value.status_code == 422
    assert raised.value.code == "ASSESSMENT_SUBMISSION_INVALID"
    assert "answer" in raised.value.message.lower()


def test_dynamic_point_configuration_survives_the_public_ui_adapter() -> None:
    captured = {}

    class Learning:
        def start_assessment(self, workspace_id, subject, request):
            captured.update(
                workspace_id=workspace_id,
                subject=subject,
                request=request,
            )
            return {"status": "PREPARING"}

    domain = object.__new__(V3DomainAdapter)
    domain.learning = Learning()
    domain._course_row = lambda _course, _subject: {"id": "cs3481"}  # type: ignore[method-assign]
    domain._workspace_for_node = lambda _course, _subject: {"id": "workspace-1"}  # type: ignore[method-assign]
    domain._workspace_revision = lambda _workspace: 7  # type: ignore[method-assign]

    result = domain._assessment_start(
        "owner-1",
        {
            "course": "cs3481",
            "node": "node-1",
            "request_id": "dynamic-start-1",
            "client_intent_id": "intent-1",
            "intent_action": "CONFIGURE",
            "content_language": "en",
            "slots": [
                {
                    "slot_id": "point-item-1",
                    "question_type": "SHORT_TEXT",
                    "task_form": "definition",
                    "primary_point_id": "point-degree",
                    "variation_purpose": None,
                    "independently_scored_parts": 1,
                }
            ],
        },
    )

    request = captured["request"]
    assert result == {"status": "PREPARING"}
    assert request.client_intent_id == "intent-1"
    assert request.intent_action == "CONFIGURE"
    assert request.content_language == "en"
    assert isinstance(request.slots[0], PointSlotSelection)
    assert request.slots[0].primary_point_id == "point-degree"


def test_dynamic_point_setup_passes_explicit_content_language() -> None:
    captured = {}

    class Learning:
        def assessment_setup(self, workspace_id, subject, node_id, *, content_language=None):
            captured.update(
                workspace_id=workspace_id,
                subject=subject,
                node_id=node_id,
                content_language=content_language,
            )
            return {"status": "READY"}

    domain = object.__new__(V3DomainAdapter)
    domain.learning = Learning()
    domain._course_row = lambda _course, _subject: {"id": "cs3481"}  # type: ignore[method-assign]
    domain._workspace_for_node = lambda _course, _subject: {"id": "workspace-1"}  # type: ignore[method-assign]

    assert domain._assessment_setup(
        "owner-1",
        {
            "course": "cs3481",
            "node": "node-1",
            "content_language": "zh-CN",
        },
    ) == {"status": "READY"}
    assert captured["content_language"] == "zh-CN"
