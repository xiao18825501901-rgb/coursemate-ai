"""Gateway semantics: modes, invalid candidates, typed failures, no retry, receipts, batch."""

from __future__ import annotations

import pytest

from app.jev.catalog import load_catalog
from app.jev.errors import (
    JevError,
    JevInvalidResponseError,
    JevNotConfiguredError,
    JevRequestError,
    JevTimeoutError,
    JevUnavailableError,
)
from app.jev.gateway import (
    Decision,
    DecisionRequest,
    FakeTransport,
    GatewayBounds,
    JevGateway,
    Receipt,
    SdkTransport,
)
from app.jev.models import CacheScope, JevAnswer, JevResult

CATALOG = load_catalog()
CHOICE = CATALOG.get("intent.next_action.v1")
SCORE = CATALOG.get("retrieval.support.v1")
NOUL = CATALOG.get("context.keep_segment.v1")
CHOICE_IDS = ("CONTINUE", "ANSWER_ONLY", "OTHER")


class MemoryStore:
    def __init__(self) -> None:
        self.receipts: list[Receipt] = []

    def save(self, receipt: Receipt) -> None:
        self.receipts.append(receipt)

    def lookup(self, definition, cache_scope, *, provider_model_version):  # noqa: ANN001
        return None


def _choice_request(**overrides) -> DecisionRequest:
    params = {
        "definition": CHOICE,
        "state": {"message": "继续讲下一节"},
        "caller_role": "intent",
        "cache_scope": CacheScope(owner_scope_hash="owner-hash", course_id="cs3481"),
        "criteria": {cid: None for cid in CHOICE_IDS},
    }
    params.update(overrides)
    return DecisionRequest(**params)


def _score_request(**overrides) -> DecisionRequest:
    params = {
        "definition": SCORE,
        "state": {"query": "q", "candidate_id": "c1", "candidate_text": "text"},
        "caller_role": "retrieval",
        "cache_scope": CacheScope(owner_scope_hash="owner-hash"),
        "criteria": None,
    }
    params.update(overrides)
    return DecisionRequest(**params)


def _gateway(transport, *, store=None, modes=None) -> JevGateway:
    return JevGateway(
        transport=transport,
        catalog=CATALOG,
        modes=modes,
        receipt_store=store,
    )


def test_off_mode_makes_no_call_and_no_receipt() -> None:
    transport = FakeTransport(lambda call: JevResult(answers={}))
    store = MemoryStore()
    gateway = _gateway(transport, store=store, modes={"intent.next_action.v1": "off"})
    decision = gateway.evaluate(_choice_request())
    assert decision.outcome == "off"
    assert decision.suggestion is None
    assert decision.mode == "off"
    assert transport.calls == []
    assert store.receipts == []


def test_shadow_mode_calls_transport_and_records_suggestion() -> None:
    def responder(call):
        return JevResult(
            answers={"intent.next_action.v1": JevAnswer(choice="CONTINUE")},
            request_id="req-1",
        )

    transport = FakeTransport(responder)
    store = MemoryStore()
    gateway = _gateway(transport, store=store, modes={"intent.next_action.v1": "shadow"})
    decision = gateway.evaluate(_choice_request())
    assert decision.mode == "shadow"
    assert decision.outcome == "ok"
    assert decision.suggestion is not None and decision.suggestion.choice == "CONTINUE"
    assert len(transport.calls) == 1
    assert len(store.receipts) == 1
    assert store.receipts[0].mode == "shadow"


def test_on_mode_returns_suggestion() -> None:
    def responder(call):
        return JevResult(answers={"intent.next_action.v1": JevAnswer(choice="OTHER")})

    gateway = _gateway(FakeTransport(responder), modes={"intent.next_action.v1": "on"})
    decision = gateway.evaluate(_choice_request())
    assert decision.mode == "on"
    assert decision.suggestion is not None and decision.suggestion.choice == "OTHER"


