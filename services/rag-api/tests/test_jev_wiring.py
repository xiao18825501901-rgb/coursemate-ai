"""Retrieval re-rank wiring and the no-state-write contract.

These tests run against a self-contained schema (see ``jev_fixtures``) so the Jev
layer is verifiable without the full V3 migration suite.
"""

from __future__ import annotations

import pytest

from jev_fixtures import make_jev_database

from app.config import Settings
from app.jev.catalog import load_catalog
from app.jev.errors import JevUnavailableError
from app.jev.gateway import FakeTransport, JevGateway
from app.jev.models import JevAnswer, JevResult
from app.jev.receipt_store import SqlReceiptStore
from app.jev.service import SemanticDecisionService
from app.learning.retrieval_orchestrator import FusedHit
from app.ui_extension.domain import V3DomainAdapter

CATALOG = load_catalog()


class _Hit:
    def __init__(self, prefix: str, index: int) -> None:
        self.chunk_id = f"{prefix}-chunk-{index}"
        self.document_id = f"{prefix}-doc-{index}"
        self.filename = f"{prefix}-{index}.md"
        self.locator_type = "page"
        self.locator_value = str(index)
        self.section = "s"
        self.content = f"{prefix} unique evidence {index}"


def _hit(prefix: str, index: int) -> _Hit:
    return _Hit(prefix, index)


def _rerank_service(database, responder, *, mode: str = "on") -> SemanticDecisionService:
    gateway = JevGateway(
        transport=FakeTransport(responder),
        catalog=CATALOG,
        modes={"retrieval.support.v1": mode},
        receipt_store=SqlReceiptStore(database),
    )
    return SemanticDecisionService(gateway)


