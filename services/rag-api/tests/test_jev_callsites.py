"""The 12 Jev call sites: business behaviour, fallbacks, budget, and no-state-write.

These tests exercise the real call sites in :mod:`app.jev.callsites` and the
wired business paths (:class:`V3DomainAdapter`, :class:`AssessmentService`) with
an offline :class:`FakeTransport`. No live Jev call is made.
"""

from __future__ import annotations

from jev_fixtures import make_jev_database

from app.jev import callsites
from app.jev.catalog import load_catalog
from app.jev.errors import JevUnavailableError
from app.jev.gateway import FakeTransport, JevGateway
from app.jev.models import JevAnswer, JevResult
from app.jev.receipt_store import SqlReceiptStore
from app.jev.service import SemanticDecisionService, TemplateOption
from app.learning.assessments import AssessmentService
from app.learning.intent_commands import route_explicit_command
from app.learning.retrieval_orchestrator import FusedHit

CATALOG = load_catalog()


def make_service(database, responder, *, modes=None):
    gateway = JevGateway(
        transport=FakeTransport(responder),
        catalog=CATALOG,
        modes=modes or {},
        receipt_store=SqlReceiptStore(database),
    )
    return SemanticDecisionService(gateway), gateway.transport


def scope_for(service, *, authorization="retrieval", course="c"):
    return service.scope(
        owner_user_id="user-a", authorization_scope=authorization, course_id=course
    )


# --------------------------------------------------------------------------- #
# 1. Exact-target protection under a hostile re-rank
# --------------------------------------------------------------------------- #

