"""Module D bound to the teaching path: claim -> citation audit on the message revision.

The audit must change what the learner is told *only* when it has a real verdict,
and it must never lose an answer. These tests drive
``cm_update.app.audit_answer_citations`` directly with the offline ``FakeTransport``
(no network) and a stub resolver, so every claim here is about behaviour:

* no semantic layer configured -> the cards are returned unchanged, byte for byte;
* a figure the claim asserts that the source never states -> flagged in code, with
  **zero** Jev calls spent;
* a shadow/unavailable decision -> cards annotated, never altered or dropped;
* an unauthorized citation -> rejected with the reason recorded;
* a real "supported" signal -> recorded as verified;
* an audit failure -> the answer and its cards survive, with the failure recorded.
"""

from __future__ import annotations

from jev_fixtures import make_jev_database

from app.cm_update.app import audit_answer_citations
from app.jev.catalog import load_catalog
from app.jev.citation_audit import (
    INSUFFICIENT_CONTEXT,
    NOT_ADDRESSED_IN_AVAILABLE_EVIDENCE,
    REJECTED,
    SUPPORTED,
    ResolvedEvidence,
    StaticEvidenceResolver,
)
from app.jev.gateway import FakeTransport, JevGateway
from app.jev.models import JevAnswer, JevResult
from app.jev.receipt_store import SqlReceiptStore
from app.jev.service import SemanticDecisionService

CATALOG = load_catalog()
SUPPORT_KEY = "source.supports_claim.v1"


def make_service(database, responder, *, modes=None) -> SemanticDecisionService:
    return SemanticDecisionService(
        JevGateway(
            transport=FakeTransport(responder),
            catalog=CATALOG,
            modes=modes or {},
            receipt_store=SqlReceiptStore(database),
        )
    )


def receipts(database) -> int:
    with database.connect() as connection:
        return int(
            connection.execute("SELECT COUNT(*) FROM jev_decision_receipts").fetchone()[0]
        )


def card(source_id: str, *, document_id: str = "doc-a", name: str = "a.pdf", page: int = 1):
    return {
        "id": source_id,
        "document_id": document_id,
        "name": name,
        "page": page,
        "locator": f"page:{page}",
        "section": "s",
    }


def source(source_id: str, text: str):
    return {"id": source_id, "document_id": "doc-a", "text": text}


OUTPUT = "The pass rate is 88% [S1].\nA second claim follows [S2]."


def test_no_semantic_layer_returns_the_cards_unchanged(tmp_path) -> None:
    database = make_jev_database(tmp_path)
    cards = [card("S1"), card("S2", page=2)]
    before = [dict(item) for item in cards]

    result = audit_answer_citations(
        cards,
        OUTPUT,
        sources=[source("S1", "the pass rate is 40%"), source("S2", "unrelated evidence")],
        jev=None,
        owner_user_id="user-a",
        course_id="cs3481",
        database=database,
    )

    assert result == before  # no audit keys at all: the response is unchanged


