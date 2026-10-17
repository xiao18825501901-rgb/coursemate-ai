"""Trusted grading predicates for the bounded graph-degree assessment family."""

import re
import unicodedata
from typing import Any, Final

METHOD: Final = "finite-loop-free-graph-degree-assessment.v1"
_DEGREE_DEFINITION_ITEM: Final = "vd_degree_definition_required"
_HANDSHAKE_IDENTITY_ITEM: Final = "vd_handshake_identity_required"


def _normalized_claim_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _degree_claims(value: str) -> tuple[dict[str, int], bool]:
    """Extract explicit vertex-degree equations and report contradictions."""

    text = _normalized_claim_text(value)
    patterns = (
        r"deg\s*\(\s*([a-d])\s*\)\s*(?:=|is|equals?|为|是|等于)\s*(-?\d+)",
        r"(?:degree|度数?|顶点度)\s*(?:of\s+(?:vertex\s+)?)?([a-d])"
        r"\s*(?:=|is|equals?|为|是|等于)\s*(-?\d+)",
        r"(?:vertex\s+)?([a-d])(?:点|顶点)?(?:的)?\s*(?:degree|度数?)"
        r"\s*(?:=|is|equals?|为|是|等于)\s*(-?\d+)",
    )
    claims: dict[str, int] = {}
    contradictory = False
    for pattern in patterns:
        for vertex, raw_value in re.findall(pattern, text, flags=re.IGNORECASE):
            key = vertex.upper()
            number = int(raw_value)
            if key in claims and claims[key] != number:
                contradictory = True
            claims[key] = number
    return claims, contradictory


def _states_degree_definition(value: str) -> bool:
    sentences = re.split(r"[。.!?！？;；\n]+", _normalized_claim_text(value))
    for sentence in sentences:
        english = re.search(
            r"degree\s+of\s+(?:a\s+)?vertex\s+(?:is|equals?|means?)\s+"
            r"(?:the\s+)?(?:number|count)\s+of\s+(?:its\s+)?incident\s+edges",
            sentence,
        )
        chinese = (
            "度" in sentence
            and any(relation in sentence for relation in ("是", "为", "等于", "指"))
            and any(
                connection in sentence
                for connection in ("关联", "相连", "连接", "相接", "端点")
            )
            and any(
                quantity in sentence
                for quantity in ("边数", "边的数量", "边的个数", "边的条数")
            )
        )
        if english or chinese:
            return True
    return False


def _states_handshake_identity(value: str) -> bool:
    text = _normalized_claim_text(value)
    compact = re.sub(r"\s+", "", text).replace("∑", "sum").replace("σ", "sum")
    symbolic = bool(
        re.search(
            r"sum[_a-z∈]*deg\(v\)=2(?:\*)?\|?e\|?",
            compact,
        )
    )
    chinese = bool(
        re.search(
            r"(?:所有)?顶点(?:的)?度数?之和(?:为|是|等于)"
            r"(?:边数|边的数量|边的条数)(?:的)?(?:两倍|2倍)",
            compact,
        )
    )
    english = bool(
        re.search(
            r"sumof(?:all)?(?:vertex)?degrees?(?:is|equals?)"
            r"(?:twice|2times)(?:the)?(?:numberof)?edges?",
            compact,
        )
    )
    return symbolic or chinese or english


def _claimed_numbers(value: str, patterns: tuple[str, ...]) -> set[int]:
    text = _normalized_claim_text(value)
    values: set[int] = set()
    for pattern in patterns:
        values.update(int(match) for match in re.findall(pattern, text, flags=re.IGNORECASE))
    return values


def _degree_sum_equation(value: str) -> tuple[list[int], int] | None:
    text = _normalized_claim_text(value)
    match = re.search(
        r"(?:degree\s*sum|sum\s*of\s*(?:all\s*)?(?:vertex\s*)?degrees?|度数?之?和)"
        r"\s*(?:=|is|equals?|为|是|等于)\s*"
        r"((?:\d+\s*\+\s*)+\d+)\s*=\s*(\d+)",
        text,
    )
    if match is None:
        return None
    return [int(value) for value in re.findall(r"\d+", match.group(1))], int(match.group(2))


def verify_graph_point_short_text(
    item_id: str,
    submitted: str,
    proof: Any,
) -> bool | None:
    """Verify two graph SHORT_TEXT targets from host-owned mathematical facts.

    ``None`` preserves the caller's existing behavior for every other method or
    target. A boolean is a complete verdict for this bounded method.
    """

    if not isinstance(proof, dict):
        return None
    if proof.get("method") != METHOD or item_id not in {
        _DEGREE_DEFINITION_ITEM,
        _HANDSHAKE_IDENTITY_ITEM,
    }:
        return None
    expected_degrees = proof.get("degrees")
    if not isinstance(expected_degrees, dict):
        return False
    expected = {
        str(vertex).upper(): value
        for vertex, value in expected_degrees.items()
        if isinstance(value, int) and not isinstance(value, bool)
    }
    vertices = proof.get("vertices")
    if not isinstance(vertices, list) or set(expected) != {
        str(vertex).upper() for vertex in vertices
    }:
        return False
    claims, contradictory = _degree_claims(submitted)
    if contradictory:
        return False
    if item_id == _DEGREE_DEFINITION_ITEM:
        return claims == expected and _states_degree_definition(submitted)

    degree_sum = proof.get("degree_sum")
    edge_count = proof.get("edge_count")
    twice_edge_count = proof.get("twice_edge_count")
    if not all(
        isinstance(value, int) and not isinstance(value, bool)
        for value in (degree_sum, edge_count, twice_edge_count)
    ):
        return False
    degree_equation = _degree_sum_equation(submitted)
    expected_addends = [expected[str(vertex).upper()] for vertex in vertices]
    counted_degrees = claims == expected or (
        degree_equation is not None
        and degree_equation[0] == expected_addends
        and degree_equation[1] == degree_sum
    )
    stated_degree_sums = _claimed_numbers(
        submitted,
        (
            r"(?:degree\s*sum|sum\s*of\s*(?:all\s*)?(?:vertex\s*)?degrees?|度数?之?和)"
            r"\s*(?:=|is|equals?|为|是|等于)\s*(\d+)",
        ),
    )
    if degree_equation is not None:
        # The direct scalar pattern sees the first addend in ``2+2+3+1=8``;
        # the structured equation parser owns this rendering instead.
        stated_degree_sums = {degree_equation[1]}
    stated_edge_counts = _claimed_numbers(
        submitted,
        (
            r"(?<!2)\|\s*e\s*\|\s*(?:=|is|equals?|为|是|等于)\s*(\d+)",
            r"(?:共有|一共|总共)\s*(\d+)\s*条?边",
            r"(?:there\s+are|has)\s*(\d+)\s*edges?",
        ),
    )
    stated_twice_counts = _claimed_numbers(
        submitted,
        (
            r"2\s*(?:\*)?\s*\|\s*e\s*\|\s*(?:=|is|equals?|为|是|等于)\s*(\d+)",
        ),
    )
    return (
        _states_handshake_identity(submitted)
        and counted_degrees
        and stated_degree_sums == {degree_sum}
        and stated_edge_counts == {edge_count}
        and stated_twice_counts == {twice_edge_count}
    )
