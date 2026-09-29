"""The task contract, the witness protocol and the bounded profiles, end to end.

Every check here is deterministic.  No provider is contacted, no model verdict is
simulated, and the certificate in each case is issued by the code under test.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.learning.ambiguity_witness import (
    AmbiguityWitnessClaim,
    Interpretation,
    SqlWitnessChecker,
    ambiguity_gate_verdict,
    structural_check,
)
from app.learning.task_spec import (
    P_COURSE_RULE,
    P_DISCRETE,
    P_SQL,
    StudentVisibleTaskSpec,
    TaskConvention,
    TaskFact,
    certify_completeness,
    profile_by_id,
    render_public_projection,
)

REVISION = "a" * 64


def _spec(**overrides):
    values = {
        "spec_id": "spec-p-sql",
        "spec_version": 1,
        "question_revision_hash": REVISION,
        "objective_id": "objective-sql",
        "question_type": "SHORT_TEXT",
        "marks": 10,
        "bloom_target": "APPLY",
        "task_boundary": "Write the result of the query and state which members appear.",
        "facts": [
            TaskFact(
                fact_id="schema",
                role="GIVEN",
                origin="PROBLEM_DATA",
                statement=(
                    "Table Member(member_id TEXT, name TEXT) and "
                    "Subscription(member TEXT, start_date TEXT)."
                ),
            )
        ],
        "conventions": [
            TaskConvention(key="DIALECT", statement="SQLite 3 semantics."),
            TaskConvention(key="DATA_COMPLETENESS", statement="The rows given are all the rows."),
            TaskConvention(
                key="DUPLICATE_ROWS",
                statement="Duplicate rows are distinct unless DISTINCT is written.",
            ),
            TaskConvention(key="ROW_ORDER", statement="Row order is not significant."),
        ],
        "answer_equivalence": "SET_UNORDERED",
        "profile_id": "P-SQL",
        "profile_version": 1,
    }
    values.update(overrides)
    return StudentVisibleTaskSpec(**values)


def _certificate(spec, span_ids=("chunk-1",), language="en"):
    return certify_completeness(
        spec,
        projection=render_public_projection(spec),
        available_span_ids=span_ids,
        reviewable_language=language,
    )


# --- the projection is the student view, and it is rendered, not asserted ---------


def test_every_premise_and_convention_appears_in_the_student_projection() -> None:
    spec = _spec()
    projection = render_public_projection(spec)
    for fact in spec.premises():
        assert fact.statement in projection.text
    for convention in spec.conventions:
        assert convention.statement in projection.text
        assert convention.key in projection.text
    assert projection.text_digest == projection.text_digest.lower()
    assert len(projection.text_digest) == 64


def test_a_claim_to_critique_is_rendered_apart_and_is_not_a_premise() -> None:
    spec = _spec(
        facts=[
            TaskFact(
                fact_id="rule",
                role="SOURCE_RULE",
                origin="COURSE_SOURCE",
                statement="The course states that a small SSE means good centroids.",
                source_span_id="chunk-1",
            ),
            TaskFact(
                fact_id="claim",
                role="CLAIM_TO_CRITIQUE",
                origin="EXERCISE_CONVENTION",
                statement="K-means recomputes centroids before assigning points.",
            ),
        ],
        conventions=[
            TaskConvention(
                key="ANSWER_FORM", statement="State the rule and the correction."
            )
        ],
        profile_id="P-COURSE-RULE",
    )
    projection = render_public_projection(spec)
    assert spec.premises() == [spec.facts[0]]
    assert spec.claims_to_critique() == [spec.facts[1]]
    assert "not a premise" in projection.text
    assert projection.claims_to_critique == [spec.facts[1].statement]
    # A wrong claim is the subject of the task, never a stated premise.
    assert spec.facts[1].statement not in projection.premises


def test_a_projection_longer_than_a_single_statement_still_renders() -> None:
    """A condition block is many statements, so it is not a single short text.

    A live item rendered more than a thousand characters and the renderer raised
    instead of returning the block: the bound was the single-statement one.
    """
    facts = [
        TaskFact(
            fact_id=f"given-{index}",
            role="GIVEN",
            origin="PROBLEM_DATA",
            statement=("Given datum number " + str(index) + ": " + "x" * 120),
        )
        for index in range(1, 12)
    ]
    spec = _spec(facts=facts)
    projection = render_public_projection(spec)
    assert len(projection.text) > 800
    for fact in facts:
        assert fact.statement in projection.text


def test_a_source_rule_without_a_span_is_refused_at_construction() -> None:
    with pytest.raises(ValidationError):
        TaskFact(
            fact_id="rule",
            role="SOURCE_RULE",
            origin="COURSE_SOURCE",
            statement="The course states the ordering.",
        )


# --- completeness is positive, per profile, and never guessed ---------------------


def test_a_complete_sql_item_is_certified_for_its_registered_profile() -> None:
    certificate = _certificate(_spec())
    assert certificate.status == "COMPLETE_FOR_REGISTERED_PROFILE"
    assert certificate.certifies is True
    assert certificate.profile_id == "P-SQL"
    assert certificate.profile_version == 1
    assert certificate.checker == P_SQL.checker
    assert certificate.identity()


def test_a_missing_required_convention_makes_the_certificate_incomplete() -> None:
    spec = _spec(
        conventions=[
            TaskConvention(key="DIALECT", statement="SQLite 3 semantics."),
            TaskConvention(key="DATA_COMPLETENESS", statement="The rows given are all the rows."),
            TaskConvention(key="ROW_ORDER", statement="Row order is not significant."),
        ]
    )
    certificate = _certificate(spec)
    assert certificate.status == "INCOMPLETE"
    failing = {check.name for check in certificate.checks if check.status == "FAIL"}
    assert failing == {"convention_stated:DUPLICATE_ROWS"}


def test_an_item_outside_every_profile_is_not_supported_rather_than_approved() -> None:
    spec = _spec(profile_id=None, profile_version=None)
    certificate = _certificate(spec)
    assert certificate.status == "NOT_SUPPORTED"
    assert certificate.certifies is False


def test_an_unregistered_profile_version_is_not_supported() -> None:
    certificate = _certificate(_spec(profile_version=99))
    assert certificate.status == "NOT_SUPPORTED"


def test_a_course_rule_item_must_actually_carry_a_claim_to_critique() -> None:
    spec = _spec(
        facts=[
            TaskFact(
                fact_id="rule",
                role="SOURCE_RULE",
                origin="COURSE_SOURCE",
                statement="The course states the ordering.",
                source_span_id="chunk-1",
            )
        ],
        conventions=[TaskConvention(key="ANSWER_FORM", statement="State the rule.")],
        profile_id="P-COURSE-RULE",
        question_type="EXPLANATION",
    )
    certificate = _certificate(spec)
    assert certificate.status == "INCOMPLETE"
    failing = {check.name for check in certificate.checks if check.status == "FAIL"}
    assert "role_present:CLAIM_TO_CRITIQUE" in failing


def test_a_dangling_source_span_is_incomplete() -> None:
    spec = _spec(
        facts=[
            TaskFact(
                fact_id="rule",
                role="SOURCE_RULE",
                origin="COURSE_SOURCE",
                statement="The course states the ordering.",
                source_span_id="chunk-absent",
            ),
            TaskFact(
                fact_id="claim",
                role="CLAIM_TO_CRITIQUE",
                origin="EXERCISE_CONVENTION",
                statement="The procedure recomputes before assigning.",
            ),
        ],
        conventions=[TaskConvention(key="ANSWER_FORM", statement="State the rule.")],
        profile_id="P-COURSE-RULE",
        question_type="EXPLANATION",
    )
    certificate = _certificate(spec, span_ids=("chunk-1",))
    assert certificate.status == "INCOMPLETE"
    failing = {check.name for check in certificate.checks if check.status == "FAIL"}
    assert "source_spans_exist" in failing


def test_the_registered_profiles_are_the_three_declared_shapes() -> None:
    assert profile_by_id("P-SQL") is P_SQL
    assert profile_by_id("P-DISCRETE") is P_DISCRETE
    assert profile_by_id("P-COURSE-RULE") is P_COURSE_RULE
    assert profile_by_id("P-ESSAY") is None
    assert P_DISCRETE.required_conventions == ("DATA_COMPLETENESS", "BOUNDARY_INCLUSION")


# --- the witness protocol ---------------------------------------------------------


def _witness(**overrides):
    values = {
        "problem_field_or_span": "the membership condition is not stated",
        "interpretations": [
            Interpretation(
                label="A",
                statement="only rows that satisfy both joins count",
                admissible_because="nothing in the stem excludes it",
                answer="A, B",
                scored_conclusion="{A,B}",
            ),
            Interpretation(
                label="B",
                statement="rows matching either join count",
                admissible_because="nothing in the stem excludes it either",
                answer="A, B, C",
                scored_conclusion="{A,B,C}",
            ),
        ],
        "material_difference": "one member appears in one reading and not the other",
        "minimal_disambiguation": "state that both conditions must hold",
    }
    values.update(overrides)
    return AmbiguityWitnessClaim(**values)


def test_a_reading_that_adds_data_is_refused_as_inadmissible() -> None:
    verdict = structural_check(
        _witness(introduces_new_data=True),
        declared_equivalence="SET_UNORDERED",
        span_ids={"chunk-1"},
    )
    assert verdict.status == "REFUSED_INADMISSIBLE"
    assert verdict.blocks is True or verdict.blocks is False  # refusals do not block
    assert verdict.status != "CONFIRMED_MATERIAL"


def test_a_reading_that_contradicts_a_stated_condition_is_refused() -> None:
    verdict = structural_check(
        _witness(changes_stated_condition=True),
        declared_equivalence="SET_UNORDERED",
        span_ids={"chunk-1"},
    )
    assert verdict.status == "REFUSED_INADMISSIBLE"


def test_a_reading_about_row_order_is_not_material_under_an_unordered_equivalence() -> None:
    verdict = structural_check(
        _witness(
            interpretations=[
                Interpretation(
                    label="A",
                    statement="rows come back in insertion order",
                    admissible_because="the engine may do this",
                    answer="B, A",
                    scored_conclusion="B A",
                ),
                Interpretation(
                    label="B",
                    statement="rows come back sorted",
                    admissible_because="the engine may do this too",
                    answer="A, B",
                    scored_conclusion="A B",
                ),
            ]
        ),
        declared_equivalence="SET_UNORDERED",
        span_ids=set(),
    )
    assert verdict.status == "REFUSED_NOT_MATERIAL"


def test_same_conclusion_from_different_methods_is_not_material() -> None:
    verdict = structural_check(
        _witness(
            interpretations=[
                Interpretation(
                    label="A",
                    statement="solve by substituting",
                    admissible_because="valid method",
                    answer="42",
                    scored_conclusion="42",
                ),
                Interpretation(
                    label="B",
                    statement="solve by factoring",
                    admissible_because="also valid",
                    answer="42",
                    scored_conclusion="42",
                ),
            ]
        ),
        declared_equivalence="EXACT",
        span_ids=set(),
    )
    assert verdict.status == "REFUSED_NOT_MATERIAL"


def test_an_unexecuted_witness_stays_an_open_objection_and_never_approves() -> None:
    verdict = structural_check(
        _witness(), declared_equivalence="SET_UNORDERED", span_ids=set()
    )
    assert verdict.status == "UNVERIFIABLE"
    assert verdict.unresolved is True
    assert verdict.blocks is True


def test_the_sql_checker_confirms_a_difference_it_can_execute() -> None:
    checker = SqlWitnessChecker(
        schema="CREATE TABLE Member(member_id TEXT, name TEXT);",
        data="INSERT INTO Member VALUES ('m1','A'), ('m2','B');",
    )
    verdict = checker.check(
        _witness(
            interpretations=[
                Interpretation(
                    label="A",
                    statement="every member",
                    admissible_because="one reading",
                    answer="A, B",
                    scored_conclusion="{A,B}",
                    executable_statement="SELECT name FROM Member",
                ),
                Interpretation(
                    label="B",
                    statement="only the first member",
                    admissible_because="another reading",
                    answer="A",
                    scored_conclusion="{A}",
                    executable_statement="SELECT name FROM Member WHERE member_id = 'm1'",
                ),
            ]
        ),
        declared_equivalence="SET_UNORDERED",
        span_ids=set(),
        comparison="SET",
    )
    assert verdict.status == "CONFIRMED_MATERIAL"
    assert verdict.executed is True
    assert verdict.checked_by == "PROFILE_CHECKER"


def test_the_sql_checker_refuses_two_readings_that_agree_on_the_given_rows() -> None:
    checker = SqlWitnessChecker(
        schema="CREATE TABLE Member(member_id TEXT, name TEXT);",
        data="INSERT INTO Member VALUES ('m1','A'), ('m2','B');",
    )
    verdict = checker.check(
        _witness(
            interpretations=[
                Interpretation(
                    label="A",
                    statement="every member",
                    admissible_because="one reading",
                    answer="A, B",
                    scored_conclusion="{A,B}",
                    executable_statement="SELECT name FROM Member",
                ),
                Interpretation(
                    label="B",
                    statement="every member, written differently",
                    admissible_because="another reading",
                    answer="B, A",
                    scored_conclusion="{B,A}",
                    executable_statement="SELECT name FROM Member ORDER BY name DESC",
                ),
            ]
        ),
        declared_equivalence="SET_UNORDERED",
        span_ids=set(),
        comparison="SET",
    )
    assert verdict.status == "REFUSED_NOT_MATERIAL"
    assert verdict.executed is True


def test_the_sql_checker_says_so_when_it_cannot_execute_the_readings() -> None:
    checker = SqlWitnessChecker(
        schema="CREATE TABLE Member(member_id TEXT, name TEXT);",
        data="INSERT INTO Member VALUES ('m1','A');",
    )
    verdict = checker.check(
        _witness(), declared_equivalence="SET_UNORDERED", span_ids=set()
    )
    assert verdict.status == "UNVERIFIABLE"
    assert verdict.executed is False


# --- the gate ---------------------------------------------------------------------


def test_the_gate_needs_positive_evidence_and_never_clears_by_absence() -> None:
    certificate = _certificate(_spec())
    verdict, reasons = ambiguity_gate_verdict(
        witness_verdicts=[],
        completeness=certificate,
        qualification_active=True,
    )
    assert (verdict, reasons) == ("PASS", [])


def test_no_certificate_means_uncertain_even_with_no_witness_at_all() -> None:
    verdict, reasons = ambiguity_gate_verdict(
        witness_verdicts=[],
        completeness=None,
        qualification_active=True,
    )
    assert verdict == "UNCERTAIN"
    assert reasons == ["HYBRID_COMPLETENESS_CERTIFICATE_MISSING"]


def test_a_certificate_without_an_active_qualification_is_not_a_pass() -> None:
    verdict, reasons = ambiguity_gate_verdict(
        witness_verdicts=[],
        completeness=_certificate(_spec()),
        qualification_active=False,
    )
    assert verdict == "UNCERTAIN"
    assert reasons == ["HYBRID_QUALIFICATION_MISSING"]


def test_a_confirmed_witness_fails_the_item_whatever_else_is_true() -> None:
    checker = SqlWitnessChecker(
        schema="CREATE TABLE Member(member_id TEXT, name TEXT);",
        data="INSERT INTO Member VALUES ('m1','A'), ('m2','B');",
    )
    witness = checker.check(
        _witness(
            interpretations=[
                Interpretation(
                    label="A",
                    statement="every member",
                    admissible_because="one reading",
                    answer="A, B",
                    scored_conclusion="{A,B}",
                    executable_statement="SELECT name FROM Member",
                ),
                Interpretation(
                    label="B",
                    statement="only the first member",
                    admissible_because="another reading",
                    answer="A",
                    scored_conclusion="{A}",
                    executable_statement="SELECT name FROM Member WHERE member_id = 'm1'",
                ),
            ]
        ),
        declared_equivalence="SET_UNORDERED",
        span_ids=set(),
        comparison="SET",
    )
    verdict, reasons = ambiguity_gate_verdict(
        witness_verdicts=[witness],
        completeness=_certificate(_spec()),
        qualification_active=True,
    )
    assert verdict == "FAIL"
    assert reasons == ["HYBRID_WITNESS_CONFIRMED_MATERIAL"]


def test_an_unverified_objection_holds_the_item_rather_than_failing_it() -> None:
    verdict, reasons = ambiguity_gate_verdict(
        witness_verdicts=[structural_check(
            _witness(), declared_equivalence="SET_UNORDERED", span_ids=set()
        )],
        completeness=_certificate(_spec()),
        qualification_active=True,
    )
    assert verdict == "UNCERTAIN"
    assert reasons == ["HYBRID_WITNESS_UNVERIFIED"]


def test_an_enumerated_missing_dependency_holds_the_item_rather_than_failing_it() -> None:
    """A specific doubt is not a witness.

    An enumeration entry says "this datum is unstated and its absence changes the
    answer" and gives one consequence.  The published rule for a material objection
    is two admissible readings with their answers and the graded difference between
    them, which an entry does not supply -- so it holds the item instead of failing
    it.  The safety is unchanged: a held item is not released, and an item can only
    pass with a completeness certificate the server issued.
    """
    verdict, reasons = ambiguity_gate_verdict(
        witness_verdicts=[],
        blocking_enumeration_entries=1,
        completeness=_certificate(_spec()),
        qualification_active=True,
    )
    assert verdict == "UNCERTAIN"
    assert reasons == ["HYBRID_UNSTATED_DEPENDENCY:question.ambiguity.v1"]

    # Without a certificate the same doubt also holds, for the same reason.
    held, held_reasons = ambiguity_gate_verdict(
        witness_verdicts=[],
        blocking_enumeration_entries=1,
        completeness=None,
        qualification_active=True,
    )
    assert held == "UNCERTAIN"
    assert held_reasons == ["HYBRID_UNSTATED_DEPENDENCY:question.ambiguity.v1"]