def test_rerank_exact_target_keeps_slot_under_hostile_rerank(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    def hostile(call):
        # The model tries to bury the exact target by boosting every non-exact
        # candidate. The exact target is never even offered to Jev (it keeps its
        # slot unconditionally), so this responder can only shuffle the rest.
        return JevResult(answers={"retrieval.support.v1": JevAnswer(score="4")})

    service, _ = make_service(database, hostile, modes={"retrieval.support.v1": "on"})
    entries = [
        _fused("a", exact=False, score=0.1),
        _fused("exact", exact=True, score=0.0),
        _fused("b", exact=False, score=0.2),
    ]
    result = callsites.rerank_retrieval(service, entries, query="q", scope=scope_for(service))
    # Exact target holds its original index (1) no matter how the rest is shuffled.
    assert result[1].chunk_id == "exact-chunk-1"
    assert {e.chunk_id for e in result} == {"a-chunk-1", "exact-chunk-1", "b-chunk-1"}


# --------------------------------------------------------------------------- #
# 2. Private candidates still ranked (reorder only; never dropped)
# --------------------------------------------------------------------------- #

def test_rerank_private_candidate_still_ranked(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    def responder(call):
        cid = call.state["candidate_id"]
        score = "4" if cid.startswith("private") else "0"
        return JevResult(answers={"retrieval.support.v1": JevAnswer(score=score)})

    service, _ = make_service(database, responder, modes={"retrieval.support.v1": "on"})
    entries = [
        _fused("official", exact=False, scopes=("official",), score=0.5),
        _fused("private", exact=False, scopes=("mine",), score=0.4),
    ]
    result = callsites.rerank_retrieval(service, entries, query="q", scope=scope_for(service))
    assert {e.chunk_id for e in result} == {"official-chunk-1", "private-chunk-1"}  # never dropped
    assert [e.chunk_id for e in result] == ["private-chunk-1", "official-chunk-1"]


# --------------------------------------------------------------------------- #
# 3. Explicit commands make zero Jev calls
# --------------------------------------------------------------------------- #

def test_explicit_commands_make_zero_jev_calls(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    def responder(call):
        return JevResult(answers={"intent.next_action.v1": JevAnswer(choice="CONTINUE")})

    service, transport = make_service(database, responder, modes={"intent.next_action.v1": "on"})
    for message in ("继续", "暂停", "只回答", "做一题"):
        assert route_explicit_command(message) is not None  # deterministic router answers it
    # "交卷" without an active assessment is correctly a no-op (nothing to submit).
    assert route_explicit_command("交卷") is None
    assert route_explicit_command("交卷", active_assessment="a1") == "SUBMIT_ASSESSMENT"
    assert transport.calls == []  # no Jev call was spent on explicit commands


# --------------------------------------------------------------------------- #
# 4. MUST_KEEP anchors never dropped even when transport says drop
# --------------------------------------------------------------------------- #

def test_context_must_keep_anchor_preserved_when_transport_says_drop(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    def responder(call):
        return JevResult(answers={"context.keep_segment.v1": JevAnswer(noul=0.0)})

    service, transport = make_service(database, responder, modes={"context.keep_segment.v1": "on"})
    anchor = {"question": "求导 f(x)=x^2", "numbers": [2], "units": "m/s", "return_point": "step-3"}
    kept = callsites.keep_history_segment(
        service,
        segment="old unrelated chat about lunch",
        current_task="求导 f(x)=x^2",
        fixed_anchor=anchor,
        remaining_scope="chapter-1",
        scope=scope_for(service, authorization="context"),
    )
    assert kept is False  # a real Jev signal may drop a FILTERABLE segment
    # The fixed anchor is outside the selector and is sent verbatim, never dropped.
    assert transport.calls[0].state["fixed_anchor"] == anchor
    assert transport.calls[0].state["segment"] == "old unrelated chat about lunch"


def test_context_shadow_never_drops_segment(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    def responder(call):
        return JevResult(answers={"context.keep_segment.v1": JevAnswer(noul=0.0)})

    service, _ = make_service(database, responder, modes={"context.keep_segment.v1": "shadow"})
    kept = callsites.keep_history_segment(
        service,
        segment="filterable segment",
        current_task="q",
        fixed_anchor={"question": "q"},
        remaining_scope="s",
        scope=scope_for(service, authorization="context"),
    )
    assert kept is True  # shadow: deterministic keep


# --------------------------------------------------------------------------- #
# 5. Coverage staying pending on fallback (never "student incomplete")
# --------------------------------------------------------------------------- #

def test_coverage_item_support_uncertain_on_fallback(tmp_path) -> None:
    database = make_jev_database(tmp_path)
    service, _ = make_service(
        database, lambda call: JevResult(answers={}), modes={"coverage.item_support.v1": "on"}
    )
    signals = callsites.coverage_item_support(
        service,
        [{"item_id": "a", "requirement": "REQUIRED"}],
        content="x",
        spec_version=1,
        scope=scope_for(service, authorization="coverage"),
    )
    assert signals == {"a": "UNCERTAIN"}  # fallback never claims completion


def test_coverage_service_none_is_uncertain() -> None:
    signals = callsites.coverage_item_support(
        None,
        [{"item_id": "a"}, {"item_id": "b"}],
        content="x",
        spec_version=1,
        scope=None,
    )
    assert signals == {"a": "UNCERTAIN", "b": "UNCERTAIN"}


# --------------------------------------------------------------------------- #
# 6. Criterion-review failure not scoring zero
# --------------------------------------------------------------------------- #

def test_criterion_review_failure_never_flags_review(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    def failing(call):
        raise JevUnavailableError("down")

    service, _ = make_service(database, failing, modes={"assessment.criterion_review.v1": "on"})
    assessment = AssessmentService(database, jev=service)
    workspace = {"owner_user_id": "user-a", "course_id": "c", "id": "ws"}
    criterion = {"node_id": "n", "spec_version": 1}
    question = {
        "prompt_text": "q", "question_type": "SHORT_TEXT",
        "answer_key": {}, "student_answer": "x",
    }
    # The backend owns fraction; a Jev failure can only leave needs_review unchanged.
    assert assessment._apply_jev_criterion_review(  # noqa: SLF001
        workspace, question, criterion, 0.8, False
    ) is False
    assert assessment._apply_jev_criterion_review(  # noqa: SLF001
        workspace, question, criterion, 0.0, False
    ) is False


def test_review_criterion_fallback_is_not_a_jev_signal(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    def failing(call):
        raise JevUnavailableError("down")

    service, _ = make_service(database, failing, modes={"assessment.criterion_review.v1": "on"})
    result = callsites.review_criterion(
        service,
        frozen_question={"prompt": "q"},
        criterion={"criterion_id": "c1"},
        reference_solution="ref",
        student_answer="ans",
        deterministic_verification="",
        candidate_answer_spans=["ans"],
        scope=scope_for(service, authorization="assessment"),
    )
    assert result.used_jev is False
    assert result.value == "NEEDS_REVIEW"  # fallback value, never a Jev signal


# --------------------------------------------------------------------------- #
# 7. Layered template classification returns OTHER on insufficient evidence
# --------------------------------------------------------------------------- #

_TEMPLATES = [
    TemplateOption(id="01", label="商务资讯系统", level="graduate"),
    TemplateOption(id="02", label="计算机科学", level="graduate"),
    TemplateOption(id="11", label="计算机科学与技术", level="undergraduate"),
    TemplateOption(id="12", label="智能制造", level="undergraduate"),
]


def test_template_match_service_none_returns_other() -> None:
    assert callsites.match_template(None, _TEMPLATES, state={}, scope=None) == "OTHER"


def test_template_match_shadow_returns_other(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    def responder(call):
        # In shadow mode the suggestion is recorded but never used, so the
        # business value must stay the deterministic OTHER.
        return JevResult(answers={"template.match.v1": JevAnswer(choice="02")})

    service, _ = make_service(database, responder, modes={"template.match.v1": "shadow"})
    result = callsites.match_template(
        service, _TEMPLATES, state={"course_title": "CS", "curriculum_samples": []},
        scope=scope_for(service, authorization="template"),
    )
    assert result == "OTHER"  # shadow: deterministic OTHER


def test_template_match_on_selects_valid_template(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    def responder(call):
        choice = "graduate" if call.state.get("stage") == "degree" else "02"
        return JevResult(answers={"template.match.v1": JevAnswer(choice=choice)})

    service, _ = make_service(database, responder, modes={"template.match.v1": "on"})
    result = callsites.match_template(
        service, _TEMPLATES, state={"course_title": "CS", "curriculum_samples": []},
        scope=scope_for(service, authorization="template"),
    )
    assert result == "02"  # degree=graduate -> template 02 within graduate


# --------------------------------------------------------------------------- #
# 8. Oversized input falls back rather than half-sending
# --------------------------------------------------------------------------- #

def test_oversized_input_falls_back_without_half_sending(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    def responder(call):
        return JevResult(answers={"corpus.quality.v1": JevAnswer(score="3")})

    service, transport = make_service(database, responder, modes={"corpus.quality.v1": "on"})
    result = service.corpus_quality(
        document_fragment="x" * 20_000,
        source_metadata={},
        parse_flags=[],
        caller_role="corpus",
        cache_scope=scope_for(service, authorization="corpus"),
    )
    assert result.used_jev is False
    assert result.path == "fallback:input_too_long"
    assert result.value == 1  # retain original; mark limitations
    assert transport.calls == []  # never half-sent


def test_input_budget_provenance_recorded(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    def responder(call):
        return JevResult(answers={"retrieval.support.v1": JevAnswer(score="3")})

    service, _ = make_service(database, responder, modes={"retrieval.support.v1": "on"})
    result = service.retrieval_support(
        _fused("c", exact=False, score=0.5),
        query="q",
        caller_role="retrieval",
        cache_scope=scope_for(service),
    )
    summary = service.summary()
    assert result.input_hash in summary["budgets"]
    prov = summary["budgets"][result.input_hash]
    assert prov["definition_key"] == "retrieval.support.v1"
    assert prov["candidate_count"] == 5  # Score has 5 ordered levels
    assert prov["input_token_estimate"] > 0
    assert "definition_version" in prov


# --------------------------------------------------------------------------- #
# 9. No state writes across a full wired flow
# --------------------------------------------------------------------------- #

def test_full_wired_flow_writes_no_learning_grade_or_coverage(tmp_path) -> None:
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

    def responder(call):
        key = next(iter(call.questions))
        if key == "retrieval.support.v1":
            return JevResult(answers={key: JevAnswer(score="4")})
        if key == "corpus.quality.v1":
            return JevResult(answers={key: JevAnswer(score="2")})
        if key == "source.supports_claim.v1":
            return JevResult(answers={key: JevAnswer(noul=0.9)})
        if key == "context.keep_segment.v1":
            return JevResult(answers={key: JevAnswer(noul=0.5)})
        # Choice definitions: return the first authorized candidate id.
        choice = next(iter(call.questions[key].criteria or {}), None)
        return JevResult(answers={key: JevAnswer(choice=choice)})

    modes = {definition: "on" for definition in CATALOG.definitions}
    service, _ = make_service(database, responder, modes=modes)
    scope = scope_for(service)

    # Exercise a representative flow across families.
    callsites.rerank_retrieval(
        service, [_fused("a", exact=False, score=0.5)], query="q", scope=scope
    )
    callsites.coverage_item_support(
        service, [{"item_id": "a"}], content="x", spec_version=1,
        scope=scope_for(service, authorization="coverage"),
    )
    callsites.review_criterion(
        service, frozen_question={}, criterion={"criterion_id": "c1"},
        reference_solution="r", student_answer="s", deterministic_verification="",
        candidate_answer_spans=["s"],
        scope=scope_for(service, authorization="assessment"),
    )
    callsites.route_next_action(
        service, message="那这个呢", fixed_anchor={}, current_mode="teach",
        active_assessment=None, scope=scope_for(service, authorization="intent"),
    )
    callsites.select_pedagogy_method(
        service, learner_request="x", known_prior_evidence=[], topic="t",
        template_profile={}, current_step="s",
        scope=scope_for(service, authorization="pedagogy"),
    )
    callsites.match_template(
        service, _TEMPLATES, state={"course_title": "CS"},
        scope=scope_for(service, authorization="template"),
    )
    callsites.select_exercise_prototype(
        service, node="n", eligible_prototypes=["p1"], recent_exposures=[],
        learning_evidence=[], scope=scope_for(service, authorization="exercise"),
    )
    callsites.select_prerequisite(
        service, current_node="n", error="e", allowed_predecessor_nodes=["p1"],
        scope=scope_for(service, authorization="prerequisite"),
    )
    callsites.assess_corpus_quality(
        service, document_fragment="frag", source_metadata={}, parse_flags=[],
        scope=scope_for(service, authorization="corpus"),
    )
    callsites.citation_support(
        service, claim="c", source_span="s", source_version="v", task_scope="t",
        scope=scope_for(service, authorization="citation"),
    )
    callsites.select_citation_span(
        service, claim="c", candidate_spans=["s1"],
        scope=scope_for(service, authorization="citation"),
    )
    callsites.keep_history_segment(
        service, segment="seg", current_task="q", fixed_anchor={}, remaining_scope="s",
        scope=scope_for(service, authorization="context"),
    )

    with database.connect() as connection:
        journey_status = connection.execute(
            "SELECT status FROM learning_journeys WHERE id='j1'"
        ).fetchone()[0]
        grade = connection.execute(
            "SELECT raw_score FROM assessment_sessions WHERE id='s1'"
        ).fetchone()[0]
        coverage = connection.execute(
            "SELECT COUNT(*) FROM learning_coverage"
        ).fetchone()[0]
        receipts = connection.execute(
            "SELECT COUNT(*) FROM jev_decision_receipts"
        ).fetchone()[0]
    assert journey_status == "LEARNING"
    assert grade == 78.0
    assert coverage == 1
    assert receipts >= 1  # the only write was to the Jev receipt ledger


# --------------------------------------------------------------------------- #
# 10. End-to-end wired flow: retrieval + citation annotation in the adapter
# --------------------------------------------------------------------------- #

class _Hit:
    def __init__(self, prefix: str, index: int) -> None:
        self.chunk_id = f"{prefix}-chunk-{index}"
        self.document_id = f"{prefix}-doc-{index}"
        self.filename = f"{prefix}-{index}.md"
        self.locator_type = "page"
        self.locator_value = str(index)
        self.section = "s"
        self.content = f"{prefix} unique evidence {index}"


class _StubRetriever:
    def retrieve(self, *, course_id, query, top_k, access):
        prefix = "official" if access.scope == "official" else "private"
        return [_Hit(prefix, i) for i in range(1, top_k + 1)]

    def retrieve_structured(self, *, course_id, reference, top_k, access=None):
        return []


def _fused(prefix: str, *, exact: bool, score: float, scopes=("official",)) -> FusedHit:
    """Build a real :class:`FusedHit` with the id nested in ``hit.chunk_id``."""
    return FusedHit(
        hit=_Hit(prefix, 1),
        score=score,
        scopes=scopes,
        ranks={scopes[0]: 1},
        exact=exact,
    )


def test_retrieve_wiring_annotates_citation_support(tmp_path) -> None:
    from app.config import Settings
    from app.ui_extension.domain import V3DomainAdapter

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
        key = next(iter(call.questions))
        if key == "retrieval.support.v1":
            return JevResult(answers={key: JevAnswer(score="3")})
        if key == "source.select_span.v1":
            return JevResult(answers={key: JevAnswer(choice="S1")})
        if key == "source.supports_claim.v1":
            return JevResult(answers={key: JevAnswer(noul=0.9)})
        return JevResult(answers={key: JevAnswer(noul=0.5)})

    service, _ = make_service(
        database,
        responder,
        modes={
            "retrieval.support.v1": "on",
            "source.select_span.v1": "on",
            "source.supports_claim.v1": "on",
        },
    )
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
        retriever=_StubRetriever(),
        jev=service,
    )
    sources = adapter._retrieve("user-a", {"course": "jev-course", "query": "evidence example"})  # noqa: SLF001
    assert sources
    assert all("jev_citation_support" in source for source in sources)
    assert any(source["jev_selected_span"] for source in sources)


# ruff: noqa: S101 (assert in tests is intentional)
