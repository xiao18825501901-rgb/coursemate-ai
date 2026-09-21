"""Unit contracts for the global candidate fusion (no database, no app import).

These pin the ordering rules that the integrated adapter depends on, so the
deterministic retrieval fix cannot silently regress while other areas change:

* ranks are comparable across authorized scopes (append order is not a score),
* the recall cap is per scope, so a wide first scope cannot starve later scopes,
* an explicitly referenced file/page/question keeps its slot,
* text budgeting trims at a boundary rather than by list position.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.learning.retrieval_orchestrator import (
    ScopedCandidates,
    budget_text,
    citation_id,
    exact_targets_from_query,
    fuse_scoped_candidates,
    trace_digest,
)


@dataclass
class Hit:
    chunk_id: str
    document_id: str
    filename: str
    locator_type: str = "page"
    locator_value: str = "1"
    section: str = ""
    content: str = "text"


def _scope(scope: str, count: int) -> ScopedCandidates:
    return ScopedCandidates(
        scope=scope,
        hits=[
            Hit(
                chunk_id=f"{scope}-{index}",
                document_id=f"{scope}-doc-{index}",
                filename=f"{scope}-{index}.md",
                locator_value=str(index),
                content=f"{scope} evidence {index}",
            )
            for index in range(1, count + 1)
        ],
    )


def test_ranks_are_comparable_across_scopes() -> None:
    fused = fuse_scoped_candidates(
        [_scope("official", 2), _scope("mine", 2)], top_k=2
    )
    ids = [entry.chunk_id for entry in fused]
    assert ids == ["official-1", "mine-1"], ids
    assert fused[1].scopes == ("mine",)
    assert fused[1].ranks == {"mine": 1}


def test_wide_first_scope_does_not_starve_later_scopes() -> None:
    # 40 official candidates must not consume the whole candidate budget: the
    # best private candidate still has to compete (this is the exact defect the
    # integrated regression caught).
    fused = fuse_scoped_candidates(
        [_scope("official", 40), _scope("mine", 5)], top_k=3
    )
    ids = [entry.chunk_id for entry in fused]
    assert "mine-1" in ids, ids


def test_scopes_combine_when_the_same_chunk_is_recalled_twice() -> None:
    shared = Hit(chunk_id="shared", document_id="doc", filename="a.md")
    official = ScopedCandidates(scope="official", hits=[shared, *_scope("official", 2).hits])
    mine = ScopedCandidates(scope="mine", hits=[shared])
    fused = fuse_scoped_candidates([official, mine], top_k=1)
    assert fused[0].chunk_id == "shared"
    assert set(fused[0].scopes) == {"official", "mine"}
    assert fused[0].ranks == {"official": 1, "mine": 1}


def test_exact_target_is_protected() -> None:
    targets = exact_targets_from_query("请讲解 official-2.md page 2 的第 3 题")
    assert {target.kind for target in targets} == {"file", "page", "question"}
    fused = fuse_scoped_candidates(
        [_scope("official", 3), _scope("mine", 3)], top_k=1, exact_targets=targets
    )
    assert fused[0].exact is True
    assert fused[0].chunk_id == "official-2"


def test_candidates_without_stable_ids_are_dropped() -> None:
    anonymous = [Hit(chunk_id="", document_id="d", filename="f.md")]
    fused = fuse_scoped_candidates(
        [ScopedCandidates(scope="official", hits=anonymous), _scope("mine", 1)], top_k=2
    )
    assert [entry.chunk_id for entry in fused] == ["mine-1"]


def test_budget_text_trims_at_a_boundary() -> None:
    text = "第一段。" * 40 + "\n\n" + "第二段。" * 40
    trimmed = budget_text(text, 60, per_hit_chars=10_000)
    assert trimmed.endswith("…")
    assert "第二段。" not in trimmed
    assert len(trimmed) <= 61


def test_citation_ids_and_trace_digest_are_server_assigned() -> None:
    assert citation_id(1) == "S1"
    fused = fuse_scoped_candidates([_scope("official", 2)], top_k=2)
    assert trace_digest(fused) == trace_digest(fused)
    assert trace_digest(fused) != trace_digest(fused[:1])
