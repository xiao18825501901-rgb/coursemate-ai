"""The live Jev predictor's contract, checked without a network call.

The predictor is the piece that turns a labelled dataset row into a real gateway call and back into
the harness's answer shape. Its translation and its two discretisations are exactly where a
measurement could quietly become wrong, so they are pinned here against a transport that returns
scripted answers: the same code path the live run takes, with the network replaced.
"""

from __future__ import annotations

from app.evaluation.jev_semantic_ablation import (
    QUESTION_KEY,
    JevTransport,
    live_jev_predictor,
)
from app.jev.models import JevAnswer, JevResult


class ScriptedTransport(JevTransport):
    """Returns one scripted answer per call and records the calls it received."""

    def __init__(self, answer: JevAnswer) -> None:
        self.answer = answer
        self.calls: list[object] = []

    def call(self, call: object, *, timeout_seconds: float) -> JevResult:
        self.calls.append((call, timeout_seconds))
        return JevResult(
            answers={QUESTION_KEY: self.answer}, request_id="req-1", model_version="scripted"
        )


class Sample:
    """The subset of `JevJudgment` the predictor reads."""

    def __init__(self, definition_id: str, question: dict, state: dict) -> None:
        self.sample_id = "sample-1"
        self.definition_id = definition_id
        self.questions = {QUESTION_KEY: question}
        self.state = state


def _predict(definition_id: str, question: dict, answer: JevAnswer, state=None):
    transport = ScriptedTransport(answer)
    calls: list[dict] = []
    predictor = live_jev_predictor(transport, calls=calls)
    sample = Sample(definition_id, question, state or {"claim": "c", "source_span": "s"})
    return predictor(sample), transport, calls


def test_a_choice_answer_is_translated_and_recorded() -> None:
    question = {
        "type": "choice",
        "instructions": "select a span",
        "criteria": {"s1": "one", "s2": "two", "NO_SUPPORT": "none"},
    }
    prediction, transport, calls = _predict(
        "source.select_span.v1", question, JevAnswer(choice="s2")
    )
    assert prediction == {"choice": "s2"}
    # The question the transport received carries the dataset's own criteria as id -> label.
    call, timeout = transport.calls[0]
    assert timeout == 60.0
    sent = call.questions[QUESTION_KEY]
    assert sent.criteria == {"s1": "one", "s2": "two", "NO_SUPPORT": "none"}
    assert calls[0]["prediction"] == {"choice": "s2"}
    assert calls[0]["raw_choice"] == "s2"


def test_a_score_answer_becomes_the_declared_level_description_list() -> None:
    question = {
        "type": "score",
        "instructions": "score relevance",
        "criteria": {"0": "unrelated", "1": "weak", "2": "partial", "3": "direct", "4": "exact"},
    }
    prediction, transport, _calls = _predict(
        "retrieval.support.v1", question, JevAnswer(score_value=3.99)
    )
    sent = transport.calls[0][0].questions[QUESTION_KEY]
    assert sent.criteria == ["unrelated", "weak", "partial", "direct", "exact"], (
        "the level descriptions must be sent in declared order"
    )
    # 3.99 rounds to the nearest declared level, which is the metric's comparison, not a boundary.
    assert prediction == {"score_index": 4}


def test_a_score_level_key_is_used_directly() -> None:
    question = {
        "type": "score",
        "instructions": "score relevance",
        "criteria": {"0": "a", "1": "b", "2": "c", "3": "d", "4": "e"},
    }
    prediction, _transport, _calls = _predict(
        "retrieval.support.v1", question, JevAnswer(score="2")
    )
    assert prediction == {"score_index": 2}


def test_a_noul_probability_becomes_the_boolean_label_at_one_half() -> None:
    question = {"type": "noul", "instructions": "does it support?", "criteria": {}}
    high, _t, _c = _predict("source.supports_claim.v1", question, JevAnswer(noul=0.98))
    low, _t2, _c2 = _predict("source.supports_claim.v1", question, JevAnswer(noul=0.01))
    assert high == {"noul": True}
    assert low == {"noul": False}


def test_a_transport_that_returns_nothing_is_recorded_as_no_prediction() -> None:
    question = {"type": "noul", "instructions": "x", "criteria": {}}
    transport = ScriptedTransport(JevAnswer())
    calls: list[dict] = []
    predictor = live_jev_predictor(transport, calls=calls)
    # A transport that answered with an empty answer: the predictor must not invent one.
    prediction = predictor(Sample("source.supports_claim.v1", question, {}))
    assert prediction == {"noul": False}, "an absent probability is not a positive answer"
    assert calls[0]["raw_noul"] is None


def test_the_recorded_call_carries_what_the_model_actually_said() -> None:
    question = {
        "type": "score",
        "instructions": "score relevance",
        "criteria": {"0": "a", "1": "b", "2": "c", "3": "d", "4": "e"},
    }
    _prediction, _transport, calls = _predict(
        "retrieval.support.v1", question, JevAnswer(score_value=1.77)
    )
    record = calls[0]
    assert record["raw_score_value"] == 1.77, "the continuous value must survive into the evidence"
    assert record["definition_id"] == "retrieval.support.v1"
    assert record["question_type"] == "score"
    assert record["model_version"] == "scripted"
    assert isinstance(record["latency_ms"], float)
