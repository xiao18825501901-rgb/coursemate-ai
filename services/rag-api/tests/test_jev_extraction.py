"""ExtractionVerification: deterministic-first, Jev-on-residue, bounded repair.

Every test uses the offline :class:`FakeTransport` — no live Jev call is made, and
none is claimed. The suite pins the module's hard guarantees: deterministic
rejections cost zero Jev calls; a Jev agreement is never vision verification
(unreadable regions stay ``NEEDS_REVIEW``); a repair is bounded to one region-scoped
step; a refused repair degrades instead of upgrading; and a student answer is never
rewritten into the correct answer.
"""

from __future__ import annotations

import pytest
from jev_fixtures import make_jev_database

from app.jev.errors import JevUnavailableError
from app.jev.extraction import (
    EXTRACTION_FIELD_GROUNDED_KEY,
    ExtractionRecord,
    ExtractionVerifier,
    FallbackReason,
    FieldSpec,
    RecordRole,
    StaticSourceRegistry,
    Status,
    Verdict,
    VerificationResult,
)
from app.jev.gateway import FakeTransport, JevGateway
from app.jev.models import JevAnswer, JevResult
from app.jev.receipt_store import SqlReceiptStore

KEY = EXTRACTION_FIELD_GROUNDED_KEY
CS = "cs101"

REGISTRY_SOURCES = {"src-1": ("cs101",), "src-2": ("cs202",)}


def make_record(**overrides) -> ExtractionRecord:
    params = {
        "source_id": "src-1",
        "source_version": "v1",
        "page": 3,
        "region": "q3.answer",
        "span": (12, 20),
        "question_id": "Q3",
        "part_id": None,
        "field_name": "mass",
        "candidate_value": "5",
        "unit": "kg",
        "uncertainty": 0.1,
        "extraction_version": "1.0.0",
        "supplied_text": "Q3: The mass of the block is 5 kg.",
    }
    params.update(overrides)
    return ExtractionRecord(**params)


def make_gateway(responder, *, store=None, modes=None) -> JevGateway:
    return JevGateway(
        transport=FakeTransport(responder),
        modes=modes or {KEY: "on"},
        receipt_store=store,
    )


def make_verifier(gateway, *, repair_budget=1, repair_allowed=True) -> ExtractionVerifier:
    return ExtractionVerifier(
        gateway=gateway,
        source_registry=StaticSourceRegistry(REGISTRY_SOURCES),
        field_specs={"mass": FieldSpec(kind="number", expected_unit="kg")},
        repair_budget=repair_budget,
        repair_allowed=repair_allowed,
    )


def verify_record(
    verifier: ExtractionVerifier, record: ExtractionRecord, *, course_scope: str = CS
) -> VerificationResult:
    return verifier.verify(record, course_scope=course_scope)


def _choice_responder(choice: str):
    def responder(call):
        return JevResult(answers={KEY: JevAnswer(choice=choice)})

    return responder


# --------------------------------------------------------------------------- #
# Record shape and identity
# --------------------------------------------------------------------------- #


def test_record_as_dict_carries_the_required_shape() -> None:
    record = make_record()
    payload = record.as_dict()
    for key in (
        "source_id",
        "source_version",
        "page",
        "region",
        "span",
        "question_id",
        "part_id",
        "field_name",
        "candidate_value",
        "unit",
        "uncertainty",
        "extraction_version",
    ):
        assert key in payload, key
    assert payload["role"] == "source"
    assert payload["span"] == [12, 20]


def test_identity_is_slot_stable_across_a_repair() -> None:
    original = make_record()
    repaired = make_record(candidate_value="6", supplied_text="Q3: the mass is 6 kg.")
    assert original.identity() == repaired.identity()
    assert make_record(field_name="length").identity() != original.identity()