def test_missing_figure_is_flagged_in_code_with_zero_jev_calls(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    def never_called(call):  # pragma: no cover - the deterministic layer must decide
        raise AssertionError("a deterministic layer-2 verdict must not spend a Jev call")

    service = make_service(database, never_called)
    cards = [card("S1")]

    result = audit_answer_citations(
        cards,
        OUTPUT,
        sources=[source("S1", "the pass rate is 40%")],
        jev=service,
        owner_user_id="user-a",
        course_id="cs3481",
        database=database,
    )

    assert result[0]["support"] == NOT_ADDRESSED_IN_AVAILABLE_EVIDENCE
    assert result[0]["audit_layer"] == "quote"
    assert result[0]["audit_missing_numbers"] == ["88%"]
    assert receipts(database) == 0  # provably no model call


def test_shadow_decision_annotates_without_altering_the_cards(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    def responder(call):
        return JevResult(answers={SUPPORT_KEY: JevAnswer(noul=0.9)})

    service = make_service(database, responder)  # shadow: no "on" mode
    cards = [card("S1"), card("S2", page=2)]
    keys_before = [set(item) for item in cards]

    result = audit_answer_citations(
        cards,
        OUTPUT,
        sources=[source("S1", "the pass rate is 40% but 88% is measured"),
                 source("S2", "unrelated evidence")],
        jev=service,
        owner_user_id="user-a",
        course_id="cs3481",
        database=database,
        resolver=StaticEvidenceResolver({"doc-a": "the pass rate is 40%"}),
    )

    # Nothing about the card the learner sees changed except the additive verdict.
    assert [item["id"] for item in result] == ["S1", "S2"]
    assert [item["name"] for item in result] == ["a.pdf", "a.pdf"]
    assert [item["page"] for item in result] == [1, 2]
    for item, keys in zip(result, keys_before, strict=True):
        assert set(item) - keys == {"support", "audit_layer", "audit_claim"}
        assert item["support"] == INSUFFICIENT_CONTEXT  # never a fabricated verdict
        assert item["audit_layer"] == "support"
    assert receipts(database) >= 1  # the shadow call really happened


def test_unauthorized_citation_is_rejected_with_its_reason(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    def responder(call):
        return JevResult(answers={SUPPORT_KEY: JevAnswer(noul=0.9)})

    service = make_service(database, responder, modes={SUPPORT_KEY: "on"})
    result = audit_answer_citations(
        [card("S1")],
        OUTPUT,
        sources=[source("S1", "the pass rate is 88%")],
        jev=service,
        owner_user_id="user-a",
        course_id="cs3481",
        database=database,
        resolver=StaticEvidenceResolver({"doc-a": "the pass rate is 88%"}, authorized=set()),
    )

    assert result[0]["support"] == REJECTED
    assert result[0]["audit_layer"] == "existence"
    assert result[0]["audit_reject_reason"] == "unauthorized"


def test_real_support_signal_is_recorded_as_verified(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    def responder(call):
        return JevResult(answers={SUPPORT_KEY: JevAnswer(noul=0.9)})

    service = make_service(database, responder, modes={SUPPORT_KEY: "on"})
    result = audit_answer_citations(
        [card("S1")],
        OUTPUT,
        sources=[source("S1", "the pass rate is 88%")],
        jev=service,
        owner_user_id="user-a",
        course_id="cs3481",
        database=database,
        resolver=StaticEvidenceResolver({"doc-a": "the pass rate is 88%"}),
    )

    assert result[0]["support"] == SUPPORTED
    assert result[0]["audit_layer"] == "support"


def test_audit_failure_never_loses_the_answer(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    class ExplodingResolver:
        def resolve(self, *, document_id, version, location):  # noqa: ANN001, ANN201
            raise RuntimeError("store unavailable")

    def responder(call):
        return JevResult(answers={SUPPORT_KEY: JevAnswer(noul=0.9)})

    service = make_service(database, responder, modes={SUPPORT_KEY: "on"})
    cards = [card("S1"), card("S2", page=2)]
    result = audit_answer_citations(
        cards,
        OUTPUT,
        sources=[source("S1", "the pass rate is 88% and 88% again"),
                 source("S2", "unrelated evidence")],
        jev=service,
        owner_user_id="user-a",
        course_id="cs3481",
        database=database,
        resolver=ExplodingResolver(),
    )

    assert [item["id"] for item in result] == ["S1", "S2"]
    assert all(item["audit_error"] == "RuntimeError" for item in result)
    assert all("support" not in item for item in result)  # no verdict was invented


def test_cards_beyond_the_budget_are_left_unannotated(tmp_path) -> None:
    database = make_jev_database(tmp_path)
    calls: list[str] = []

    def responder(call):
        calls.append(next(iter(call.questions)))
        return JevResult(answers={SUPPORT_KEY: JevAnswer(noul=0.9)})

    service = make_service(database, responder, modes={SUPPORT_KEY: "on"})
    cards = [card(f"S{index}") for index in range(1, 9)]
    # One cited claim per line, so each audit is a distinct state and the call count
    # measures the budget rather than the gateway's own de-duplication.
    text = "\n".join(f"distinct claim number {index} [S{index}]" for index in range(1, 9))
    result = audit_answer_citations(
        cards,
        text,
        sources=[source(f"S{index}", "irrelevant but authorized text") for index in range(1, 9)],
        jev=service,
        owner_user_id="user-a",
        course_id="cs3481",
        database=database,
        resolver=StaticEvidenceResolver({"doc-a": "irrelevant but authorized text"}),
        max_cards=6,
    )

    asserted = [item for item in result if "support" in item]
    untouched = [item for item in result if "support" not in item]
    assert len(asserted) == 6
    assert [item["id"] for item in untouched] == ["S7", "S8"]
    assert len(calls) == 6  # the per-answer model budget is enforced


def test_layer_one_reads_the_authorized_store_not_the_caller_store(
    tmp_path, monkeypatch
) -> None:
    """The caller's own database is not the store the citations live in.

    On the teaching path the caller passes the UI extension's `ui.sqlite3`
    (`cm_update.app.create_app`), which has no `document_versions` table at all.
    Layer 1 was built over that file, so **every** card raised
    `OperationalError: no such table: document_versions`, the handler recorded the
    failure and the learner never saw a single citation verdict — while the code
    looked correctly wired from every angle a unit test usually checks. The store
    is therefore an explicit parameter, and this pins which one is used.
    """

    caller_database = make_jev_database(tmp_path)
    evidence_store = object()  # stands in for the authorized document store
    built_with: list[object] = []
    class SpyResolver:
        def __init__(self, database, **_kwargs):  # noqa: ANN001
            built_with.append(database)

        def resolve(self, *, document_id, version, location):  # noqa: ANN001, ANN201
            return ResolvedEvidence(
                status="ok",
                document_id=document_id,
                version="1",
                location=location,
                text="the pass rate is 88%",
                span_id="chunk-1",
            )

    monkeypatch.setattr(
        "app.jev.citation_evidence.DocumentEvidenceResolver", SpyResolver
    )

    def responder(call):
        return JevResult(answers={SUPPORT_KEY: JevAnswer(noul=0.9)})

    service = make_service(caller_database, responder, modes={SUPPORT_KEY: "on"})
    result = audit_answer_citations(
        [card("S1")],
        OUTPUT,
        sources=[source("S1", "the pass rate is 88%")],
        jev=service,
        owner_user_id="user-a",
        course_id="cs3481",
        database=caller_database,
        evidence_database=evidence_store,
    )
    assert built_with == [evidence_store]
    assert result[0]["support"] == SUPPORTED
    assert "audit_error" not in result[0]


def test_one_cards_failure_does_not_erase_another_cards_verdict(tmp_path) -> None:
    """A layer-2 verdict is decided in code and must survive a neighbour's failure.

    The handler used to record the failure on every card and abandon the loop, so a
    single unavailable store hid the *deterministic* findings for every later card —
    which is exactly how the wrong-store defect above stayed invisible.
    """

    database = make_jev_database(tmp_path)

    class ExplodingResolver:
        def resolve(self, *, document_id, version, location):  # noqa: ANN001, ANN201
            raise RuntimeError("store unavailable")

    def responder(call):
        return JevResult(answers={SUPPORT_KEY: JevAnswer(noul=0.9)})

    service = make_service(database, responder, modes={SUPPORT_KEY: "on"})
    output = "The pass rate is 88% [S1].\nA different claim states 42% [S2]."
    result = audit_answer_citations(
        [card("S1"), card("S2", page=2)],
        output,
        sources=[source("S1", "the pass rate is 88%"), source("S2", "unrelated evidence")],
        jev=service,
        owner_user_id="user-a",
        course_id="cs3481",
        database=database,
        resolver=ExplodingResolver(),
    )

    assert result[0]["audit_error"] == "RuntimeError"
    assert "support" not in result[0]  # no verdict was invented for the card that failed
    assert result[1]["support"] == NOT_ADDRESSED_IN_AVAILABLE_EVIDENCE
    assert result[1]["audit_layer"] == "quote"
    assert result[1]["audit_missing_numbers"] == ["42%"]
