"""TeachingCapabilityRouter: code filters first, Jev selects one legal candidate only.

Every test uses the offline :class:`FakeTransport` — no live Jev call is made, and
none is claimed. The suite pins the router's hard guarantees: explicit commands cost
zero Jev calls; a normal request is never routed to a Thinking-only capability; a
hidden-answer capability is excluded while the answer is unrevealed; assessment-state
preconditions are enforced in code; an illegal candidate proposed by the transport is
rejected; ``NO_SKILL`` keeps the legal default; and the candidate list is narrowed
with a one-round disambiguation bound.
"""

from __future__ import annotations

from jev_fixtures import make_jev_database

from app.jev.capability_router import (
    CAPABILITY_CATALOG,
    DEFAULT_SKILL,
    MAX_OFFERED_CANDIDATES,
    NO_SKILL,
    CapabilityRequest,
    TeachingCapabilityRouter,
    filter_candidates,
)
from app.jev.catalog import load_catalog
from app.jev.gateway import FakeTransport, JevGateway
from app.jev.models import JevAnswer, JevResult
from app.jev.receipt_store import SqlReceiptStore
from app.jev.service import SemanticDecisionService

CATALOG = load_catalog()
KEY = "teaching.capability.v1"

ALL_PERMISSIONS = frozenset({"teach", "exercise", "assess"})


def make_request(**overrides) -> CapabilityRequest:
    params = {
        "learner_request": "给我讲一下 K-means 聚类",
        "product_mode": "teach",
        "revealed_state": False,
        "active_assessment": None,
        "pair_binding": "pair-1",
        "candidate_skills": (),
        "mode": "normal",
        "permissions": ALL_PERMISSIONS,
        "explicit_command": None,
        "enabled_skills": None,
        "default_skill": DEFAULT_SKILL,
    }
    params.update(overrides)
    return CapabilityRequest(**params)


def make_service(database, responder, *, modes=None):
    gateway = JevGateway(
        transport=FakeTransport(responder),
        catalog=CATALOG,
        modes=modes or {KEY: "on"},
        receipt_store=SqlReceiptStore(database),
    )
    return SemanticDecisionService(gateway), gateway.transport


def scope_kwargs(**overrides):
    params = {
        "owner_user_id": "user-a",
        "authorization_scope": "capability",
        "course_id": "c",
    }
    params.update(overrides)
    return params


def _choice_responder(choice: str):
    def responder(call):
        return JevResult(answers={KEY: JevAnswer(choice=choice)})

    return responder


# --------------------------------------------------------------------------- #
# Stage 1: deterministic filters (zero Jev calls)
# --------------------------------------------------------------------------- #


def test_filter_excludes_thinking_only_capabilities_in_normal_mode() -> None:
    normal = make_request(mode="normal")
    assert "worked_example" not in filter_candidates(normal)
    assert "code_trace" not in filter_candidates(normal)
    thinking = make_request(mode="thinking")
    assert "worked_example" in filter_candidates(thinking)
    assert "code_trace" in filter_candidates(thinking)


def test_filter_excludes_hidden_answer_capability_while_unrevealed() -> None:
    assert "step_explanation" not in filter_candidates(make_request(revealed_state=False))
    assert "step_explanation" in filter_candidates(make_request(revealed_state=True))


def test_filter_enforces_assessment_state_preconditions() -> None:
    # assessment_submission needs an active assessment and the assess product mode.
    assert "assessment_submission" not in filter_candidates(
        make_request(product_mode="assess", active_assessment=None)
    )
    assert "assessment_submission" in filter_candidates(
        make_request(product_mode="assess", active_assessment="session-1")
    )
    # teaching capabilities are forbidden while an assessment occupies the screen.
    with_assessment = make_request(active_assessment="session-1")
    survivors = filter_candidates(with_assessment)
    assert "node_lesson" not in survivors
    assert "exercise" not in survivors
    assert "direct_qa" not in survivors


def test_filter_enforces_permissions_and_disabled_entry_points() -> None:
    no_permissions = make_request(permissions=frozenset())
    survivors = filter_candidates(no_permissions)
    assert "node_lesson" not in survivors  # requires permission:teach
    assert "exercise" not in survivors  # requires permission:exercise

    disabled = make_request(enabled_skills=frozenset({"direct_qa"}))
    survivors = filter_candidates(disabled)
    assert "node_lesson" not in survivors  # a disabled entry point is never re-enabled
    assert survivors == ("direct_qa",)


