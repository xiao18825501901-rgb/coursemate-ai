"""The E2E fixture must actually be *shaped* for the journeys that assert on it.

`scripts/seed_structured_fixture.py` builds the content four browser journeys act
on. A fixture that quietly loses the property a journey depends on would turn that
journey into a test of nothing — it would still pass, because the assertion would
find whatever the fixture happens to contain. These are the properties, checked in
process and without a browser:

* the alias page is reachable **only** through the accepted English alias: it never
  contains the Chinese term the journey asks with;
* the two "kernel" pages really do use the word in two unrelated senses;
* the percentages the citation journeys assert on are exactly the ones the pages
  state, and the figure the unsupported-citation journey asks about is in none of
  them — checked through the very function that decides it
  (`app.jev.citation_audit.missing_claim_numbers`), so the journey's expected
  verdict follows from the fixture rather than from a hope about the model.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

from app.jev.citation_audit import missing_claim_numbers

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SEEDER = REPOSITORY_ROOT / "scripts" / "seed_structured_fixture.py"


def _seeder():
    """Import the seeder as a module without running its CLI."""
    if "seed_structured_fixture_under_test" in sys.modules:
        return sys.modules["seed_structured_fixture_under_test"]
    spec = importlib.util.spec_from_file_location("seed_structured_fixture_under_test", SEEDER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_structured_fixture_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def fixture() -> dict[str, str]:
    return dict(_seeder().DOCUMENTS)


def test_the_alias_page_is_reachable_only_through_the_accepted_alias(
    fixture: dict[str, str],
) -> None:
    seeder = _seeder()
    page = fixture[seeder.ALIAS_PAGE]
    assert "DBSCAN" in page
    # The journey asks in Chinese; the page must not contain the Chinese term, or a
    # lexical hit would prove nothing about the alias.
    assert seeder.NODES[0][1] not in page  # the canonical title, e.g. 密度聚类
    assert seeder.NODES[0][1].casefold() not in page.casefold()
    # And the alias the registry carries is the English form the page uses.
    assert any(alias == "DBSCAN" for alias in seeder.NODES[0][4])


def test_the_two_kernel_pages_use_the_word_in_unrelated_senses(
    fixture: dict[str, str],
) -> None:
    seeder = _seeder()
    svm = fixture[seeder.KERNEL_SVM_PAGE].casefold()
    operating_system = fixture[seeder.KERNEL_OS_PAGE].casefold()
    assert "kernel" in svm and "kernel" in operating_system
    assert "support vector machine" in svm
    assert "operating system kernel" in operating_system
    # Neither page may mention the other's field, or "not merged" would be trivial.
    assert "operating system" not in svm
    assert "support vector" not in operating_system


def test_the_alpha_pages_carry_the_figures_the_citation_journeys_assert_on(
    fixture: dict[str, str],
) -> None:
    seeder = _seeder()
    two_sided_a = fixture[seeder.ALPHA_TWO_SIDED_A_PAGE]
    two_sided_b = fixture[seeder.ALPHA_TWO_SIDED_B_PAGE]
    one_sided = fixture[seeder.ALPHA_ONE_SIDED_PAGE]
    assert "5%" in two_sided_a
    assert "20%" in two_sided_b
    assert "10%" in one_sided
    # The contradiction pair shares its assumption; the third page differs in it.
    assert "two-sided" in two_sided_a and "two-sided" in two_sided_b
    assert "one-sided" in one_sided


def test_the_threshold_page_has_two_sections_so_the_two_fragments_are_distinct_parts(
    fixture: dict[str, str],
) -> None:
    """Module C's deterministic narrowing pairs chunks of one document only when
    their locators differ. A markdown page with two headings is what produces that
    through the product's own loader (`app/rag/loaders.py::_load_markdown` gives each
    heading its own section/locator), so the two figures land in different chunks of
    the same document instead of in one chunk."""
    seeder = _seeder()
    page = fixture[seeder.THRESHOLD_SECTIONS_PAGE]
    headings = [
        line.lstrip("# ").strip()
        for line in page.splitlines()
        if line.startswith("# ")
    ]
    assert len(headings) >= 2, page
    assert len(set(headings)) == len(headings)
    assert "3.5%" in page and "8.2%" in page
    # Both fragments answer the same *question* ("decision threshold") under
    # different tasks, which is what makes the pair comparable at all.
    assert page.count("decision threshold") >= 2


def test_the_locator_page_exposes_the_question_number_the_journey_names(
    fixture: dict[str, str],
) -> None:
    """An exact-locator journey needs a locator that resolves, not a plausible one.

    `app/rag/structure.py` reads an explicit `Question N` line and a following `(b)`
    line, and `parse_query_reference` turns the same wording in the learner's message
    into a filter on chunk metadata. The journey asks for `Question 3(b)`, so the page
    must state exactly that — a page whose numbering drifted would leave the journey
    asserting on a fallback hybrid ranking that happens to contain the file.
    """
    seeder = _seeder()
    page = fixture[seeder.LOCATOR_PAGE]
    assert re.search(r"(?im)^\s*question\s+3\s*$", page), page
    assert re.search(r"(?im)^\s*\(b\)\s+\S", page), page
    assert re.search(r"(?im)^\s*question\s+4\s*$", page), page

    from app.tutor.references import parse_query_reference

    reference = parse_query_reference(f"{seeder.LOCATOR_PAGE} Question 3(b) 说明了什么")
    assert reference.document == seeder.LOCATOR_PAGE
    assert reference.question_number == "3"
    assert reference.question_part == "b"


def test_a_figure_no_page_states_is_decided_in_code_and_one_that_a_page_states_is_not(
    fixture: dict[str, str],
) -> None:
    """The journey's two verdicts, decided by the real layer-2 function."""
    seeder = _seeder()
    absent = "针对「材料里说默认显著性水平是 42% 吗」，课程材料中的相关依据见 [S1]。"
    present = "针对「材料里说默认显著性水平是 5% 吗」，课程材料中的相关依据见 [S1]。"
    for text in fixture.values():
        assert missing_claim_numbers(absent, text) == ("42%",), text
    assert missing_claim_numbers(present, fixture[seeder.ALPHA_TWO_SIDED_A_PAGE]) == ()
    assert missing_claim_numbers(present, fixture[seeder.ALPHA_TWO_SIDED_B_PAGE]) == ("5%",)
