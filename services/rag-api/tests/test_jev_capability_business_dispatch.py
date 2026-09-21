"""Module E (TeachingCapabilityRouter): the routed capability must reach the business path.

A capability decision that is only written to the receipt ledger is not an
integration, so these tests prove the value is *consumed*:

* the code-owned baseline is the flow the shell already took — a node-bound run
  keeps the journey-bound teaching flow, and shadow never changes it;
* an explicit answer-only command really answers only (no V3 journey is bound,
  nothing is written to the learning ledger) at **zero Jev cost**;
* a capability this endpoint does not implement can never be dispatched;
* end to end through the real app, the recorded capability and the database rows
  agree.

The semantic layer runs on the offline ``FakeTransport``: no network is used.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jev_fixtures import make_jev_database

# The integrated-app harness (settings, verifiers, fake model, seeding) is shared
# with the learning-closure suite instead of being re-invented here.
from test_ui_extension_learning_closure import (
    UI,
    FakeAuthVerifier,
    FakeEmbeddingProvider,
    FakeUiProvider,
    auth,
    create_course_and_seed,
    make_settings,
    wait_terminal,
)

from app.cm_update.app import ANSWER_ONLY_SKILLS, TEACHING_FLOW_SKILLS, run_capability
from app.jev.catalog import load_catalog
from app.jev.gateway import FakeTransport, JevGateway
from app.jev.models import JevAnswer, JevResult
from app.jev.receipt_store import SqlReceiptStore
from app.jev.service import SemanticDecisionService
from app.main import create_app

CATALOG = load_catalog()
CAPABILITY_KEY = "teaching.capability.v1"
ANSWER_ONLY_TEXT = "\u53ea\u56de\u7b54"
TEACHING_TEXT = "\u8bf7\u4ece\u96f6\u6559\u6211\u7406\u89e3\u8fd9\u4e2a\u8282\u70b9"
CONTINUE_TEXT = "\u7ee7\u7eed"


@pytest.fixture
def ui_client(tmp_path: Path) -> Iterator[TestClient]:
    """The real app (mounted UI extension, injected identity, deterministic model)."""

    provider = FakeUiProvider()
    application = create_app(
        settings=make_settings(tmp_path),
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
        ui_provider=provider,
    )
    with TestClient(application) as test_client:
        from campus_actor_fixture import authorize_synthetic_campus_users

        authorize_synthetic_campus_users(test_client, "user-a", "user-b")
        test_client.app.state.ui_provider = provider  # type: ignore[attr-defined]
        yield test_client


def _service(database, responder, *, mode: str | None = None) -> SemanticDecisionService:
    modes = {CAPABILITY_KEY: mode} if mode is not None else None
    gateway = JevGateway(
        transport=FakeTransport(responder),
        catalog=CATALOG,
        receipt_store=SqlReceiptStore(database),
        modes=modes,
    )
    return SemanticDecisionService(gateway)


def _receipts(database) -> int:
    with database.connect() as connection:
        return int(
            connection.execute("SELECT COUNT(*) FROM jev_decision_receipts").fetchone()[0]
        )


def _call(service, **overrides):
    arguments = {
        "text": TEACHING_TEXT,
        "explicit_action": None,
        "node_bound": True,
        "pair_binding": "pair-1",
        "teaching_mode": "normal",
        "owner_user_id": "user-a",
        "course_id": "jev-course",
    }
    arguments.update(overrides)
    return run_capability(service, **arguments)


def _hostile(choice: str):
    def responder(call):
        return JevResult(answers={CAPABILITY_KEY: JevAnswer(choice=choice)})

    return responder


# --------------------------------------------------------------------------- #
# baseline: the deterministic flow the shell already took
# --------------------------------------------------------------------------- #


def test_node_bound_run_keeps_the_teaching_flow_without_jev(tmp_path) -> None:
    resolution, skill_id, teaching_flow = _call(None)
    assert resolution is None
    assert skill_id == "node_lesson"
    assert teaching_flow is True


def test_non_node_run_is_answer_only(tmp_path) -> None:
    resolution, skill_id, teaching_flow = _call(None, node_bound=False, pair_binding=None)
    assert resolution is None
    assert skill_id == "direct_qa"
    assert teaching_flow is False


# --------------------------------------------------------------------------- #
# explicit commands: deterministic, zero Jev, and actually honoured
# --------------------------------------------------------------------------- #


def test_explicit_answer_only_answers_only_at_zero_jev_cost(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    def never_called(call):  # pragma: no cover - must not be reached
        raise AssertionError("an explicit command must not spend a Jev call")

    resolution, skill_id, teaching_flow = _call(
        _service(database, never_called), text=ANSWER_ONLY_TEXT, explicit_action="ANSWER_ONLY"
    )
    assert resolution is not None
    assert resolution.used_jev is False
    assert resolution.path == "fallback:explicit_command_forbidden"
    assert skill_id == "direct_qa"
    assert teaching_flow is False  # the request really answers only
    assert _receipts(database) == 0  # provably zero Jev calls


def test_explicit_continue_keeps_the_teaching_flow_at_zero_jev_cost(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    def never_called(call):  # pragma: no cover - must not be reached
        raise AssertionError("an explicit command must not spend a Jev call")

    resolution, skill_id, teaching_flow = _call(
        _service(database, never_called), text=CONTINUE_TEXT, explicit_action="CONTINUE"
    )
    assert resolution is not None
    assert resolution.path == "deterministic:explicit_command"
    assert skill_id == "node_lesson"
    assert teaching_flow is True
    assert _receipts(database) == 0


def test_explicit_continue_wins_over_a_hostile_shadow_choice(tmp_path) -> None:
    """An explicit command is never overridden by the semantic layer."""

    database = make_jev_database(tmp_path)
    _, skill_id, teaching_flow = _call(
        _service(database, _hostile("figure_explanation")),
        text=CONTINUE_TEXT,
        explicit_action="CONTINUE",
    )
    assert skill_id == "node_lesson"
    assert teaching_flow is True
    assert _receipts(database) == 0


# --------------------------------------------------------------------------- #
# shadow: recorded, never acted on
# --------------------------------------------------------------------------- #


def test_shadow_choice_is_recorded_but_never_changes_the_flow(tmp_path) -> None:
    database = make_jev_database(tmp_path)
    service = _service(database, _hostile("direct_qa"))

    resolution, skill_id, teaching_flow = _call(service)

    # The call really happened (a receipt was written; an illegal answer costs one
    # extra disambiguation round, which is the documented bound) ...
    assert _receipts(database) >= 1
    assert resolution is not None and resolution.used_jev is False
    # ... and the code-owned flow was still the one taken.
    assert skill_id == "node_lesson"
    assert teaching_flow is True


def test_normal_run_refuses_a_thinking_only_capability_even_in_on_mode(tmp_path) -> None:
    """The hard invariant: a normal request can never gain a Thinking-only capability."""

    database = make_jev_database(tmp_path)
    service = _service(database, _hostile("worked_example"), mode="on")

    resolution, skill_id, teaching_flow = _call(service, teaching_mode="normal")
    assert resolution is not None
    assert "worked_example" not in resolution.offered_candidates
    assert skill_id == "node_lesson"
    assert teaching_flow is True


def test_mode_on_cannot_offer_or_dispatch_a_skill_this_endpoint_lacks(tmp_path) -> None:
    """Even a live, hostile answer can only pick among the served capabilities."""

    database = make_jev_database(tmp_path)
    service = _service(database, _hostile("exercise"), mode="on")

    resolution, skill_id, teaching_flow = _call(service)
    assert resolution is not None
    assert "exercise" not in resolution.offered_candidates
    assert skill_id == "node_lesson"  # `exercise` is not servable here
    assert teaching_flow is True

    _, answer_only_skill, answer_only_flow = _call(
        service, node_bound=False, pair_binding=None
    )
    assert answer_only_skill in ANSWER_ONLY_SKILLS
    assert answer_only_flow is False


def test_mode_on_choice_inside_the_served_set_is_dispatched(tmp_path) -> None:
    """In `on`, a legal choice inside the served set is the dispatched capability."""

    database = make_jev_database(tmp_path)
    # `worked_example` is a Thinking-only capability, so it is legal exactly when
    # the run itself is a Thinking run.
    service = _service(database, _hostile("worked_example"), mode="on")

    resolution, skill_id, teaching_flow = _call(service, teaching_mode="thinking")
    assert resolution is not None
    # Only the capabilities this endpoint serves were ever offered.
    assert set(resolution.offered_candidates) <= set(TEACHING_FLOW_SKILLS)
    assert "worked_example" in resolution.offered_candidates
    assert "direct_qa" not in resolution.offered_candidates
    assert resolution.used_jev is True
    assert skill_id == "worked_example"
    assert teaching_flow is True  # same existing journey-bound handler
    assert _receipts(database) == 1


# --------------------------------------------------------------------------- #
# end to end through the real app
# --------------------------------------------------------------------------- #


def _cmui_rows(application, sql: str, parameters: tuple) -> list[dict]:
    with application.state.ui_extension_app.state.db.connect() as connection:
        return [dict(row) for row in connection.execute(sql, parameters)]


def _journeys(client: TestClient, node_id: str) -> list[str]:
    with client.app.state.database.connect() as connection:
        rows = connection.execute(
            "SELECT status FROM learning_journeys WHERE node_id=?", (node_id,)
        ).fetchall()
    return [row["status"] for row in rows]


def test_answer_only_run_does_not_bind_the_journey_end_to_end(
    ui_client: TestClient,
) -> None:
    client = ui_client
    node_id = create_course_and_seed(client)
    conversation = client.post(
        f"{UI}/conversations",
        headers=auth("Bearer token-a"),
        json={"course": "cs3481", "lane": "teach"},
    )
    assert conversation.status_code == 201, conversation.text
    conv_id = conversation.json()["id"]

    answer_only = client.post(
        f"{UI}/conversations/{conv_id}/runs",
        headers=auth("Bearer token-a"),
        json={
            "text": ANSWER_ONLY_TEXT,
            "request_id": "dispatch-answer-only-000001",
            "node_id": node_id,
        },
    )
    assert answer_only.status_code == 202, answer_only.text
    body = answer_only.json()
    # The decision is reported, not inferred: this run answers without teaching.
    assert body["capability"]["skill_id"] == "direct_qa"
    assert body["capability"]["teaching_flow"] is False
    assert body["capability"]["used_jev"] is False
    assert body["capability"]["explicit_command"] == "ANSWER_ONLY"
    wait_terminal(client, body["id"])

    # Nothing was bound to the lesson: no V3 cross-reference, no learning journey.
    assert (
        _cmui_rows(client.app, "SELECT * FROM cmui_run_v3 WHERE run=?", (body["id"],))
        == []
    )
    assert _journeys(client, node_id) == []

    # The ordinary teaching request still takes the journey-bound flow.
    teaching = client.post(
        f"{UI}/conversations/{conv_id}/runs",
        headers=auth("Bearer token-a"),
        json={
            "text": TEACHING_TEXT,
            "request_id": "dispatch-teaching-000002",
            "node_id": node_id,
        },
    )
    assert teaching.status_code == 202, teaching.text
    teaching_body = teaching.json()
    assert teaching_body["capability"]["skill_id"] == "node_lesson"
    assert teaching_body["capability"]["teaching_flow"] is True
    wait_terminal(client, teaching_body["id"])

    links = _cmui_rows(
        client.app,
        "SELECT * FROM cmui_run_v3 WHERE run=?",
        (teaching_body["id"],),
    )
    assert len(links) == 1
    assert _journeys(client, node_id) == ["LEARNING"]