def test_filter_respects_server_candidate_hint() -> None:
    hinted = make_request(candidate_skills=("direct_qa", "exercise"))
    survivors = filter_candidates(hinted)
    assert set(survivors) <= {"direct_qa", "exercise"}


# --------------------------------------------------------------------------- #
# Stage 2: Jev selection + fallback policy
# --------------------------------------------------------------------------- #


def test_explicit_command_short_circuits_with_zero_jev_calls(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    def responder(call):
        raise AssertionError("an explicit command must not spend a Jev call")

    service, transport = make_service(database, responder)
    router = TeachingCapabilityRouter(service)
    resolution = router.resolve(make_request(explicit_command="QUIZ_WAIT"), **scope_kwargs())

    assert resolution.skill_id == "exercise"
    assert resolution.capability is CAPABILITY_CATALOG["exercise"]
    assert resolution.handler == CAPABILITY_CATALOG["exercise"].handler
    assert resolution.path == "deterministic:explicit_command"
    assert resolution.used_jev is False
    assert resolution.jev_calls == 0
    assert transport.calls == []  # zero Jev calls


def test_explicit_command_honours_hard_invariants(tmp_path) -> None:
    """An explicit command still cannot route to a capability the filters forbid."""
    database = make_jev_database(tmp_path)
    service, transport = make_service(database, _choice_responder("exercise"))
    router = TeachingCapabilityRouter(service)

    # "交卷" (SUBMIT_ASSESSMENT) without an active assessment is forbidden.
    resolution = router.resolve(
        make_request(explicit_command="SUBMIT_ASSESSMENT"), **scope_kwargs()
    )
    assert resolution.skill_id == DEFAULT_SKILL
    assert resolution.path == "fallback:explicit_command_forbidden"
    assert transport.calls == []


def test_normal_request_never_routed_to_thinking_only(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    # A hostile transport proposes a Thinking-only capability in normal mode.
    service, _ = make_service(database, _choice_responder("worked_example"))
    router = TeachingCapabilityRouter(service)
    resolution = router.resolve(make_request(mode="normal"), **scope_kwargs())

    assert resolution.skill_id != "worked_example"
    assert resolution.capability is None or resolution.capability.skill_id != "worked_example"
    assert resolution.skill_id == DEFAULT_SKILL


def test_hidden_answer_capability_not_routed_while_unrevealed(tmp_path) -> None:
    database = make_jev_database(tmp_path)
    service, _ = make_service(database, _choice_responder("step_explanation"))
    router = TeachingCapabilityRouter(service)
    resolution = router.resolve(make_request(revealed_state=False), **scope_kwargs())

    assert resolution.capability is None or resolution.capability.skill_id != "step_explanation"
    assert resolution.skill_id == DEFAULT_SKILL


def test_illegal_candidate_proposed_by_transport_is_rejected(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    # Only direct_qa survives; the transport tries to force node_lesson (illegal).
    service, transport = make_service(database, _choice_responder("node_lesson"))
    router = TeachingCapabilityRouter(service)
    resolution = router.resolve(
        make_request(candidate_skills=("direct_qa",)), **scope_kwargs()
    )

    assert resolution.capability is None or resolution.capability.skill_id != "node_lesson"
    assert resolution.skill_id == DEFAULT_SKILL
    assert resolution.used_jev is False
    assert len(transport.calls) == 1  # one call, then rejected


def test_no_skill_keeps_legal_default(tmp_path) -> None:
    database = make_jev_database(tmp_path)
    service, transport = make_service(database, _choice_responder(NO_SKILL))
    router = TeachingCapabilityRouter(service)
    resolution = router.resolve(
        make_request(candidate_skills=("direct_qa",)), **scope_kwargs()
    )

    assert resolution.skill_id == DEFAULT_SKILL
    assert resolution.capability is CAPABILITY_CATALOG[DEFAULT_SKILL]
    assert resolution.used_jev is False
    assert resolution.path == "fallback:no_skill"
    assert len(transport.calls) == 1


def test_candidate_list_narrowed_and_disambiguation_bounded(tmp_path) -> None:
    database = make_jev_database(tmp_path)
    calls = []

    def responder(call):
        calls.append(call)
        if len(calls) == 1:
            return JevResult(answers={KEY: JevAnswer(choice=NO_SKILL)})
        return JevResult(answers={KEY: JevAnswer(choice="node_lesson")})

    service, _ = make_service(database, responder)
    router = TeachingCapabilityRouter(service)
    resolution = router.resolve(make_request(), **scope_kwargs())

    # More survivors exist than are offered, so the offered list is capped.
    assert len(resolution.offered_candidates) <= MAX_OFFERED_CANDIDATES
    assert resolution.offered_candidates == (
        "direct_qa",
        "node_lesson",
        "prerequisite_explanation",
        "figure_explanation",
    )
    assert resolution.disambiguation_rounds <= 1
    assert resolution.jev_calls <= 2
    assert resolution.skill_id == "node_lesson"
    assert resolution.path == "jev:disambiguated"


def test_jev_selection_returns_usable_capability_and_handler(tmp_path) -> None:
    database = make_jev_database(tmp_path)
    service, _ = make_service(database, _choice_responder("node_lesson"))
    router = TeachingCapabilityRouter(service)
    resolution = router.resolve(make_request(), **scope_kwargs())

    assert resolution.skill_id == "node_lesson"
    assert resolution.capability is CAPABILITY_CATALOG["node_lesson"]
    assert resolution.handler == "app.learning.orchestrator.LearningOrchestrator.teach"
    assert resolution.used_jev is True
    assert resolution.path == "jev"


def test_no_service_and_no_candidates_keep_default() -> None:
    router = TeachingCapabilityRouter(None)
    assert router.resolve(make_request(), **scope_kwargs()).skill_id == DEFAULT_SKILL
    assert router.resolve(make_request(), **scope_kwargs()).used_jev is False
    assert router.resolve(make_request(), **scope_kwargs()).jev_calls == 0

    assert router.resolve(
        make_request(candidate_skills=("nonexistent",)), **scope_kwargs()
    ).path == "fallback:no_candidates"


# --------------------------------------------------------------------------- #
# No learning/grade/coverage row writes
# --------------------------------------------------------------------------- #


def test_capability_routing_writes_only_receipts(tmp_path) -> None:
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

    service, _ = make_service(database, _choice_responder("node_lesson"))
    router = TeachingCapabilityRouter(service)
    resolution = router.resolve(make_request(), **scope_kwargs())
    assert resolution.skill_id == "node_lesson"

    with database.connect() as connection:
        journey_status = connection.execute(
            "SELECT status FROM learning_journeys WHERE id='j1'"
        ).fetchone()[0]
        grade = connection.execute(
            "SELECT raw_score FROM assessment_sessions WHERE id='s1'"
        ).fetchone()[0]
        coverage = connection.execute("SELECT COUNT(*) FROM learning_coverage").fetchone()[0]
        receipts = connection.execute("SELECT COUNT(*) FROM jev_decision_receipts").fetchone()[0]

    assert journey_status == "LEARNING"
    assert grade == 78.0
    assert coverage == 1
    assert receipts >= 1  # the only write was to the Jev receipt ledger


# --------------------------------------------------------------------------- #
# Genuine scope isolation: receipts are owner-scoped, never a constant
# --------------------------------------------------------------------------- #


def test_two_owners_produce_distinct_receipt_scopes(tmp_path) -> None:
    database = make_jev_database(tmp_path)
    service, _ = make_service(database, _choice_responder("direct_qa"))
    router = TeachingCapabilityRouter(service)

    for owner in ("user-a", "user-b"):
        router.resolve(
            make_request(candidate_skills=("direct_qa",)),
            **scope_kwargs(owner_user_id=owner),
        )

    with database.connect() as connection:
        hashes = [
            row[0]
            for row in connection.execute(
                "SELECT owner_scope_hash FROM jev_decision_receipts ORDER BY rowid"
            ).fetchall()
        ]
    assert len(hashes) == 2
    assert hashes[0] != hashes[1]


def test_private_and_public_authorization_scopes_hash_differently(tmp_path) -> None:
    """A private scope must never hash the same as a public one."""
    database = make_jev_database(tmp_path)
    service, _ = make_service(database, _choice_responder("direct_qa"))
    router = TeachingCapabilityRouter(service)

    router.resolve(
        make_request(candidate_skills=("direct_qa",)),
        **scope_kwargs(authorization_scope="official"),
    )
    router.resolve(
        make_request(candidate_skills=("direct_qa",)),
        **scope_kwargs(authorization_scope="mine"),
    )

    with database.connect() as connection:
        hashes = [
            row[0]
            for row in connection.execute(
                "SELECT owner_scope_hash FROM jev_decision_receipts ORDER BY rowid"
            ).fetchall()
        ]
    assert len(hashes) == 2
    assert hashes[0] != hashes[1]
