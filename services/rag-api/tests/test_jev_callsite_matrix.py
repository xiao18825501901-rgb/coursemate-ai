"""Pin the call-site matrix to the code it describes.

``JEV_CALLSITE_MATRIX.md`` is a deliverable in its own right: one row per
definition saying where it is really called from, what state it reads, what it
changes and what happens when Jev is absent. Nothing connected that file to the
code, so a newly registered definition could have no row, a row could name a
definition that no longer exists, or the matrix's headline claims — the count,
the catalog version, and "all `shadow`" — could go stale with every test still
green. These tests read the delivered file and fail on each of those.

They deliberately do not check the prose of each row: a human writes that, and a
regex would only pretend to verify it.
"""

from __future__ import annotations

import pathlib
import re

from app.jev.catalog import load_catalog
from app.jev.gateway import FakeTransport, JevGateway
from app.jev.models import JevResult

MATRIX_PATH = pathlib.Path(__file__).resolve().parents[3] / "JEV_CALLSITE_MATRIX.md"

# The twelve case definitions. Order is deliberately NOT asserted: the matrix
# numbers its rows by pipeline position (retrieval first, intent fifth), which is
# a legitimate authoring choice and not something the task constrains.
CORE_CALLSITE_IDS = frozenset({
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
})

DEFINITION_ID = re.compile(r"`([a-z][a-z_]*\.[a-z_]+\.v1)`")
TABLE_ONE_ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*`([^`]+)`\s*\|")


def matrix_text() -> str:
    assert MATRIX_PATH.is_file(), f"the delivered matrix is missing: {MATRIX_PATH}"
    return MATRIX_PATH.read_text(encoding="utf-8")


def catalog_keys() -> tuple[str, ...]:
    return load_catalog().keys()


def test_every_registered_definition_appears_in_the_matrix() -> None:
    """A definition with no row is a capability the deliverable does not describe."""
    text = matrix_text()

    missing = [key for key in catalog_keys() if key not in text]

    assert missing == [], (
        "these registered definitions have no row in JEV_CALLSITE_MATRIX.md: "
        + ", ".join(missing)
    )


def test_the_matrix_names_no_definition_outside_the_catalog() -> None:
    """A row for a definition that no longer exists is a claim about nothing."""
    known = set(catalog_keys())

    mentioned = set(DEFINITION_ID.findall(matrix_text()))
    phantom = sorted(mentioned - known)

    assert phantom == [], (
        "JEV_CALLSITE_MATRIX.md names definitions that are not in the catalog: "
        + ", ".join(phantom)
    )


def test_table_one_lists_exactly_the_twelve_core_call_sites() -> None:
    """Table 1 is the twelve case definitions, numbered 1..12, with no extras."""
    numbered = [
        (int(match.group(1)), match.group(2))
        for match in (TABLE_ONE_ROW.match(line) for line in matrix_text().splitlines())
        if match is not None
    ]

    assert [index for index, _ in numbered] == list(range(1, 13))
    assert {key for _, key in numbered} == CORE_CALLSITE_IDS


def test_the_matrix_states_the_version_and_count_the_catalog_actually_has() -> None:
    """The two numbers a reader takes on trust are checked against the catalog."""
    catalog = load_catalog()
    text = matrix_text()

    assert catalog.version in text, (
        f"the matrix does not state the catalog version {catalog.version}"
    )
    assert f"All {len(catalog.keys())} definitions are `shadow`" in text, (
        "the matrix no longer states the definition count it is describing"
    )


def test_every_definition_defaults_to_shadow_as_the_matrix_claims() -> None:
    """The matrix's headline mode claim follows from code, not from the prose."""
    catalog = load_catalog()
    gateway = JevGateway(
        transport=FakeTransport(lambda call: JevResult(answers={})),
        catalog=catalog,
    )

    assert catalog.default_runtime_mode == "shadow"
    # ``Catalog`` exposes ``keys()`` without being iterable, so this stays a call
    # on a bound local rather than the dict-comprehension form SIM118 prefers.
    registered = catalog.keys()
    modes = {key: gateway.mode_for(key) for key in registered}

    assert set(modes.values()) == {"shadow"}, modes
    assert len(modes) == len(registered)
