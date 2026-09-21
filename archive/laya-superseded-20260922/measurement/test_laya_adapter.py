"""Unit tests for the Laya adapter: parsing, validation, transport and temperature."""

from __future__ import annotations

import json
import urllib.error

import pytest

from app.jev.catalog import load_catalog
from app.laya.adapter import (
    FakeLayaTransport,
    HttpLayaTransport,
    LayaConfig,
    _answer_from_raw,
    _concentration,
    _temperature_payload,
    _validate_answer,
    laya_question,
)
from app.laya.errors import LayaInvalidResponseError, LayaUnavailableError
from app.laya.models import LayaQuestion, LayaReply, LayaRequest, request_content_hash

CATALOG = load_catalog()
CHOICE = CATALOG.get("intent.next_action.v1")
SCORE = CATALOG.get("retrieval.support.v1")
NOUL = CATALOG.get("context.keep_segment.v1")
CHOICE_IDS = ("CONTINUE", "ANSWER_ONLY", "OTHER")


def _choice_q() -> LayaQuestion:
    return laya_question(CHOICE, criteria={cid: "" for cid in CHOICE_IDS})


def _score_q() -> LayaQuestion:
    return laya_question(SCORE)


def _noul_q() -> LayaQuestion:
    return laya_question(NOUL)


def _request() -> LayaRequest:
    return LayaRequest(
        definition_id="intent.next_action.v1",
        definition_version="1.0.0-design",
        state={"message": "继续"},
        questions={"intent.next_action.v1": _choice_q()},
        deadline_ms=0,
        request_id="r1",
        compiler_version="c1",
        model_revision="rev1",
    )


# ------------------------------------------------------------------ parsing
def test_answer_from_raw_choice() -> None:
    raw = {
        "type": "choice",
        "choice": "CONTINUE",
        "probabilities": {"CONTINUE": 0.8, "ANSWER_ONLY": 0.1, "OTHER": 0.1},
        "confidence": 0.63,
        "rl_agent": {"act_probability": 0.9},
    }
    answer = _answer_from_raw("choice", raw)
    assert answer.kind == "choice"
    assert answer.choice == "CONTINUE"
    assert answer.act_probability == 0.9
    assert answer.confidence_kind == "distribution_concentration"


def test_answer_from_raw_noul_has_no_confidence_or_probabilities() -> None:
    answer = _answer_from_raw("noul", {"type": "noul", "noul": 0.73})
    assert answer.noul == 0.73
    assert answer.confidence == 0.0
    assert answer.probabilities == {}


# ------------------------------------------------------------------ choice
def test_choice_valid_surfaces_concentration() -> None:
    answer = _validate_answer(
        _choice_q(),
        _answer_from_raw(
            "choice",
            {
                "choice": "CONTINUE",
                "probabilities": {"CONTINUE": 0.8, "ANSWER_ONLY": 0.1, "OTHER": 0.1},
                "confidence": 0.63,
            },
        ),
    )
    assert answer.choice == "CONTINUE"
    assert answer.confidence > 0
    assert answer.confidence_kind == "distribution_concentration"


def test_choice_rejects_invented_id() -> None:
    with pytest.raises(LayaInvalidResponseError):
        _validate_answer(
            _choice_q(),
            _answer_from_raw("choice", {"choice": "EVIL", "probabilities": {"EVIL": 1.0}}),
        )


def test_choice_rejects_invented_probability_key() -> None:
    with pytest.raises(LayaInvalidResponseError):
        _validate_answer(
            _choice_q(),
            _answer_from_raw(
                "choice",
                {
                    "choice": "CONTINUE",
                    "probabilities": {"CONTINUE": 0.5, "HACKED": 0.5},
                },
            ),
        )


def test_choice_rejects_nonfinite_probability() -> None:
    with pytest.raises(LayaInvalidResponseError):
        _validate_answer(
            _choice_q(),
            _answer_from_raw(
                "choice",
                {
                    "choice": "CONTINUE",
                    "probabilities": {"CONTINUE": float("nan"), "ANSWER_ONLY": 0.5, "OTHER": 0.5},
                },
            ),
        )


def test_choice_rejects_probability_mass_not_one() -> None:
    with pytest.raises(LayaInvalidResponseError):
        _validate_answer(
            _choice_q(),
            _answer_from_raw(
                "choice",
                {
                    "choice": "CONTINUE",
                    "probabilities": {"CONTINUE": 0.3, "ANSWER_ONLY": 0.2, "OTHER": 0.1},
                },
            ),
        )


# ------------------------------------------------------------------ score
def test_score_valid_and_exposes_legend() -> None:
    answer = _validate_answer(
        _score_q(),
        _answer_from_raw(
            "score",
            {
                "score": 3.1,
                "legend": {"0": "l0", "1": "l1", "2": "l2", "3": "l3", "4": "l4"},
                "probabilities": {"0": 0.0, "1": 0.0, "2": 0.1, "3": 0.8, "4": 0.1},
                "confidence": 0.5,
            },
        ),
    )
    assert answer.kind == "score"
    assert answer.score == 3.1
    assert answer.legend is not None and answer.legend["3"] == "l3"


def test_score_rejects_out_of_range_index() -> None:
    with pytest.raises(LayaInvalidResponseError):
        _validate_answer(
            _score_q(),
            _answer_from_raw("score", {"score": 9.0, "probabilities": {"4": 1.0}}),
        )


