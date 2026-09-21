"""Service semantics: cache, shadow contract, cross-user isolation, deterministic fallback."""

from __future__ import annotations

import pytest

from jev_fixtures import make_jev_database

from app.jev.catalog import load_catalog
from app.jev.gateway import FakeTransport, JevGateway
from app.jev.models import JevAnswer, JevResult
from app.jev.receipt_store import SqlReceiptStore
from app.jev.service import SemanticDecisionService

CATALOG = load_catalog()
CHOICE_IDS = ("CONTINUE", "ANSWER_ONLY", "OTHER")


@pytest.fixture
def database(tmp_path):
    return make_jev_database(tmp_path)


def _score_responder(level: str):
    def responder(call):
        return JevResult(answers={"retrieval.support.v1": JevAnswer(score=level)})

    return responder


def _gateway(transport, *, modes, store) -> JevGateway:
    return JevGateway(transport=transport, catalog=CATALOG, modes=modes, receipt_store=store)


def _state():
    return {"query": "q", "candidate_id": "c1", "candidate_text": "text"}


def test_cache_hit_and_material_revision_invalidation(database) -> None:
    transport = FakeTransport(_score_responder("3"))
    gateway = _gateway(
        transport, modes={"retrieval.support.v1": "on"}, store=SqlReceiptStore(database)
    )
    service = SemanticDecisionService(gateway)
    scope = service.scope(
        owner_user_id="user-a", authorization_scope="retrieval", course_id="c", material_revision="r1"
    )
    first = service.score(
        "retrieval.support.v1", state=_state(), caller_role="retrieval", cache_scope=scope
    )
    assert first.used_jev and first.value == 3
    assert len(transport.calls) == 1

    second = service.score(
        "retrieval.support.v1", state=_state(), caller_role="retrieval", cache_scope=scope
    )
    assert second.used_jev and second.value == 3
    assert len(transport.calls) == 1  # cache hit: no second transport call

    # A material-revision change invalidates the cached suggestion.
    changed = service.scope(
        owner_user_id="user-a", authorization_scope="retrieval", course_id="c", material_revision="r2"
    )
    third = service.score(
        "retrieval.support.v1", state=_state(), caller_role="retrieval", cache_scope=changed
    )
    assert len(transport.calls) == 2  # miss


def test_cache_cross_user_isolation(database) -> None:
    transport = FakeTransport(_score_responder("3"))
    gateway = _gateway(
        transport, modes={"retrieval.support.v1": "on"}, store=SqlReceiptStore(database)
    )
    service = SemanticDecisionService(gateway)
    scope_a = service.scope(
        owner_user_id="user-a", authorization_scope="retrieval", course_id="c", material_revision="r1"
    )
    service.score("retrieval.support.v1", state=_state(), caller_role="retrieval", cache_scope=scope_a)
    assert len(transport.calls) == 1

    scope_b = service.scope(
        owner_user_id="user-b", authorization_scope="retrieval", course_id="c", material_revision="r1"
    )
    service.score("retrieval.support.v1", state=_state(), caller_role="retrieval", cache_scope=scope_b)
    assert len(transport.calls) == 2  # a cached suggestion is never reused for another owner


def test_shadow_contract_byte_identical_and_suggestion_recorded(database) -> None:
    store = SqlReceiptStore(database)

    def responder(call):
        return JevResult(answers={"intent.next_action.v1": JevAnswer(choice="CONTINUE")})

    off = SemanticDecisionService(
        _gateway(FakeTransport(responder), modes={"intent.next_action.v1": "off"}, store=store)
    )
    shadow = SemanticDecisionService(
        _gateway(FakeTransport(responder), modes={"intent.next_action.v1": "shadow"}, store=store)
    )
    state = {"message": "继续", "fixed_anchor": {}, "current_mode": "teach", "active_assessment": None}
    scope = service_scope(off, "user-a")

    off_result = off.choice(
        "intent.next_action.v1",
        candidate_ids=CHOICE_IDS,
        state=state,
        caller_role="intent",
        cache_scope=scope,
        deterministic="OTHER",
    )
    shadow_result = shadow.choice(
        "intent.next_action.v1",
        candidate_ids=CHOICE_IDS,
        state=state,
        caller_role="intent",
        cache_scope=scope,
        deterministic="OTHER",
    )

    assert off_result.value == shadow_result.value == "OTHER"  # byte-identical user-visible result
    assert off_result.suggestion is None
    assert shadow_result.suggestion == "CONTINUE"  # suggestion recorded in the receipt only
    assert shadow_result.used_jev is False

    with database.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM jev_decision_receipts WHERE outcome='ok' AND mode='shadow'"
        ).fetchone()[0]
    assert count == 1


def test_choice_never_returns_model_invented_id(database) -> None:
    def responder(call):
        return JevResult(answers={"intent.next_action.v1": JevAnswer(choice="EVIL_ID")})

    gateway = _gateway(
        FakeTransport(responder), modes={"intent.next_action.v1": "on"}, store=SqlReceiptStore(database)
    )
    service = SemanticDecisionService(gateway)
    result = service.choice(
        "intent.next_action.v1",
        candidate_ids=CHOICE_IDS,
        state={"message": "继续", "fixed_anchor": {}, "current_mode": "teach", "active_assessment": None},
        caller_role="intent",
        cache_scope=service_scope(service, "user-a"),
        deterministic="OTHER",
    )
    assert result.value == "OTHER"  # deterministic fallback; the invalid id never surfaces
    assert result.suggestion is None


def service_scope(service: SemanticDecisionService, user: str):
    return service.scope(owner_user_id=user, authorization_scope="retrieval", course_id="c")
