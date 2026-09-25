from __future__ import annotations

import pytest

from app.errors import ApiError
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
