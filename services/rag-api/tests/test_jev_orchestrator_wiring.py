"""The shared Jev service reaches the learning orchestrator, and receipts never block it.

Two production-wiring facts are asserted here, because both are invisible from a unit
test of any single module:

1. ``create_app`` hands the **same** ``SemanticDecisionService`` to the learning
   orchestrator, which is where call site 6 (pedagogy), 8 (assessment criterion
   review) and 11 (prerequisite) actually live. Without that, those three call
   sites exist in code but are unreachable in a real deployment.
2. The receipt store is **best-effort under write contention**. Assessment grading
   calls the criterion review from inside its own write transaction, so a receipt
   INSERT on a second connection must never wait for the full busy timeout and must
   never raise: a receipt is observability, not authority. A genuine data error is
   still raised.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest
from jev_fixtures import make_jev_database

from app.config import Settings
from app.jev.gateway import Receipt
from app.jev.receipt_store import SqlReceiptStore
from app.main import create_app


def _receipt(owner_scope_hash: str | None = "scope-a") -> Receipt:
    return Receipt(
        id="receipt-wiring-1",
        definition_key="pedagogy.next_method.v1",
        primitive="Choice",
        mode="shadow",
        caller_role="pedagogy",
        owner_scope_hash=owner_scope_hash,
        course_id="cs3481",
        workspace_id=None,
        material_revision=None,
        node_id=None,
        spec_version=None,
        question_hash=None,
        input_hash="a" * 64,
        output_json="{}",
        outcome="ok",
        latency_ms=1.0,
        model_version="fake-1.0.0",
    )


class FakeAuthVerifier:
    def authenticate(self, request):  # noqa: ANN001, ANN201
        return "user-a" if request.headers.get("authorization") else None


class FakeEmbeddingProvider:
    def embed_texts(self, texts):  # noqa: ANN001, ANN201
        return [[1.0, 0.0, 0.0] for _ in texts]


@pytest.fixture
def application(tmp_path: Path):
    settings = Settings(
        database_path=tmp_path / "wiring.sqlite3",
        upload_dir=tmp_path / "uploads",
        admin_user_ids="",
        app_env="test",
        v3_enabled=True,
        ui_extension_enabled=False,
        rag_provider_mode="deterministic",
        ui_web_dir=tmp_path / "no-web-build",
    )
    return create_app(
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
    )


def test_learning_orchestrator_receives_the_shared_service(application) -> None:
    shared = application.state.jev_service
    learning = application.state.learning

    # One service, not a second gateway: the orchestrator and everything it owns
    # point at the same object the rest of the app uses.
    assert learning.jev is shared
    assert learning.assessments.jev is shared
    assert learning.knowledge.jev is shared
    assert shared.gateway.receipt_store is not None  # the ledger is configured


def test_every_wired_call_site_has_the_service_in_the_real_app(application) -> None:
    """The three orchestrator-side call sites are reachable, not just defined."""
    assert application.state.learning.jev is not None  # pedagogy (6) + prerequisite (11)
    assert application.state.learning.assessments.jev is not None  # criterion review (8)


def test_receipt_write_is_dropped_instead_of_blocking_while_a_writer_holds_the_lock(
    tmp_path: Path,
) -> None:
    database = make_jev_database(tmp_path)
    store = SqlReceiptStore(database)

    with database.connect() as writer:
        # Hold the write lock the way the grading loop does: an uncommitted INSERT
        # on its own connection, exactly the situation a receipt write must survive.
        writer.execute("BEGIN IMMEDIATE")
        writer.execute(
            "INSERT INTO jev_decision_receipts("
            "id,definition_key,primitive,mode,caller_role,owner_scope_hash,input_hash,"
            "output_json,outcome,latency_ms) "
            "VALUES('held','x','Choice','shadow','test','held-scope','h','{}','ok',1.0)"
        )
        started = time.monotonic()
        store.save(_receipt())  # must not wait for the 10s busy timeout, must not raise
        elapsed = time.monotonic() - started
        assert elapsed < 2.0, f"receipt write stalled for {elapsed:.2f}s behind the caller lock"
        rows = writer.execute("SELECT COUNT(*) FROM jev_decision_receipts").fetchone()[0]
        writer.rollback()

    # The contended receipt was dropped (observability), and the held row is gone with
    # the rolled-back transaction: neither write blocked the other.
    assert rows == 1

    # With no writer holding the lock, the same write succeeds normally.
    store.save(_receipt())
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM jev_decision_receipts").fetchone()[0] == 1


def test_receipt_write_still_raises_a_real_data_error(tmp_path: Path) -> None:
    """Only lock/busy conflicts are swallowed; a genuine constraint error surfaces."""
    database = make_jev_database(tmp_path)
    store = SqlReceiptStore(database)
    with pytest.raises(sqlite3.IntegrityError):
        store.save(_receipt(owner_scope_hash=None))  # NOT NULL column