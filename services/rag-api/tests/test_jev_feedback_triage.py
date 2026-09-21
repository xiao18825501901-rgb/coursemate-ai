"""FeedbackTriage: user-initiated, batched, review-queue-only feedback triage.

Every test uses the offline :class:`FakeTransport` — no live Jev call is made and
none is claimed. The suite pins the module's hard guarantees: nothing is recorded
(and zero Jev calls happen) unless the user actually submits a report; a normal
report is classified and queued with exactly one batched Jev call; the default
payload is identifiers only and a body without the opt-in flag is refused; two
owners produce different receipt scopes; an unavailable transport still accepts
and queues the report with ``OTHER``; no grade/user/permission/coverage row ever
changes; and no automatic action exists on the module.
"""

from __future__ import annotations

import pytest
from jev_fixtures import make_jev_database

from app.jev.catalog import load_catalog
from app.jev.errors import JevUnavailableError
from app.jev.feedback_triage import (
    CATEGORIES,
    CATEGORY_KEY,
    FALLBACK_CATEGORY,
    FALLBACK_SEVERITY,
    SEVERITY_KEY,
    FeedbackReport,
    FeedbackTriage,
    FeedbackValidationError,
    report_key,
    suggested_queue,
)
from app.jev.gateway import FakeTransport, JevGateway
from app.jev.models import JevAnswer, JevResult
from app.jev.receipt_store import SqlReceiptStore
from app.jev.service import SemanticDecisionService

CATALOG = load_catalog()

IDENTIFIERS = ("course_id", "message_id", "run_id", "model", "template_version", "app_version")


def make_service(database, responder, *, modes=None):
    gateway = JevGateway(
        transport=FakeTransport(responder),
        catalog=CATALOG,
        modes=modes or {CATEGORY_KEY: "on", SEVERITY_KEY: "on"},
        receipt_store=SqlReceiptStore(database),
    )
    return SemanticDecisionService(gateway), gateway.transport


def make_report(**overrides) -> FeedbackReport:
    params = {
        "course_id": "c",
        "message_id": "msg-1",
        "run_id": "run-1",
        "model": "deepseek-v4",
        "template_version": "tpl-1",
        "app_version": "app-1",
    }
    params.update(overrides)
    return FeedbackReport(**params)


def _responder(category: str = "ANSWER_WRONG", severity: str = "2", *, confidence=None):
    raw = {"confidence": confidence} if confidence is not None else {}

    def responder(call):
        return JevResult(
            answers={
                CATEGORY_KEY: JevAnswer(choice=category, raw=raw),
                SEVERITY_KEY: JevAnswer(score=severity, raw=raw),
            }
        )

    return responder


# --------------------------------------------------------------------------- #
# Only a submitted report is ever recorded; zero Jev calls otherwise
# --------------------------------------------------------------------------- #


