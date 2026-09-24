"""Catalog integrity: core, structured-enhancement and Question Engine definitions."""

from __future__ import annotations

from app.jev.catalog import Primitive, load_catalog

EXPECTED_KEYS = (
    "intent.next_action.v1",
    "retrieval.support.v1",
    "source.supports_claim.v1",
    "source.select_span.v1",
    "context.keep_segment.v1",
    "pedagogy.next_method.v1",
    "coverage.item_support.v1",
    "assessment.criterion_review.v1",
    "question.ambiguity.v1",
    "question.answer_agreement.v1",
    "template.match.v1",
    "exercise.prototype.v1",
    "graph.prerequisite.v1",
    "corpus.quality.v1",
    # Structured enhancement round: field-level extraction verification (module A) and
    # evidence condition/conflict checking (module C). Both were implemented against
    # module constants first and are now the catalog's own definitions.
    "extraction.field_grounded.v1",
    "evidence.consistency.v1",
    # P1 structured enhancement: course-scope entity relations (module B), teaching
    # capability routing (module E) and side-effecting tool intent checking (module F).
    "entity.relation.v1",
    "teaching.capability.v1",
    "tool.intent.v1",
    # P2: lightweight user-initiated feedback triage (category is a Choice, severity a Score).
    "feedback.category.v1",
    "feedback.severity.v1",
)


def test_catalog_has_exactly_the_expected_definitions() -> None:
    catalog = load_catalog()
    assert catalog.keys() == EXPECTED_KEYS
    assert len(catalog.definitions) == 21


def test_catalog_primitive_split() -> None:
    catalog = load_catalog()
    choices = {k for k, d in catalog.definitions.items() if d.primitive == Primitive.CHOICE}
    nouls = {k for k, d in catalog.definitions.items() if d.primitive == Primitive.NOUL}
    scores = {k for k, d in catalog.definitions.items() if d.primitive == Primitive.SCORE}
    assert choices == {
        "intent.next_action.v1",
        "source.select_span.v1",
        "pedagogy.next_method.v1",
        "coverage.item_support.v1",
        "assessment.criterion_review.v1",
        "question.ambiguity.v1",
        "question.answer_agreement.v1",
        "template.match.v1",
        "exercise.prototype.v1",
        # the two structured-enhancement definitions are both Choice primitives
        "extraction.field_grounded.v1",
        "evidence.consistency.v1",
        # P1 additions: all three are Choice primitives too
        "entity.relation.v1",
        "teaching.capability.v1",
        "tool.intent.v1",
        # P2: feedback category is a Choice (severity is the Score above)
        "feedback.category.v1",
        "graph.prerequisite.v1",
    }
    assert nouls == {"source.supports_claim.v1", "context.keep_segment.v1"}
    # feedback.severity.v1 joined the Score primitives in the feedback round.
    assert scores == {"retrieval.support.v1", "corpus.quality.v1", "feedback.severity.v1"}


def test_catalog_thresholds_unset_and_probability_not_a_grade() -> None:
    catalog = load_catalog()
    assert catalog.probability_is_grade is False
    assert catalog.default_runtime_mode == "shadow"
    assert catalog.thresholds == "UNSET_UNTIL_CALIBRATED_ON_LABELLED_DATA"


def test_score_definitions_expose_ordered_levels() -> None:
    catalog = load_catalog()
    assert catalog.get("retrieval.support.v1").score_levels == ("0", "1", "2", "3", "4")
    assert catalog.get("corpus.quality.v1").score_levels == ("0", "1", "2", "3")


def test_every_definition_declares_cache_scope_and_state() -> None:
    catalog = load_catalog()
    for definition in catalog.definitions.values():
        assert definition.required_state, definition.key
        assert "input_hash" in definition.cache_scope, definition.key
        assert "authorization_scope" in definition.cache_scope, definition.key
