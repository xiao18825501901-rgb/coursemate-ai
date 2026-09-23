"""The DeepSeek baseline predictor's contract, checked without a network call.

This is the side of the ablation comparison that must be exactly as fair as the Jev side: same
question, same options, and an unusable answer counted as an abstention rather than as a wrong one.
The tests below drive it with a scripted transport, so the parsing and the refusals are verified
without spending a call.
"""

from __future__ import annotations

import pytest

from app.evaluation.jev_deepseek_baseline import (
    FRAMING,
    deepseek_baseline_predictor,
)


class Sample:
    def __init__(self, question: dict, state: dict | None = None) -> None:
        self.sample_id = "sample-1"
        self.definition_id = "retrieval.support.v1"
        self.questions = {"q": question}
        self.state = state or {"query": "q", "candidate_text": "text"}


def _responses(text: str, *, input_tokens: int = 10, output_tokens: int = 5) -> dict:
    return {
        "output": [{"content": [{"type": "output_text", "text": text}]}],
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


def _transport_returning(text: str):
    sent: list[tuple[str, dict]] = []

    def transport(endpoint: str, payload: dict) -> dict:
        sent.append((endpoint, payload))
        return _responses(text)

    return transport, sent


def test_a_choice_answer_is_only_accepted_from_the_supplied_options() -> None:
    question = {
        "type": "choice",
        "instructions": "select a span",
        "criteria": {"s1": "one", "s2": "two"},
    }
    transport, sent = _transport_returning('{"answer": "s2"}')
    predict = deepseek_baseline_predictor(transport, base_url="https://api.deepseek.com")
    assert predict(Sample(question)) == {"choice": "s2"}

    endpoint, payload = sent[0]
    assert endpoint == "https://api.deepseek.com/responses"
    assert payload["reasoning"] == {"effort": "none"}, "the model needs thinking disabled to finish"
    assert payload["stream"] is False
    # The prompt carries the dataset's own option ids, so the baseline cannot invent one.
    assert "s1: one" in payload["input"] and "s2: two" in payload["input"]
    assert payload["instructions"] == FRAMING


def test_an_answer_outside_the_options_is_an_abstention() -> None:
    question = {"type": "choice", "instructions": "x", "criteria": {"s1": "one", "s2": "two"}}
    transport, _sent = _transport_returning('{"answer": "s9"}')
    calls: list[dict] = []
    predict = deepseek_baseline_predictor(
        transport, base_url="https://api.deepseek.com", calls=calls
    )
    assert predict(Sample(question)) is None
    assert calls[0]["status"] == "invalid_answer", "the reason must be recorded, not hidden"


def test_a_score_answer_must_be_an_integer_inside_the_scale() -> None:
    question = {
        "type": "score",
        "instructions": "score it",
        "criteria": {"0": "a", "1": "b", "2": "c"},
    }
    good, _ = _transport_returning('{"score_index": 2}')
    out_of_range, _ = _transport_returning('{"score_index": 7}')
    fractional, _ = _transport_returning('{"score_index": 1.5}')
    base = "https://api.deepseek.com"
    assert deepseek_baseline_predictor(good, base_url=base)(Sample(question)) == {"score_index": 2}
    assert deepseek_baseline_predictor(out_of_range, base_url=base)(Sample(question)) is None
    assert deepseek_baseline_predictor(fractional, base_url=base)(Sample(question)) is None


def test_a_noul_answer_must_be_boolean() -> None:
    question = {"type": "noul", "instructions": "does it support?", "criteria": {}}
    yes, _ = _transport_returning('{"answer": true}')
    text, _ = _transport_returning('{"answer": "yes"}')
    base = "https://api.deepseek.com"
    assert deepseek_baseline_predictor(yes, base_url=base)(Sample(question)) == {"noul": True}
    assert deepseek_baseline_predictor(text, base_url=base)(Sample(question)) is None


def test_an_unparsable_or_missing_answer_is_an_abstention_with_its_reason() -> None:
    question = {"type": "noul", "instructions": "x", "criteria": {}}
    base = "https://api.deepseek.com"
    for text, status in (("not json at all", "unparsable"), ("", "unparsable")):
        transport, _ = _transport_returning(text)
        calls: list[dict] = []
        predictor = deepseek_baseline_predictor(transport, base_url=base, calls=calls)
        assert predictor(Sample(question)) is None
        assert calls[0]["status"] == status

    empty_transport = lambda endpoint, payload: {"output": []}  # noqa: E731
    calls = []
    predictor = deepseek_baseline_predictor(empty_transport, base_url=base, calls=calls)
    assert predictor(Sample(question)) is None
    assert calls[0]["status"] == "no_text"


def test_a_transport_failure_never_crashes_the_run() -> None:
    def broken(endpoint: str, payload: dict) -> dict:
        raise RuntimeError("PROVIDER_HTTP_500")

    question = {"type": "noul", "instructions": "x", "criteria": {}}
    calls: list[dict] = []
    predictor = deepseek_baseline_predictor(
        broken, base_url="https://api.deepseek.com", calls=calls
    )
    assert predictor(Sample(question)) is None
    assert calls[0]["status"] == "transport_failed"
    assert calls[0]["error"] == "RuntimeError"


def test_the_reported_usage_is_recorded_for_cost_accounting() -> None:
    question = {"type": "noul", "instructions": "x", "criteria": {}}
    transport, _ = _transport_returning('{"answer": false}')
    calls: list[dict] = []
    predictor = deepseek_baseline_predictor(
        transport, base_url="https://api.deepseek.com", calls=calls
    )
    assert predictor(Sample(question)) == {"noul": False}
    assert calls[0]["input_tokens"] == 10
    assert calls[0]["output_tokens"] == 5
    assert calls[0]["status"] == "answered"


@pytest.mark.parametrize("base", ["https://api.deepseek.com", "https://api.deepseek.com/"])
def test_the_endpoint_is_normalised(base: str) -> None:
    question = {"type": "noul", "instructions": "x", "criteria": {}}
    transport, sent = _transport_returning('{"answer": true}')
    deepseek_baseline_predictor(transport, base_url=base)(Sample(question))
    assert sent[0][0] == "https://api.deepseek.com/responses"
