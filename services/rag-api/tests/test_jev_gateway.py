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