def test_rerank_exact_target_keeps_slot_and_private_promoted(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    def responder(call):
        cid = call.state["candidate_id"]
        level = "4" if cid.startswith("private") else "0"
        return JevResult(answers={"retrieval.support.v1": JevAnswer(score=level)})

    service = _rerank_service(database, responder)
    exact_hit = _Hit("official", 2)
    exact_hit.filename = "official-2.md"
    entries = [
        FusedHit(hit=_hit("official", 1), score=0.5, scopes=("official",), ranks={"official": 1}, exact=False),
        FusedHit(hit=_hit("private", 1), score=0.4, scopes=("mine",), ranks={"mine": 1}, exact=False),
        FusedHit(hit=exact_hit, score=0.3, scopes=("official",), ranks={"official": 2}, exact=True),
    ]
    scope = service.scope(owner_user_id="u", authorization_scope="retrieval")
    result = service.rerank_retrieval(entries, query="official-2.md page 2", caller_role="retrieval", cache_scope=scope)
    # The private candidate is promoted past the official one, while the exact
    # target keeps its original slot (index 2).
    assert [e.chunk_id for e in result] == ["private-chunk-1", "official-chunk-1", "official-chunk-2"]


def test_rerank_shadow_returns_deterministic_order(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    def responder(call):
        return JevResult(answers={"retrieval.support.v1": JevAnswer(score="4")})

    service = _rerank_service(database, responder, mode="shadow")
    entries = [
        FusedHit(hit=_hit("official", 1), score=0.5, scopes=("official",), ranks={"official": 1}, exact=False),
        FusedHit(hit=_hit("private", 1), score=0.4, scopes=("mine",), ranks={"mine": 1}, exact=False),
    ]
    scope = service.scope(owner_user_id="u", authorization_scope="retrieval")
    result = service.rerank_retrieval(entries, query="q", caller_role="retrieval", cache_scope=scope)
    assert [e.chunk_id for e in result] == ["official-chunk-1", "private-chunk-1"]


class _StubRetriever:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def retrieve(self, *, course_id, query, top_k, access):  # noqa: ANN001
        self.calls.append({"course": course_id, "scope": access.scope, "top_k": top_k})
        prefix = "official" if access.scope == "official" else "private"
        return [_hit(prefix, index) for index in range(1, top_k + 1)]

    def retrieve_structured(self, *, course_id, reference, top_k, access=None):  # noqa: ANN001
        return []


def test_retrieve_wiring_promotes_private_with_jev_on(tmp_path) -> None:
    database = make_jev_database(tmp_path, with_courses=True)
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO courses(id,name,owner_user_id,course_type,visibility,"
            "publication_status,display_type,requires_student_verification) "
            "VALUES('jev-course','Jev Course',NULL,'official','public','published','campus',1)"
        )
        connection.execute(
            "INSERT INTO courses(id,name,owner_user_id,course_type,visibility,publication_status) "
            "VALUES('jev-private','My workspace files','user-a','user','private','private')"
        )
        connection.execute(
            "INSERT INTO learning_workspaces(id,owner_user_id,course_id,private_course_id) "
            "VALUES('ws-1','user-a','jev-course','jev-private')"
        )

    def responder(call):
        cid = call.state["candidate_id"]
        level = "4" if cid.startswith("private") else "0"
        return JevResult(answers={"retrieval.support.v1": JevAnswer(score=level)})

    service = _rerank_service(database, responder, mode="on")
    settings = Settings(
        database_path=database.path,
        upload_dir=database.upload_dir,
        admin_user_ids="",
        app_env="test",
        v3_enabled=True,
        ui_extension_enabled=True,
        rag_provider_mode="deterministic",
        ui_web_dir=tmp_path / "no-web-build",
        top_k=2,
    )
    adapter = V3DomainAdapter(
        database=database,
        settings=settings,
        ingestion=None,
        learning=None,
        retriever=_StubRetriever(),  # type: ignore[arg-type]
        jev=service,
    )
    sources = adapter._retrieve("user-a", {"course": "jev-course", "query": "private supplement example"})  # noqa: SLF001
    document_ids = [source["document_id"] for source in sources]
    assert document_ids[0].startswith("private"), document_ids


def test_failed_jev_call_writes_no_learning_grade_or_coverage(tmp_path) -> None:
    database = make_jev_database(tmp_path)
    with database.connect() as connection:
        connection.executescript(
            """
            CREATE TABLE learning_journeys (id TEXT PRIMARY KEY, node_id TEXT, status TEXT);
            CREATE TABLE assessment_sessions (id TEXT PRIMARY KEY, raw_score REAL, status TEXT);
            CREATE TABLE learning_coverage (id TEXT PRIMARY KEY, journey_id TEXT, item_id TEXT);
            INSERT INTO learning_journeys VALUES('j1','n1','LEARNING');
            INSERT INTO assessment_sessions VALUES('s1',78.0,'GRADED');
            INSERT INTO learning_coverage VALUES('c1','j1','item-a');
            """
        )

    def failing(call):
        raise JevUnavailableError("down")

    gateway = JevGateway(
        transport=FakeTransport(failing),
        catalog=CATALOG,
        modes={"retrieval.support.v1": "on", "coverage.item_support.v1": "on"},
        receipt_store=SqlReceiptStore(database),
    )
    service = SemanticDecisionService(gateway)
    scope = service.scope(owner_user_id="user-a", authorization_scope="retrieval", course_id="c")
    service.rerank_retrieval(
        [FusedHit(hit=_hit("official", 1), score=0.5, scopes=("official",), ranks={"official": 1}, exact=False)],
        query="x",
        caller_role="retrieval",
        cache_scope=scope,
    )
    service.item_support(
        [{"item_id": "item-a", "requirement": "REQUIRED"}],
        content="x",
        spec_version=1,
        caller_role="coverage",
        cache_scope=scope,
    )

    with database.connect() as connection:
        journey_status = connection.execute(
            "SELECT status FROM learning_journeys WHERE id='j1'"
        ).fetchone()[0]
        grade = connection.execute(
            "SELECT raw_score FROM assessment_sessions WHERE id='s1'"
        ).fetchone()[0]
        coverage = connection.execute("SELECT COUNT(*) FROM learning_coverage").fetchone()[0]
        receipts = connection.execute(
            "SELECT COUNT(*) FROM jev_decision_receipts WHERE outcome='unavailable'"
        ).fetchone()[0]
    assert journey_status == "LEARNING"
    assert grade == 78.0
    assert coverage == 1
    assert receipts >= 1  # the only write was to the Jev receipt ledger
