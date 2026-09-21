"""Gateway semantics: modes, fallback, deadline, breaker, receipts, cache, no retry."""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import Any

from app.jev.catalog import load_catalog
from app.laya.adapter import (
    FakeLayaTransport,
    LayaConfig,
    LayaGateway,
    LayaReceipt,
    laya_question,
)
from app.laya.errors import LayaUnavailableError
from app.laya.models import LayaRequest, LayaScope, request_content_hash
from app.laya.receipt_store import SqlLayaReceiptStore

CATALOG = load_catalog()
CHOICE = CATALOG.get("intent.next_action.v1")
SCORE = CATALOG.get("retrieval.support.v1")
NOUL = CATALOG.get("context.keep_segment.v1")
CHOICE_IDS = ("CONTINUE", "ANSWER_ONLY", "OTHER")


class MemoryStore:
    def __init__(self) -> None:
        self.receipts: list[LayaReceipt] = []
        self.cached: dict[str, Any] | None = None

    def save(self, receipt: LayaReceipt) -> None:
        self.receipts.append(receipt)

    def lookup(self, definition_id: str, scope: LayaScope, *, model_revision: str) -> dict | None:
        return self.cached


class FakeClock:
    def __init__(self, now_ms: int = 0) -> None:
        self.now = now_ms

    def now_ms(self) -> int:
        return self.now


def _request(definition, *, criteria=None, deadline_ms: int = 0) -> LayaRequest:
    question = laya_question(definition, criteria=criteria)
    return LayaRequest(
        definition_id=definition.key,
        definition_version="1.0.0-design",
        state={"message": "继续"},
        questions={definition.key: question},
        deadline_ms=deadline_ms,
        request_id="r1",
        compiler_version="c1",
        model_revision="rev1",
    )


def _gateway(transport, *, modes=None, store=None, clock=None, config=None) -> LayaGateway:
    return LayaGateway(
        transport=transport,
        catalog=CATALOG,
        modes=modes,
        receipt_store=store,
        clock=clock,
        config=config,
    )


def _scope(**kwargs) -> LayaScope:
    return LayaScope(owner_scope_hash="owner", **kwargs)


def _choice_responder(choice: str):
    def responder(req: LayaRequest) -> dict:
        qid = req.definition_id
        probabilities = {cid: (1.0 if cid == choice else 0.0) for cid in CHOICE_IDS}
        return {
            "answers": {
                qid: {
                    "type": "choice",
                    "choice": choice,
                    "probabilities": probabilities,
                    "confidence": 1.0,
                    "rl_agent": {"act_probability": 0.9},
                }
            },
            "usage": {"input_tokens": 10, "output_tokens": 0},
        }

    return responder


def _noul_responder(p: float):
    def responder(req: LayaRequest) -> dict:
        return {
            "answers": {req.definition_id: {"type": "noul", "noul": p}},
            "usage": {"input_tokens": 8, "output_tokens": 0},
        }

    return responder


# ------------------------------------------------------------------ modes
def test_mode_for_defaults_to_shadow() -> None:
    gateway = _gateway(FakeLayaTransport())
    assert gateway.mode_for(CHOICE.key) == "shadow"


def test_off_makes_no_call_and_returns_fallback() -> None:
    transport = FakeLayaTransport(_choice_responder("CONTINUE"))
    store = MemoryStore()
    gateway = _gateway(transport, modes={CHOICE.key: "off"}, store=store)
    decision = gateway.decide(
        _request(CHOICE, criteria={cid: "" for cid in CHOICE_IDS}), scope=_scope(), fallback="OTHER"
    )
    assert decision.mode == "off"
    assert decision.value == "OTHER"
    assert decision.used_laya is False
    assert transport.requests == []
    assert store.receipts == []


def test_shadow_records_suggestion_and_returns_fallback() -> None:
    transport = FakeLayaTransport(_choice_responder("CONTINUE"))
    store = MemoryStore()
    gateway = _gateway(transport, modes={CHOICE.key: "shadow"}, store=store)
    decision = gateway.decide(
        _request(CHOICE, criteria={cid: "" for cid in CHOICE_IDS}), scope=_scope(), fallback="OTHER"
    )
    assert decision.value == "OTHER"
    assert decision.used_laya is False
    assert decision.answer is None  # shadow keeps the suggestion receipt-only
    assert len(transport.requests) == 1
    assert len(store.receipts) == 1
    receipt = store.receipts[0]
    assert receipt.mode == "shadow"
    assert receipt.outcome == "ok"