def test_invalid_candidate_id_is_rejected() -> None:
    def responder(call):
        return JevResult(answers={"intent.next_action.v1": JevAnswer(choice="EVIL_ID")})

    gateway = _gateway(FakeTransport(responder), modes={"intent.next_action.v1": "on"})
    decision = gateway.evaluate(_choice_request())
    assert decision.outcome == "invalid_response"
    assert decision.suggestion is None


def test_timeout_maps_to_typed_outcome_without_retry() -> None:
    calls: list[int] = []

    def responder(call):
        calls.append(1)
        raise JevTimeoutError("slow")

    store = MemoryStore()
    gateway = _gateway(FakeTransport(responder), store=store, modes={"intent.next_action.v1": "on"})
    decision = gateway.evaluate(_choice_request())
    assert decision.outcome == "timeout"
    assert decision.suggestion is None
    assert len(calls) == 1  # no retry
    assert store.receipts[0].outcome == "timeout"


def test_unavailable_maps_to_typed_outcome() -> None:
    def responder(call):
        raise JevUnavailableError("down")

    gateway = _gateway(FakeTransport(responder), modes={"intent.next_action.v1": "on"})
    decision = gateway.evaluate(_choice_request())
    assert decision.outcome == "unavailable"
    assert decision.suggestion is None


def test_live_sdk_transport_raises_not_configured_without_key() -> None:
    transport = SdkTransport(api_key=None)
    from app.jev.models import JevCall, JevQuestion

    with pytest.raises(JevNotConfiguredError):
        transport.call(
            JevCall(state={}, questions={"q": JevQuestion("q", "Noul", "is this x?")}),
            timeout_seconds=1.0,
        )


def test_live_sdk_transport_disables_hidden_retries_and_passes_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    from types import SimpleNamespace

    typesafe_sdk = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "typesafe_sdk", typesafe_sdk)

    from app.jev.models import JevCall, JevQuestion

    captured = {}

    class Retry:
        def __init__(self, *, max_retries: int) -> None:
            captured["max_retries"] = max_retries

    class NoulQuestion:
        def __init__(self, *, instructions: str) -> None:
            self.instructions = instructions

    class Client:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def system_one(self, _state, _questions):
            return type(
                "Result",
                (),
                {
                    "nouls": {"q": type("NoulResult", (), {"noul": 0.75})()},
                    "choices": {},
                    "scores": {},
                    "request_id": "fake-sdk-request",
                },
            )()

    monkeypatch.setattr(typesafe_sdk, "RetryPolicy", Retry, raising=False)
    monkeypatch.setattr(typesafe_sdk, "Noul", NoulQuestion, raising=False)
    monkeypatch.setattr(typesafe_sdk, "TypeSafeClient", Client, raising=False)
    monkeypatch.setattr(typesafe_sdk, "Choice", object, raising=False)
    monkeypatch.setattr(typesafe_sdk, "Score", object, raising=False)

    result = SdkTransport(api_key="protected-test-key", model="jev-latest").call(
        JevCall(
            state={"synthetic": True},
            questions={"q": JevQuestion("q", "Noul", "is this synthetic?")},
        ),
        timeout_seconds=17.0,
    )

    assert captured["api_key"] == "protected-test-key"
    assert captured["model"] == "jev-latest"
    assert captured["max_retries"] == 0
    assert captured["timeout"] == 17.0
    assert result.answers["q"].noul == 0.75


def test_receipt_persists_input_hash_and_mode() -> None:
    def responder(call):
        return JevResult(
            answers={"retrieval.support.v1": JevAnswer(score="3")}, request_id="req-score"
        )

    store = MemoryStore()
    gateway = _gateway(FakeTransport(responder), store=store, modes={"retrieval.support.v1": "on"})
    decision = gateway.evaluate(_score_request())
    assert decision.outcome == "ok"
    receipt = store.receipts[0]
    assert receipt.input_hash == decision.input_hash
    assert receipt.input_hash
    assert receipt.mode == "on"
    assert receipt.primitive == "Score"
    assert receipt.caller_role == "retrieval"


