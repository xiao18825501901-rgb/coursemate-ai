"""Catalog integrity: 12 definitions, primitive split, thresholds unset."""

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
    "template.match.v1",
    "exercise.prototype.v1",
    "graph.prerequisite.v1",
    "corpus.quality.v1",
)


def test_catalog_has_exactly_twelve_definitions() -> None:
    catalog = load_catalog()
    assert catalog.keys() == EXPECTED_KEYS
    assert len(catalog.definitions) == 12


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
        "template.match.v1",
        "exercise.prototype.v1",
        "graph.prerequisite.v1",
    }
    assert nouls == {"source.supports_claim.v1", "context.keep_segment.v1"}
    assert scores == {"retrieval.support.v1", "corpus.quality.v1"}


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
