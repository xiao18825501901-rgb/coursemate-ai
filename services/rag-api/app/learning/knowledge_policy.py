from __future__ import annotations

from app.errors import ApiError


MAX_EFFECTIVE_COURSE_NODES = 50


def enforce_effective_node_budget(member_count: int) -> None:
    """Reject a materialized course view that exceeds the product-wide budget.

    A membership is a real node in the effective view. Composite chapters,
    atomic learning units, and an explicitly stored root therefore all consume
    one slot. Source chunks and citations are intentionally not memberships.
    """

    if member_count > MAX_EFFECTIVE_COURSE_NODES:
        raise ApiError(
            422,
            "TREE_NODE_LIMIT_EXCEEDED",
            f"A course knowledge view may contain at most "
            f"{MAX_EFFECTIVE_COURSE_NODES} effective nodes, including chapters and roots.",
        )