def test_on_uses_laya_value() -> None:
    transport = FakeLayaTransport(_choice_responder("OTHER"))
    gateway = _gateway(transport, modes={CHOICE.key: "on"})
    decision = gateway.decide(
        _request(CHOICE, criteria={cid: "" for cid in CHOICE_IDS}),
        scope=_scope(),
        fallback="CONTINUE",
    )
    assert decision.value == "OTHER"
    assert decision.used_laya is True
    assert decision.fallback_reason is None


def test_advisory_surfaces_answer_but_returns_fallback() -> None:
    transport = FakeLayaTransport(_choice_responder("CONTINUE"))
    gateway = _gateway(transport, modes={CHOICE.key: "advisory"})
    decision = gateway.decide(
        _request(CHOICE, criteria={cid: "" for cid in CHOICE_IDS}), scope=_scope(), fallback="OTHER"
    )
    assert decision.value == "OTHER"
    assert decision.used_laya is False
    assert decision.answer is not None and decision.answer.choice == "CONTINUE"


# ------------------------------------------------------------------ failure paths
def test_invalid_choice_falls_back_with_reason_and_no_retry() -> None:
    def evil(req: LayaRequest) -> dict:
        return {
            "answers": {
                req.definition_id: {
                    "type": "choice",
                    "choice": "EVIL_ID",
                    "probabilities": {"EVIL_ID": 1.0},
                    "confidence": 1.0,
                }
            },
            "usage": {"input_tokens": 5, "output_tokens": 0},
        }

    transport = FakeLayaTransport(evil)
    store = MemoryStore()
    gateway = _gateway(transport, modes={CHOICE.key: "on"}, store=store)
    decision = gateway.decide(
        _request(CHOICE, criteria={cid: "" for cid in CHOICE_IDS}), scope=_scope(), fallback="OTHER"
    )
    assert decision.value == "OTHER"
    assert decision.used_laya is False
    assert decision.fallback_reason == "invalid_response"
    assert len(transport.requests) == 1  # one attempt only


def test_transport_failure_falls_back_with_reason() -> None:
    def down(req: LayaRequest) -> None:
        raise LayaUnavailableError("down")

    transport = FakeLayaTransport(down)
    store = MemoryStore()
    gateway = _gateway(transport, modes={CHOICE.key: "on"}, store=store)
    decision = gateway.decide(
        _request(CHOICE, criteria={cid: "" for cid in CHOICE_IDS}), scope=_scope(), fallback="OTHER"
    )
    assert decision.value == "OTHER"
    assert decision.used_laya is False
    assert decision.fallback_reason == "unavailable"
    assert len(transport.requests) == 1  # no retry
    assert store.receipts[0].outcome == "unavailable"


# ------------------------------------------------------------------ deadline
def test_deadline_passed_before_call_skips_transport() -> None:
    transport = FakeLayaTransport(_choice_responder("CONTINUE"))
    clock = FakeClock(now_ms=2_000)
    gateway = _gateway(transport, modes={CHOICE.key: "on"}, clock=clock)
    decision = gateway.decide(
        _request(CHOICE, criteria={cid: "" for cid in CHOICE_IDS}, deadline_ms=1_000),
        scope=_scope(),
        fallback="OTHER",
    )
    assert decision.fallback_reason == "deadline_exceeded"
    assert transport.requests == []  # never sent


def test_late_reply_is_discarded() -> None:
    clock = FakeClock(now_ms=0)

    def slow(req: LayaRequest) -> dict:
        clock.now = 5_000  # the clock advances past the deadline during the call
        return _choice_responder("CONTINUE")(req)

    transport = FakeLayaTransport(slow)
    gateway = _gateway(transport, modes={CHOICE.key: "on"}, clock=clock)
    decision = gateway.decide(
        _request(CHOICE, criteria={cid: "" for cid in CHOICE_IDS}, deadline_ms=1_000),
        scope=_scope(),
        fallback="OTHER",
    )
    assert decision.value == "OTHER"
    assert decision.used_laya is False
    assert decision.fallback_reason == "deadline_exceeded"


# ------------------------------------------------------------------ circuit breaker
def test_circuit_breaker_opens_and_fails_fast() -> None:
    def down(req: LayaRequest) -> None:
        raise LayaUnavailableError("down")

    transport = FakeLayaTransport(down)
    config = LayaConfig(breaker_failure_threshold=2, breaker_cooldown_ms=100_000)
    clock = FakeClock(now_ms=0)
    gateway = _gateway(transport, modes={CHOICE.key: "on"}, clock=clock, config=config)

    for _ in range(2):
        decision = gateway.decide(
            _request(CHOICE, criteria={cid: "" for cid in CHOICE_IDS}),
            scope=_scope(),
            fallback="OTHER",
        )
        assert decision.fallback_reason == "unavailable"
    assert gateway.breaker_state == "open"

    third = gateway.decide(
        _request(CHOICE, criteria={cid: "" for cid in CHOICE_IDS}), scope=_scope(), fallback="OTHER"
    )
    assert third.fallback_reason == "circuit_open"
    assert len(transport.requests) == 2  # fail-fast: no third transport call