def test_no_report_means_zero_jev_calls(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    def responder(call):
        raise AssertionError("nothing may call Jev without a submitted report")

    service, transport = make_service(database, responder)
    triage = FeedbackTriage(service)

    assert transport.calls == []
    assert triage.reports == []
    assert triage.summary()["submitted"] == 0


def test_off_mode_makes_no_call(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    def responder(call):
        raise AssertionError("off mode must not spend a transport call")

    service, transport = make_service(
        database, responder, modes={CATEGORY_KEY: "off", SEVERITY_KEY: "off"}
    )
    triage = FeedbackTriage(service)
    result = triage.submit(make_report(), owner_user_id="user-a", authorization_scope="feedback")

    assert result.category == FALLBACK_CATEGORY
    assert result.severity == FALLBACK_SEVERITY
    assert result.path == "fallback:off"
    assert transport.calls == []
    assert len(triage.reports) == 1


def test_no_service_falls_back_without_any_call() -> None:
    triage = FeedbackTriage(None)
    result = triage.submit(make_report(), owner_user_id="user-a", authorization_scope="feedback")

    assert result.category == FALLBACK_CATEGORY
    assert result.severity == FALLBACK_SEVERITY
    assert result.path == "fallback:no_service"
    assert result.jev_calls == 0
    assert len(triage.reports) == 1


# --------------------------------------------------------------------------- #
# One batched Jev call for category + severity on the same state
# --------------------------------------------------------------------------- #


def test_normal_report_classified_and_queued_with_one_jev_call(tmp_path) -> None:
    database = make_jev_database(tmp_path)
    service, transport = make_service(database, _responder("ANSWER_WRONG", "2", confidence=0.9))
    triage = FeedbackTriage(service)
    result = triage.submit(make_report(), owner_user_id="user-a", authorization_scope="feedback")

    assert result.category == "ANSWER_WRONG"
    assert result.severity == 2
    assert result.path == "jev"
    assert result.used_jev is True
    assert result.jev_calls == 1
    assert result.confidence == 0.9
    assert result.suggested_queue == "priority"
    assert len(transport.calls) == 1
    # the single call carries both independent questions on the one shared state
    assert set(transport.calls[0].questions) == {CATEGORY_KEY, SEVERITY_KEY}
    assert len(triage.reports) == 1
    assert triage.reports[0] is result

    with database.connect() as connection:
        receipts = connection.execute(
            "SELECT COUNT(*) FROM jev_decision_receipts"
        ).fetchone()[0]
    assert receipts == 2  # category + severity receipts, both properly scoped


def test_invalid_category_answer_falls_back_but_severity_stays(tmp_path) -> None:
    database = make_jev_database(tmp_path)
    service, _ = make_service(database, _responder(category="NOT_A_REAL_CATEGORY", severity="2"))
    triage = FeedbackTriage(service)
    result = triage.submit(make_report(), owner_user_id="user-a", authorization_scope="feedback")

    assert result.category == FALLBACK_CATEGORY
    assert result.severity == 2
    assert result.category_path == "fallback:invalid_response"
    assert result.severity_path == "jev"
    assert result.path == "fallback:invalid_response"
    assert result.used_jev is False


def test_shadow_mode_records_suggestion_but_uses_fallback(tmp_path) -> None:
    database = make_jev_database(tmp_path)
    service, transport = make_service(
        database, _responder("ANSWER_WRONG", "2"),
        modes={CATEGORY_KEY: "shadow", SEVERITY_KEY: "shadow"},
    )
    triage = FeedbackTriage(service)
    result = triage.submit(make_report(), owner_user_id="user-a", authorization_scope="feedback")

    assert result.category == FALLBACK_CATEGORY
    assert result.severity == FALLBACK_SEVERITY
    assert result.used_jev is False
    assert result.category_path == "fallback:shadow"
    assert result.severity_path == "fallback:shadow"
    assert len(transport.calls) == 1  # shadow still records the suggestion


# --------------------------------------------------------------------------- #
# Minimal default payload + opt-in enforcement
# --------------------------------------------------------------------------- #


def test_default_payload_is_identifiers_only(tmp_path) -> None:
    database = make_jev_database(tmp_path)
    service, transport = make_service(database, _responder())
    triage = FeedbackTriage(service)
    report = make_report()  # no body, no opt-in
    result = triage.submit(report, owner_user_id="user-a", authorization_scope="feedback")

    stored = result.report
    assert stored.report_text is None
    assert stored.question_text is None
    assert stored.answer_text is None
    assert "report_text" not in stored.as_dict()
    assert "question_text" not in stored.as_dict()
    assert "answer_text" not in stored.as_dict()
    for field in IDENTIFIERS:
        assert field in stored.as_dict()

    sent = transport.calls[0].state
    assert sent["report_text"] == ""
    assert set(sent["attached_context_ids"]) == {"msg-1", "run-1", "c"}


def test_api_refuses_body_without_opt_in(tmp_path) -> None:
    database = make_jev_database(tmp_path)
    service, transport = make_service(database, _responder())
    triage = FeedbackTriage(service)

    for field, value in (
        ("report_text", "the answer is wrong"),
        ("question_text", "what is 2+2"),
        ("answer_text", "4"),
    ):
        with pytest.raises(FeedbackValidationError) as excinfo:
            triage.submit(
                make_report(**{field: value}),
                owner_user_id="user-a",
                authorization_scope="feedback",
            )
        assert excinfo.value.code == "BODY_NOT_OPTED_IN"

    assert transport.calls == []  # nothing ever reached Jev
    assert triage.reports == []


def test_opt_in_path_stores_body(tmp_path) -> None:
    database = make_jev_database(tmp_path)
    service, transport = make_service(database, _responder())
    triage = FeedbackTriage(service)
    report = make_report(
        report_text="the answer is wrong",
        question_text="what is 2+2",
        answer_text="4",
        attach_body=True,
    )
    result = triage.submit(report, owner_user_id="user-a", authorization_scope="feedback")

    stored = result.report
    assert stored.report_text == "the answer is wrong"
    assert stored.question_text == "what is 2+2"
    assert stored.answer_text == "4"
    assert result.as_dict()["report"]["report_text"] == "the answer is wrong"
    assert transport.calls[0].state["report_text"] == "the answer is wrong"


# --------------------------------------------------------------------------- #
# Scope isolation
# --------------------------------------------------------------------------- #


def test_two_owners_produce_distinct_receipt_scopes(tmp_path) -> None:
    database = make_jev_database(tmp_path)
    service, _ = make_service(database, _responder())
    triage = FeedbackTriage(service)

    for owner in ("user-a", "user-b"):
        triage.submit(make_report(), owner_user_id=owner, authorization_scope="feedback")

    with database.connect() as connection:
        hashes = [
            row[0]
            for row in connection.execute(
                "SELECT owner_scope_hash FROM jev_decision_receipts ORDER BY rowid"
            ).fetchall()
        ]
    assert len(hashes) == 4  # two receipts per report × two owners
    assert hashes[0] == hashes[1]  # one owner's two receipts share a scope
    assert hashes[0] != hashes[2]  # a different owner never shares the scope
    assert len(set(hashes)) == 2


# --------------------------------------------------------------------------- #
# Degradation: Jev unavailable still accepts and queues the report
# --------------------------------------------------------------------------- #


def test_unavailable_transport_still_accepts_and_queues(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    def responder(call):
        raise JevUnavailableError("down")

    service, transport = make_service(database, responder)
    triage = FeedbackTriage(service)
    result = triage.submit(make_report(), owner_user_id="user-a", authorization_scope="feedback")

    assert result.category == FALLBACK_CATEGORY
    assert result.severity == FALLBACK_SEVERITY
    assert result.path == "fallback:unavailable"
    assert result.used_jev is False
    assert result.jev_calls == 0
    assert len(triage.reports) == 1  # the report was never lost
    assert len(transport.calls) == 1  # one attempted call


# --------------------------------------------------------------------------- #
# Review queue, not automation: no state rows change, no action callable exists
# --------------------------------------------------------------------------- #


def test_no_grade_user_permission_coverage_rows_changed(tmp_path) -> None:
    database = make_jev_database(tmp_path)
    with database.connect() as connection:
        connection.executescript(
            """
            CREATE TABLE users (id TEXT PRIMARY KEY, status TEXT);
            CREATE TABLE permissions (id TEXT PRIMARY KEY, granted TEXT);
            CREATE TABLE learning_journeys (id TEXT PRIMARY KEY, node_id TEXT, status TEXT);
            CREATE TABLE assessment_sessions (id TEXT PRIMARY KEY, raw_score REAL, status TEXT);
            CREATE TABLE learning_coverage (id TEXT PRIMARY KEY, journey_id TEXT, item_id TEXT);
            INSERT INTO users VALUES('u1','active');
            INSERT INTO permissions VALUES('p1','teach');
            INSERT INTO learning_journeys VALUES('j1','n1','LEARNING');
            INSERT INTO assessment_sessions VALUES('s1',78.0,'GRADED');
            INSERT INTO learning_coverage VALUES('c1','j1','item-a');
            """
        )

    service, _ = make_service(database, _responder())
    triage = FeedbackTriage(service)
    result = triage.submit(make_report(), owner_user_id="user-a", authorization_scope="feedback")
    assert result.category == "ANSWER_WRONG"

    with database.connect() as connection:
        user_status = connection.execute("SELECT status FROM users WHERE id='u1'").fetchone()[0]
        permission = connection.execute(
            "SELECT granted FROM permissions WHERE id='p1'"
        ).fetchone()[0]
        journey = connection.execute(
            "SELECT status FROM learning_journeys WHERE id='j1'"
        ).fetchone()[0]
        grade = connection.execute(
            "SELECT raw_score FROM assessment_sessions WHERE id='s1'"
        ).fetchone()[0]
        coverage = connection.execute("SELECT COUNT(*) FROM learning_coverage").fetchone()[0]
        receipts = connection.execute("SELECT COUNT(*) FROM jev_decision_receipts").fetchone()[0]

    assert user_status == "active"
    assert permission == "teach"
    assert journey == "LEARNING"
    assert grade == 78.0
    assert coverage == 1
    assert receipts >= 2  # the only write was to the Jev receipt ledger


def test_no_automatic_action_callable_exists() -> None:
    forbidden = {
        "close", "delete", "resolve", "reopen", "ban", "limit", "silence",
        "grade", "change_mark", "set_grade", "update_grade", "remove",
    }
    for name in forbidden:
        assert not hasattr(FeedbackTriage, name), f"FeedbackTriage must not expose {name!r}"

    public = {name for name in dir(FeedbackTriage) if not name.startswith("_")}
    assert public == {"submit", "summary"}


# --------------------------------------------------------------------------- #
# Privacy: dedup by object id + version + scope, never by private text
# --------------------------------------------------------------------------- #


def test_report_key_ignores_body_and_tracks_scope() -> None:
    base = make_report()
    with_body = make_report(report_text="a different complaint", attach_body=True)

    assert report_key(base, "hash-a") == report_key(with_body, "hash-a")
    assert report_key(base, "hash-a") != report_key(base, "hash-b")


def test_duplicate_reports_share_key_across_text(tmp_path) -> None:
    database = make_jev_database(tmp_path)
    service, _ = make_service(database, _responder())
    triage = FeedbackTriage(service)

    first = triage.submit(
        make_report(), owner_user_id="user-a", authorization_scope="feedback"
    ).report_key
    second = triage.submit(
        make_report(report_text="a different complaint", attach_body=True),
        owner_user_id="user-a",
        authorization_scope="feedback",
    ).report_key
    other_owner = triage.submit(
        make_report(), owner_user_id="user-b", authorization_scope="feedback"
    ).report_key

    assert first == second  # same object + version + scope, regardless of text
    assert first != other_owner


# --------------------------------------------------------------------------- #
# Suggested queue is a deterministic routing hint, never an action
# --------------------------------------------------------------------------- #


def test_suggested_queue_is_deterministic() -> None:
    assert suggested_queue("SERVICE_FAULT", 1) == "service"
    assert suggested_queue("GRADING_DISPUTE", 1) == "grading"
    assert suggested_queue("ANSWER_WRONG", 1) == "content"
    assert suggested_queue("OTHER", 1) == "triage"
    assert suggested_queue("ANSWER_WRONG", 2) == "priority"


def test_categories_match_catalog() -> None:
    definition = CATALOG.get(CATEGORY_KEY)
    assert set(definition.criteria) == set(CATEGORIES)
    severity = CATALOG.get(SEVERITY_KEY)
    assert severity.score_levels == ("0", "1", "2")