# --------------------------------------------------------------------------- #
# Deterministic rejections cost zero Jev calls
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("record", "course_scope", "expected_code"),
    [
        # missing unit (field expects "kg", unit is None)
        (make_record(unit=None), CS, "missing_unit"),
        # shifted table cell: an empty cell under a populated header column
        (
            make_record(
                table_rows=(("mass", "length"), ("5 kg", ""), ("2 kg", "3 m")),
            ),
            CS,
            "table_shifted_cell",
        ),
        # source exists but is outside the authorized course scope
        (make_record(source_id="src-2"), CS, "source_out_of_scope"),
    ],
)
def test_deterministic_rejection_spends_zero_jev(record, course_scope, expected_code) -> None:
    calls: list[object] = []

    def responder(call):
        calls.append(call)
        return JevResult(answers={KEY: JevAnswer(choice="GROUNDED")})

    gateway = make_gateway(responder)
    verifier = make_verifier(gateway)
    result = verifier.verify(record, course_scope=course_scope)

    assert result.status is Status.REJECTED
    assert result.jev_calls == 0
    assert result.used_jev is False
    assert calls == []  # the transport was never reached
    assert any(f.code == expected_code for f in result.deterministic_failures)


# --------------------------------------------------------------------------- #
# Semantic judgments over the residue only
# --------------------------------------------------------------------------- #


def test_grounded_acceptance() -> None:
    gateway = make_gateway(_choice_responder("GROUNDED"))
    verifier = make_verifier(gateway)
    result = verify_record(verifier, make_record())

    assert result.status is Status.ACCEPTED
    assert result.verdict is Verdict.GROUNDED
    assert result.used_jev is True
    assert result.jev_calls == 1
    assert result.path == "jev"
    assert len(gateway.transport.calls) == 1
    # Jev only ever sees the residue: the one field + its supplied text.
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


def test_wrong_field_is_flagged_with_a_repair_request() -> None:
    gateway = make_gateway(_choice_responder("WRONG_FIELD"))
    verifier = make_verifier(gateway, repair_budget=1)
    result = verify_record(verifier, make_record())

    assert result.status is Status.FLAGGED
    assert result.verdict is Verdict.WRONG_FIELD
    assert result.repair_request is not None
    assert result.repair_request.field_name == "mass"
    assert result.repair_request.kind == "re_extract"
    assert result.repair_budget_remaining == 0


def test_negation_lost_is_flagged() -> None:
    gateway = make_gateway(_choice_responder("NEGATION_LOST"))
    verifier = make_verifier(gateway)
    result = verify_record(verifier, make_record())

    assert result.status is Status.FLAGGED
    assert result.verdict is Verdict.NEGATION_LOST
    assert result.repair_request is not None


# --------------------------------------------------------------------------- #
# A Jev agreement is not vision verification
# --------------------------------------------------------------------------- #


def test_unreadable_region_returns_needs_review_without_jev() -> None:
    gateway = make_gateway(_choice_responder("GROUNDED"))
    verifier = make_verifier(gateway)
    result = verify_record(verifier, make_record(unreadable=True))

    assert result.status is Status.NEEDS_REVIEW
    assert result.fallback_reason is FallbackReason.UNREADABLE_REGION
    assert result.used_jev is False
    assert result.jev_calls == 0
    assert gateway.transport.calls == []  # never a confident acceptance
    # The source region is preserved for a human/deep re-read.
    assert result.record["page"] == 3
    assert result.record["region"] == "q3.answer"


# --------------------------------------------------------------------------- #
# Bounded repair
# --------------------------------------------------------------------------- #


def test_single_repair_bound_per_extraction() -> None:
    gateway = make_gateway(_choice_responder("WRONG_FIELD"))
    verifier = make_verifier(gateway, repair_budget=5)

    first = verify_record(verifier, make_record())
    assert first.status is Status.FLAGGED
    assert first.repair_request is not None

    # The same slot (identity ignores the candidate value) may not be repaired again.
    second = verify_record(
        verifier,
        make_record(candidate_value="6", supplied_text="Q3: the mass is 6 kg."),
    )
    assert second.status is Status.NEEDS_REVIEW
    assert second.fallback_reason is FallbackReason.REPAIR_STEP_LIMIT
    assert second.repair_request is None