# ------------------------------------------------------------------ receipts
def test_receipt_records_the_truth() -> None:
    transport = FakeLayaTransport(_choice_responder("CONTINUE"))
    store = MemoryStore()
    gateway = _gateway(transport, modes={CHOICE.key: "on"}, store=store)
    request = _request(CHOICE, criteria={cid: "" for cid in CHOICE_IDS})
    decision = gateway.decide(request, scope=_scope(), fallback="OTHER")
    receipt = store.receipts[0]
    assert decision.receipt_id == receipt.id
    assert receipt.definition_id == CHOICE.key
    assert receipt.definition_version == "1.0.0-design"
    assert receipt.model_revision == "rev1"
    assert receipt.compiler_version == "c1"
    assert receipt.outcome == "ok"
    assert receipt.calibration_version is None
    assert receipt.temperature is None  # identity temperature: no calibration applied
    expected_hash = request_content_hash(
        request.definition_id, request.definition_version, request.state, request.questions
    )
    assert receipt.input_hash == expected_hash


# ------------------------------------------------------------------ cache
def test_cache_hit_skips_transport() -> None:
    transport = FakeLayaTransport(_choice_responder("CONTINUE"))
    store = MemoryStore()
    store.cached = {
        "choice": "CONTINUE",
        "probabilities": {cid: (1.0 if cid == "CONTINUE" else 0.0) for cid in CHOICE_IDS},
        "confidence": 1.0,
    }
    gateway = _gateway(transport, modes={CHOICE.key: "on"}, store=store)
    decision = gateway.decide(
        _request(CHOICE, criteria={cid: "" for cid in CHOICE_IDS}), scope=_scope(), fallback="OTHER"
    )
    assert decision.value == "CONTINUE"
    assert decision.used_laya is True
    assert transport.requests == []


# ------------------------------------------------------------------ oversized / unsupported
def test_oversized_request_fails_fast() -> None:
    transport = FakeLayaTransport(_choice_responder("CONTINUE"))
    gateway = _gateway(transport, modes={CHOICE.key: "on"}, config=LayaConfig(max_request_chars=10))
    decision = gateway.decide(
        _request(CHOICE, criteria={cid: "" for cid in CHOICE_IDS}), scope=_scope(), fallback="OTHER"
    )
    assert decision.fallback_reason == "oversized"
    assert transport.requests == []


def test_noul_decision_confidence_is_none() -> None:
    transport = FakeLayaTransport(_noul_responder(0.7))
    gateway = _gateway(transport, modes={NOUL.key: "on"})
    decision = gateway.decide(_request(NOUL), scope=_scope(), fallback=False)
    assert decision.value == 0.7
    assert decision.used_laya is True
    assert decision.confidence is None  # noul is never a confidence


# ------------------------------------------------------------------ sql receipt store
def test_sql_receipt_store_persists_provider_laya(tmp_path) -> None:
    migrations = Path(__file__).parent.parent / "migrations"

    class Database:
        def __init__(self, path: Path) -> None:
            self.path = path

        @contextlib.contextmanager
        def connect(self):
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    database = Database(tmp_path / "laya.sqlite3")
    with database.connect() as conn:
        conn.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL)"
        )
        conn.executescript(
            (migrations / "028_jev_decision_receipts.sql").read_text(encoding="utf-8")
        )
        conn.executescript(
            (migrations / "029_laya_decision_receipts.sql").read_text(encoding="utf-8")
        )

    store = SqlLayaReceiptStore(database)
    transport = FakeLayaTransport(_choice_responder("CONTINUE"))
    gateway = _gateway(transport, modes={CHOICE.key: "on"}, store=store)
    gateway.decide(
        _request(CHOICE, criteria={cid: "" for cid in CHOICE_IDS}), scope=_scope(), fallback="OTHER"
    )

    with database.connect() as conn:
        row = conn.execute(
            "SELECT provider, model_revision, definition_id, mode, outcome "
            "FROM laya_decision_receipts"
        ).fetchone()
    assert row["provider"] == "laya"
    assert row["model_revision"] == "rev1"
    assert row["definition_id"] == CHOICE.key
    assert row["mode"] == "on"
    assert row["outcome"] == "ok"