def test_score_confidence_falls_back_to_concentration() -> None:
    # confidence 0.0 (missing/uniform) is recomputed from a peak distribution -> ~1.0
    answer = _validate_answer(
        _score_q(),
        _answer_from_raw(
            "score",
            {
                "score": 2.0,
                "probabilities": {"0": 0.0, "1": 0.0, "2": 1.0, "3": 0.0, "4": 0.0},
                "confidence": 0.0,
            },
        ),
    )
    assert answer.confidence == pytest.approx(1.0)
    assert answer.confidence_kind == "distribution_concentration"


# ------------------------------------------------------------------ noul
def test_noul_uses_p_true_only_and_never_a_confidence() -> None:
    answer = _validate_answer(_noul_q(), _answer_from_raw("noul", {"noul": 0.73}))
    assert answer.noul == 0.73
    assert answer.confidence == 0.0
    assert answer.probabilities == {}


def test_noul_rejects_out_of_range() -> None:
    with pytest.raises(LayaInvalidResponseError):
        _validate_answer(_noul_q(), _answer_from_raw("noul", {"noul": 1.2}))


# ------------------------------------------------------------------ concentration
def test_concentration_peak_is_one_uniform_is_zero() -> None:
    assert _concentration([1.0, 0.0, 0.0]) == pytest.approx(1.0)
    assert _concentration([0.5, 0.5]) == pytest.approx(0.0)


# ------------------------------------------------------------------ temperature
def test_identity_temperature_records_none() -> None:
    assert _temperature_payload(LayaConfig()) is None


def test_calibration_temperature_is_recorded_explicitly() -> None:
    payload = json.loads(_temperature_payload(LayaConfig(temperature=(0.5, 1.0, 1.0))))
    assert payload["temperature"] == [0.5, 1.0, 1.0]


# ------------------------------------------------------------------ content hash
def test_request_content_hash_deterministic_and_order_independent() -> None:
    h1 = request_content_hash("x", "1.0.0", {"b": 2, "a": 1}, {"q": _choice_q()})
    h2 = request_content_hash("x", "1.0.0", {"a": 1, "b": 2}, {"q": _choice_q()})
    assert h1 == h2
    assert len(h1) == 64


# ------------------------------------------------------------------ http transport
class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


class _RecordingOpener:
    def __init__(self, payload: dict | None = None, error: Exception | None = None) -> None:
        self.payload = payload or {}
        self.error = error
        self.requests: list = []

    def open(self, req: object, timeout: float | None = None) -> _FakeResponse:  # noqa: ARG002
        self.requests.append(req)
        if self.error is not None:
            raise self.error
        return _FakeResponse(self.payload)


def _choice_payload(choice: str = "CONTINUE") -> dict:
    return {
        "answers": {
            "intent.next_action.v1": {
                "type": "choice",
                "choice": choice,
                "probabilities": {cid: (1.0 if cid == choice else 0.0) for cid in CHOICE_IDS},
                "confidence": 1.0,
                "rl_agent": {"act_probability": 0.9},
            }
        },
        "usage": {"input_tokens": 12, "output_tokens": 0},
    }


def test_http_transport_payload_shape_and_parse() -> None:
    opener = _RecordingOpener(payload=_choice_payload())
    transport = HttpLayaTransport(LayaConfig(base_url="http://laya.internal"), opener=opener)
    reply = transport.decide(_request())
    req = opener.requests[0]
    assert req.full_url == "http://laya.internal/system_one"
    assert req.get_method() == "POST"
    body = json.loads(req.data)
    assert body["questions"]["intent.next_action.v1"]["type"] == "choice"
    assert body["questions"]["intent.next_action.v1"]["criteria"] == {
        cid: "" for cid in CHOICE_IDS
    }
    assert reply.status == "ok"
    assert reply.answers["intent.next_action.v1"].choice == "CONTINUE"
    assert reply.diagnostics is not None
    assert reply.diagnostics.input_tokens == 12
    assert reply.diagnostics.option_count == 3
    assert len(reply.diagnostics.content_hash) == 64


def test_http_transport_never_adds_authorization_without_key() -> None:
    opener = _RecordingOpener(payload=_choice_payload())
    transport = HttpLayaTransport(LayaConfig(base_url="http://x", api_key=None), opener=opener)
    transport.decide(_request())
    assert opener.requests[0].headers.get("Authorization") is None


def test_http_transport_unconfigured_base_url() -> None:
    with pytest.raises(LayaUnavailableError):
        HttpLayaTransport(LayaConfig(base_url=None)).decide(_request())


def test_http_transport_network_error_maps_to_unavailable() -> None:
    opener = _RecordingOpener(error=urllib.error.URLError("boom"))
    transport = HttpLayaTransport(LayaConfig(base_url="http://laya.internal"), opener=opener)
    with pytest.raises(LayaUnavailableError):
        transport.decide(_request())


# ------------------------------------------------------------------ fake transport
def test_fake_transport_responder_dict() -> None:
    def responder(req: LayaRequest) -> dict:
        return _choice_payload("OTHER")

    transport = FakeLayaTransport(responder)
    reply = transport.decide(_request())
    assert reply.answers["intent.next_action.v1"].choice == "OTHER"


def test_fake_transport_passes_reply_through() -> None:
    raw = _choice_payload()["answers"]["intent.next_action.v1"]
    reply = LayaReply(answers={"q": _answer_from_raw("choice", raw)})
    transport = FakeLayaTransport(lambda req: reply)
    assert transport.decide(_request()) is reply


def test_fake_transport_raises_typed_error() -> None:
    def boom(req: LayaRequest) -> None:
        raise LayaUnavailableError("down")

    with pytest.raises(LayaUnavailableError):
        FakeLayaTransport(boom).decide(_request())