def test_budget_refused_repair_degrades_instead_of_upgrading() -> None:
    gateway = make_gateway(_choice_responder("WRONG_FIELD"))
    verifier = make_verifier(gateway, repair_budget=0)
    result = verify_record(verifier, make_record())

    assert result.status is Status.NEEDS_REVIEW
    assert result.fallback_reason is FallbackReason.REPAIR_BUDGET_EXHAUSTED
    assert result.repair_request is None
    assert result.verdict is Verdict.WRONG_FIELD  # diagnostic preserved, never acted on
    assert result.used_jev is False
    # The only model reached was the Jev gateway; no tier upgrade, no second provider.
    assert len(gateway.transport.calls) == 1


# --------------------------------------------------------------------------- #
# Never help a student cheat
# --------------------------------------------------------------------------- #


def test_student_answer_rewritten_to_correct_is_refused() -> None:
    gateway = make_gateway(_choice_responder("GROUNDED"))
    verifier = make_verifier(gateway, repair_budget=1)
    original = make_record(
        role=RecordRole.STUDENT_ANSWER,
        field_name="answer",
        candidate_value="x+1",
        supplied_text="student wrote x+1",
    )
    repaired = make_record(
        role=RecordRole.STUDENT_ANSWER,
        field_name="answer",
        candidate_value="2x+3",
        supplied_text="student wrote x+1",
    )

    result = verifier.apply_repair(original, repaired, correct_answer="2x+3")

    assert result.status is Status.NEEDS_REVIEW
    assert result.fallback_reason is FallbackReason.STUDENT_ANSWER_REWRITE_REFUSED
    assert result.record["candidate_value"] == "x+1"  # the original is preserved


def test_student_legibility_repair_not_to_correct_is_allowed() -> None:
    gateway = make_gateway(_choice_responder("GROUNDED"))
    verifier = make_verifier(gateway, repair_budget=1)
    original = make_record(
        role=RecordRole.STUDENT_ANSWER,
        field_name="answer",
        candidate_value="1l",
        supplied_text="student wrote 1l",
    )
    repaired = make_record(
        role=RecordRole.STUDENT_ANSWER,
        field_name="answer",
        candidate_value="11",
        supplied_text="student wrote 11",
    )

    result = verifier.apply_repair(original, repaired, correct_answer="12", course_scope=CS)

    assert result.status is Status.ACCEPTED  # legibility clarification is allowed


# --------------------------------------------------------------------------- #
# Degradation on an unavailable transport
# --------------------------------------------------------------------------- #


def test_unavailable_transport_degrades_to_needs_review() -> None:
    def responder(call):
        raise JevUnavailableError("down")

    gateway = make_gateway(responder)
    verifier = make_verifier(gateway)
    result = verify_record(verifier, make_record())

    assert result.status is Status.NEEDS_REVIEW
    assert result.fallback_reason is FallbackReason.JEV_UNAVAILABLE
    assert result.used_jev is False
    assert result.verdict is None


def test_no_gateway_is_a_typed_deterministic_fallback() -> None:
    verifier = make_verifier(None)
    result = verify_record(verifier, make_record())
    assert result.status is Status.NEEDS_REVIEW
    assert result.fallback_reason is FallbackReason.NO_SERVICE
    assert result.jev_calls == 0


# --------------------------------------------------------------------------- #
# No learning/grade/coverage row writes
# --------------------------------------------------------------------------- #


def test_verification_writes_only_receipts(tmp_path) -> None:
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

    gateway = JevGateway(
        transport=FakeTransport(_choice_responder("GROUNDED")),
        modes={KEY: "on"},
        receipt_store=SqlReceiptStore(database),
    )
    verifier = make_verifier(gateway)
    result = verify_record(verifier, make_record())
    assert result.status is Status.ACCEPTED

    with database.connect() as connection:
        journey_status = connection.execute(
            "SELECT status FROM learning_journeys WHERE id='j1'"
        ).fetchone()[0]
        grade = connection.execute(
            "SELECT raw_score FROM assessment_sessions WHERE id='s1'"
        ).fetchone()[0]
        coverage = connection.execute("SELECT COUNT(*) FROM learning_coverage").fetchone()[0]
        receipts = connection.execute(
            "SELECT COUNT(*) FROM jev_decision_receipts"
        ).fetchone()[0]

    assert journey_status == "LEARNING"
    assert grade == 78.0
    assert coverage == 1
    assert receipts >= 1  # the only write was to the Jev receipt ledger
