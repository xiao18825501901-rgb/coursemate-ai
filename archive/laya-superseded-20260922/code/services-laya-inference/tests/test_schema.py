"""Request schema validation: finite numerics, safe ids, size caps."""

from __future__ import annotations

import pytest
from app.schema import DecisionRequest
from pydantic import ValidationError


def _base() -> dict:
    return {
        "request_id": "req-0001",
        "decision_definition_id": "course-triage",
        "definition_version": "1",
        "compiled_state": {"body": "hello"},
        "questions": {"q": {"type": "noul", "instructions": "is it true?"}},
        "deadline_ms": 5000,
        "model_revision": "1c5edc17a7acd8701df6fc341c0d179f1c62c982",
        "compiler_version": "1.0.0",
    }


def test_valid_request_parses() -> None:
    req = DecisionRequest.model_validate(_base())
    assert req.request_id == "req-0001"
    assert req.deadline_ms == 5000


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_deadline_must_be_finite(bad: float) -> None:
    payload = _base()
    payload["deadline_ms"] = bad
    with pytest.raises(ValidationError):
        DecisionRequest.model_validate(payload)


def test_deadline_must_be_positive() -> None:
    payload = _base()
    payload["deadline_ms"] = 0
    with pytest.raises(ValidationError):
        DecisionRequest.model_validate(payload)


def test_request_id_charset_is_restricted() -> None:
    payload = _base()
    payload["request_id"] = "bad\nid\nwith\nnewlines"
    with pytest.raises(ValidationError):
        DecisionRequest.model_validate(payload)


def test_request_id_length_cap() -> None:
    payload = _base()
    payload["request_id"] = "x" * 200
    with pytest.raises(ValidationError):
        DecisionRequest.model_validate(payload)


def test_empty_questions_rejected() -> None:
    payload = _base()
    payload["questions"] = {}
    with pytest.raises(ValidationError):
        DecisionRequest.model_validate(payload)


def test_too_many_questions_rejected() -> None:
    payload = _base()
    payload["questions"] = {
        f"q{i}": {"type": "noul", "instructions": "x"} for i in range(101)
    }
    with pytest.raises(ValidationError):
        DecisionRequest.model_validate(payload)


def test_oversized_instructions_rejected() -> None:
    payload = _base()
    payload["questions"] = {"q": {"type": "noul", "instructions": "x" * 3000}}
    with pytest.raises(ValidationError):
        DecisionRequest.model_validate(payload)


def test_choice_criteria_may_be_list() -> None:
    payload = _base()
    payload["questions"] = {
        "q": {"type": "choice", "instructions": "pick", "criteria": ["a", "b"]}
    }
    req = DecisionRequest.model_validate(payload)
    assert req.questions["q"].criteria == ["a", "b"]


def test_compiled_state_accepts_string() -> None:
    payload = _base()
    payload["compiled_state"] = "a plain string state"
    req = DecisionRequest.model_validate(payload)
    assert req.compiled_state == "a plain string state"


def test_compiled_state_size_cap() -> None:
    payload = _base()
    payload["compiled_state"] = "x" * 300_000
    with pytest.raises(ValidationError):
        DecisionRequest.model_validate(payload)