def test_batch_limit_enforced() -> None:
    gateway = _gateway(FakeTransport(lambda call: JevResult(answers={})))
    requests = [_score_request() for _ in range(GatewayBounds().max_batch_questions + 1)]
    with pytest.raises(JevRequestError):
        gateway.evaluate_batch(requests)


def test_invalid_score_level_rejected() -> None:
    def responder(call):
        return JevResult(answers={"retrieval.support.v1": JevAnswer(score="99")})

    gateway = _gateway(FakeTransport(responder), modes={"retrieval.support.v1": "on"})
    decision = gateway.evaluate(_score_request())
    assert decision.outcome == "invalid_response"
    assert decision.suggestion is None


def test_a_live_decimal_score_on_the_scale_is_carried_without_inventing_a_level() -> None:
    """Measured behaviour of the live primitive: a decimal on the definition's own scale.

    `retrieval.support.v1` declares levels `0..4`; the live service answered `3.99` for a candidate
    that directly supports the query. That is a legitimate answer on that scale, so it is carried as
    the provider's own number — and `score` stays `None`, because which level `3.99` *is* depends on
    boundaries the catalogue explicitly leaves to calibration.
    """

    def responder(call):
        return JevResult(answers={"retrieval.support.v1": JevAnswer(score="3.99")})

    gateway = _gateway(FakeTransport(responder), modes={"retrieval.support.v1": "on"})
    decision = gateway.evaluate(_score_request())

    assert decision.outcome == "ok"
    assert decision.suggestion is not None
    assert decision.suggestion.score_value == 3.99
    assert decision.suggestion.score is None, "no level may be inferred from a decimal"


def test_a_decimal_outside_the_declared_scale_is_still_refused() -> None:
    """The scale is the definition's, so 4.01 on a 0..4 definition is not an answer."""

    def responder(call):
        return JevResult(answers={"retrieval.support.v1": JevAnswer(score="4.01")})

    gateway = _gateway(FakeTransport(responder), modes={"retrieval.support.v1": "on"})
    decision = gateway.evaluate(_score_request())
    assert decision.outcome == "invalid_response"
    assert decision.suggestion is None


def test_a_decimal_on_a_three_level_definition_is_carried_on_its_own_scale() -> None:
    """`feedback.severity.v1` declares `0..2`, and the live service answered `2.0` and `0.03`."""

    definition = CATALOG.get("feedback.severity.v1")

    def responder(call):
        return JevResult(answers={"feedback.severity.v1": JevAnswer(score="2.0")})

    gateway = _gateway(FakeTransport(responder), modes={"feedback.severity.v1": "on"})
    request = DecisionRequest(
        definition=definition,
        state={"user_report": "the grader marked my correct answer wrong", "category": "GRADING"},
        caller_role="feedback",
        cache_scope=CacheScope(owner_scope_hash="o", course_id="c"),
    )
    decision = gateway.evaluate(request)
    assert decision.outcome == "ok"
    assert decision.suggestion is not None
    assert decision.suggestion.score_value == 2.0


def test_a_level_key_is_still_a_level_and_not_a_number() -> None:
    """A certain answer still names a level, and the level survives as the level."""

    def responder(call):
        return JevResult(answers={"retrieval.support.v1": JevAnswer(score="3")})

    gateway = _gateway(FakeTransport(responder), modes={"retrieval.support.v1": "on"})
    decision = gateway.evaluate(_score_request())
    assert decision.outcome == "ok"
    assert decision.suggestion is not None
    assert decision.suggestion.score == "3"
    assert decision.suggestion.score_value is None


def test_the_cached_payload_round_trips_a_decimal_score() -> None:
    """A cached decimal must come back as a decimal, not as a level or as nothing."""
    from app.jev.gateway import _suggestion_payload

    definition = CATALOG.get("retrieval.support.v1")
    gateway = _gateway(FakeTransport(lambda call: JevResult(answers={})))
    payload = _suggestion_payload(
        JevAnswer(score=None, score_value=1.82), outcome="ok", model_version="jev-latest"
    )
    assert payload["score_value"] == 1.82
    restored = gateway._suggestion_from_cache(definition, payload)
    assert restored.score_value == 1.82
    assert restored.score is None
