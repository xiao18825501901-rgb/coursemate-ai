"""Module A on the exact-locator path: the label is a filter, so it must be earned.

The query-reference parser's question number/part does not stay a hint — it becomes
a hard exact-locator SQL filter in both the official and the learner's private
scope, and its hits are placed at the head of the candidate list. These tests pin:

* the deterministic layer never invents a label out of prose (the failure mode that
  motivated the wiring, reproduced first as a real regression test);
* a message with no label costs **zero** Jev calls, and an uncalibrated deployment
  (off/shadow/no service/timeout) keeps the deterministic reference unchanged;
* only an affirmative defect drops a locator, and dropping can only ever remove a
  filter — it can never widen access;
* the semantic judgment sees the learner's own message and nothing else, and its
  cache scope is owner-scoped.

Every test uses the offline :class:`FakeTransport`: no live Jev call is made and
none is claimed.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from jev_fixtures import make_jev_database

from app.jev.errors import JevUnavailableError
from app.jev.extraction import EXTRACTION_FIELD_GROUNDED_KEY, ExtractionVerifier, Verdict
from app.jev.gateway import FakeTransport, JevGateway
from app.jev.models import JevAnswer, JevResult
from app.jev.receipt_store import SqlReceiptStore
from app.jev.reference_verification import (
    QUERY_REFERENCE_SOURCE,
    QUESTION_NUMBER_FIELD,
    QUESTION_PART_FIELD,
    build_verifier,
    reference_records,
    verify_query_reference,
)
from app.tutor.references import parse_query_reference

KEY = EXTRACTION_FIELD_GROUNDED_KEY
OWNER = "user-a"


# --------------------------------------------------------------------------- #
# The deterministic layer: no invented labels
# --------------------------------------------------------------------------- #

PROSE_QUERIES = [
    "What does question 5 have to do with chapter 2?",
    "what does q mean in this context",
    "question 3 marks distribution",
    "How many marks is question 4 worth",
    "explain the quest meaning here",
]


@pytest.mark.parametrize("query", PROSE_QUERIES)
def test_prose_never_yields_a_question_part(query: str) -> None:
    """A word that merely follows the number is not a sub-part.

    The pre-fix parser read "question 5 have ..." as part "h" and "q mean" as the
    roman number "M"; that invented label then became an exact-locator filter.
    """
    reference = parse_query_reference(query)
    assert reference.question_part is None, query
    assert reference.question_number != "M", query


LEGITIMATE_REFERENCES = [
    ("CS_3481_Assignment_2.pdf Question 2", "2", None),
    ("assignment_2.pdf Question 1(b)", "1", "b"),
    ("CS_3481_Assignment_2.pdf Question 3(2)", "3", "2"),
    ("GE2324_Tut07.docx Q1", "1", None),
    ("教我 assignment_2.pdf 的 Question 1(c)", "1", "c"),
    ("CS_3481_Assignment_2.pdf 第 2 题怎么做？", "2", None),
    ("q 2 b is confusing", "2", "b"),
]


@pytest.mark.parametrize(("query", "number", "part"), LEGITIMATE_REFERENCES)
def test_delimited_references_still_parse(query: str, number: str, part: str | None) -> None:
    """Narrowing the pattern must not lose a reference the learner really wrote."""
    reference = parse_query_reference(query)
    assert reference.question_number == number
    assert reference.question_part == part
    assert reference.question_span is not None


def test_record_span_and_text_are_the_query_itself() -> None:
    query = "  assignment_2.pdf   Question 1(b)  "
    reference = parse_query_reference(query)
    (number,) = reference_records(query, reference)[:1]

    normalized = "assignment_2.pdf Question 1(b)"
    assert number.source_id == QUERY_REFERENCE_SOURCE
    assert number.field_name == QUESTION_NUMBER_FIELD
    assert number.candidate_value == "1"
    assert number.part_id == "b"
    # The supplied text is the learner's own message, so its span must index it.
    assert number.supplied_text == normalized
    assert number.question_id == "1"
    assert number.span is not None
    assert normalized[number.span[0] : number.span[1]] == "Question 1(b)"
    assert number.region == "Question 1(b)"


def test_a_part_without_a_number_is_not_a_locator() -> None:
    reference = parse_query_reference("part b of the assignment")
    assert reference.question_number is None
    assert reference_records("part b of the assignment", reference) == ()


# --------------------------------------------------------------------------- #
# Zero Jev calls where a rule already decides
# --------------------------------------------------------------------------- #


def test_message_without_a_label_spends_zero_jev_calls() -> None:
    calls: list[object] = []
    gateway = JevGateway(transport=FakeTransport(lambda call: calls.append(call)))
    query = "how are you today"
    result = verify_query_reference(
        query, parse_query_reference(query), service=None, verifier=_for(gateway),
        owner_user_id=OWNER,
    )

    assert result.questioned is False
    assert result.jev_calls == 0
    assert result.dropped == ()
    assert calls == []
    assert result.reference.question_number is None


def test_no_service_keeps_the_deterministic_reference() -> None:
    query = "assignment_2.pdf Question 1(b)"
    result = verify_query_reference(
        query, parse_query_reference(query), service=None, owner_user_id=OWNER
    )

    # Uncalibrated deployments behave exactly as before: nothing is dropped...
    assert result.dropped == ()
    assert result.reference.question_number == "1"
    assert result.reference.question_part == "b"
    assert result.jev_calls == 0
    # ...but the fields are on record as unconfirmed, not as verified.
    assert set(result.needs_review) == {QUESTION_NUMBER_FIELD, QUESTION_PART_FIELD}
    assert all(not field.used_jev for field in result.fields)


# --------------------------------------------------------------------------- #
# Deterministic rejection, before any model call
# --------------------------------------------------------------------------- #


def test_wrong_shaped_label_is_rejected_without_a_call() -> None:
    calls: list[object] = []
    gateway = JevGateway(transport=FakeTransport(lambda call: calls.append(call)))
    query = "assignment_2.pdf Question 1(b)"
    reference = parse_query_reference(query)
    # A label the deterministic layer cannot accept (the parser never emits this).
    broken = replace(reference, question_number="Question 1")
    result = verify_query_reference(
        query, broken, service=None, verifier=_for(gateway), owner_user_id=OWNER
    )

    assert calls == []
    assert QUESTION_NUMBER_FIELD in result.dropped
    assert result.reference.question_number is None
    # A sub-part whose parent question is untrusted is not usable on its own.
    assert result.reference.question_part is None


# --------------------------------------------------------------------------- #
# Jev on the residue
# --------------------------------------------------------------------------- #


def responder_for(choice: str):
    def responder(call):  # noqa: ANN001, ANN202 - test helper
        return JevResult(answers={KEY: JevAnswer(choice=choice)})

    return responder


def _for(gateway: JevGateway):
    """The production verifier shape, driven by an offline gateway instead."""
    return build_verifier(None, gateway=gateway)


def make_gateway(responder, *, mode: str = "on", store=None) -> JevGateway:
    return JevGateway(
        transport=FakeTransport(responder), modes={KEY: mode}, receipt_store=store
    )


def verify(query: str, gateway: JevGateway, **kwargs):
    reference = parse_query_reference(query)
    return verify_query_reference(
        query, reference, service=None, verifier=_for(gateway),
        owner_user_id=kwargs.pop("owner_user_id", OWNER), **kwargs
    )


def test_grounded_label_is_accepted_and_jev_sees_only_the_residue() -> None:
    gateway = make_gateway(responder_for("GROUNDED"))
    query = "assignment_2.pdf Question 1(b)"
    result = verify(query, gateway)

    assert result.dropped == ()
    assert result.reference.question_number == "1"
    assert result.reference.question_part == "b"
    assert all(field.status == "ACCEPTED" for field in result.fields)
    assert all(field.trusted and field.used_jev for field in result.fields)
    assert result.jev_calls == 2

    sent = gateway.transport.calls[0].state
    assert set(sent) == {
        "question_id",
        "part_id",
        "field_name",
        "candidate_value",
        "unit",
        "supplied_text",
        "source_region",
    }
    assert sent["supplied_text"] == query
    assert sent["field_name"] == QUESTION_NUMBER_FIELD
    assert sent["candidate_value"] == "1"
    # The locator travels with the residue so a flag can be traced to a position.
    assert sent["source_region"]["region"] == "Question 1(b)"


def test_negated_reference_drops_the_locator() -> None:
    """The residue a regex cannot settle: "it is not question 3, it is 4"."""
    gateway = make_gateway(responder_for("NEGATION_LOST"))
    query = "it is not question 3, it is 4"
    result = verify(query, gateway)

    assert QUESTION_NUMBER_FIELD in result.dropped
    assert result.reference.question_number is None
    assert result.blocked is True
    number = next(f for f in result.fields if f.field == QUESTION_NUMBER_FIELD)
    assert number.verdict == Verdict.NEGATION_LOST.value
    assert number.status == "FLAGGED"
    assert number.trusted is False


def test_wrong_field_defect_drops_every_wide_reference() -> None:
    """Both labels of a two-label reference are judged, not just the first."""
    gateway = make_gateway(responder_for("WRONG_FIELD"))
    query = "assignment_2.pdf Question 1(b)"
    result = verify(query, gateway)

    assert set(result.dropped) == {QUESTION_NUMBER_FIELD, QUESTION_PART_FIELD}
    assert result.jev_calls == 2  # neither label was skipped by a shared allowance
    assert all(field.status == "FLAGGED" for field in result.fields)
    assert result.reference.question_number is None
    assert result.reference.question_part is None
    # The document locator is untouched: it was never in question.
    assert result.reference.document == "assignment_2.pdf"
    assert result.reference.document_kind is not None


def test_a_defect_drops_the_locator_even_when_no_repair_remains() -> None:
    """The invariant is about the verdict, not about the repair allowance.

    A verifier built with the module's default single allowance cannot plan a
    second repair, so the second label comes back NEEDS_REVIEW with the verdict
    preserved. Reading only the status there would leave a label the model called
    wrong in place as a hard filter, which is the one outcome this module exists to
    prevent.
    """
    gateway = make_gateway(responder_for("WRONG_FIELD"))
    starved = ExtractionVerifier(
        gateway=gateway,
        source_registry=build_verifier(None).source_registry,
        repair_budget=1,
        question_number_pattern=build_verifier(None).question_number_pattern,
        part_number_pattern=build_verifier(None).part_number_pattern,
    )
    query = "assignment_2.pdf Question 1(b)"
    result = verify_query_reference(
        query, parse_query_reference(query), service=None, verifier=starved,
        owner_user_id="user-a",
    )

    assert set(result.dropped) == {QUESTION_NUMBER_FIELD, QUESTION_PART_FIELD}
    assert result.reference.question_number is None
    assert result.reference.question_part is None
    statuses = {field.field: field.status for field in result.fields}
    assert statuses[QUESTION_PART_FIELD] == "NEEDS_REVIEW"  # diagnostic, still acted on


def test_constraint_lost_on_the_part_keeps_the_question() -> None:
    def responder(call):  # noqa: ANN001, ANN202 - test helper
        field = call.state["field_name"]
        choice = "CONSTRAINT_LOST" if field == QUESTION_PART_FIELD else "GROUNDED"
        return JevResult(answers={KEY: JevAnswer(choice=choice)})

    result = verify("assignment_2.pdf Question 1(b)", make_gateway(responder))

    assert result.dropped == (QUESTION_PART_FIELD,)
    assert result.reference.question_number == "1"
    assert result.reference.question_part is None


@pytest.mark.parametrize("choice", ["UNCERTAIN", "SOURCE_INSUFFICIENT"])
def test_uncertainty_never_acts_on_its_own(choice: str) -> None:
    """UNCERTAIN is surfaced as review; SOURCE_INSUFFICIENT is a defect.

    The split matters: an unconfirmed label is reported, while a label the model
    affirmatively says the source cannot support stops being a hard filter.
    """
    result = verify("assignment_2.pdf Question 1(b)", make_gateway(responder_for(choice)))

    if choice == "UNCERTAIN":
        assert result.dropped == ()
        assert set(result.needs_review) == {QUESTION_NUMBER_FIELD, QUESTION_PART_FIELD}
        assert result.reference.question_number == "1"
    else:
        assert QUESTION_NUMBER_FIELD in result.dropped
        assert result.reference.question_number is None


def test_an_unauthorized_candidate_is_a_fallback_not_a_verdict() -> None:
    """Fail safe: a verdict outside the authorized vocabulary keeps the reference."""
    result = verify("assignment_2.pdf Question 1(b)", make_gateway(responder_for("TRUST_ME")))

    assert result.dropped == ()
    assert result.reference.question_number == "1"
    assert all(field.verdict is None for field in result.fields)
    assert all(field.fallback_reason == "jev_invalid_response" for field in result.fields)


# --------------------------------------------------------------------------- #
# Degradation: shadow, unavailable, cache scope
# --------------------------------------------------------------------------- #


def test_shadow_mode_records_a_receipt_and_changes_nothing(tmp_path) -> None:
    database = make_jev_database(tmp_path)
    gateway = make_gateway(
        responder_for("NEGATION_LOST"),
        mode="shadow",
        store=SqlReceiptStore(database),
    )

    result = verify("it is not question 3, it is 4", gateway)

    assert result.dropped == ()
    assert result.reference.question_number == "3"
    assert result.jev_calls == 1  # the call was made; the answer may not be used
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT mode, outcome FROM jev_decision_receipts ORDER BY created_at"
        ).fetchall()
    assert rows, "shadow must still write an auditable receipt"
    assert {row[0] for row in rows} == {"shadow"}


def test_unavailable_transport_keeps_the_deterministic_reference() -> None:
    def responder(call):  # noqa: ANN001, ANN202 - test helper
        raise JevUnavailableError("down")

    result = verify("assignment_2.pdf Question 1(b)", make_gateway(responder))

    assert result.dropped == ()
    assert result.reference.question_number == "1"
    assert all(field.fallback_reason == "jev_unavailable" for field in result.fields)
    assert all(not field.used_jev for field in result.fields)


def test_cache_scope_is_owner_scoped_and_never_crosses_users(tmp_path) -> None:
    """§7: a private-scope judgment must not be served from another user's cache."""
    database = make_jev_database(tmp_path)
    gateway = make_gateway(
        responder_for("GROUNDED"), mode="on", store=SqlReceiptStore(database)
    )
    query = "assignment_2.pdf Question 1(b)"

    for owner in ("user-a", "user-a", "user-b"):
        reference = parse_query_reference(query)
        verify_query_reference(
            query,
            reference,
            service=None,
            verifier=_for(gateway),
            owner_user_id=owner,
            authorization_scope="mine",
            course_id="private-1",
        )

    # Two labels per owner: user-a's repeat must be served from its own cache, and
    # user-b must never be served user-a's judgment.
    assert len(gateway.transport.calls) == 4
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT owner_scope_hash, COUNT(*) FROM jev_decision_receipts "
            "GROUP BY owner_scope_hash"
        ).fetchall()
    assert len(rows) == 2, rows
    assert [count for _, count in rows] == [2, 2]


def test_a_verifier_without_a_source_registry_is_refused() -> None:
    """Silently dropping every label would look like a clean verification."""
    query = "assignment_2.pdf Question 1(b)"
    loose = build_verifier(None)
    loose.source_registry = None

    with pytest.raises(ValueError, match="source registry"):
        verify_query_reference(
            query, parse_query_reference(query), service=None, verifier=loose,
            owner_user_id=OWNER,
        )
