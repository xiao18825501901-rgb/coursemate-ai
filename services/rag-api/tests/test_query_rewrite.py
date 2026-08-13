from app.tutor.rewrite import ConversationTurn, rewrite_retrieval_query
from app.tutor.strategy import TeachingApproach, choose_teaching_approach


def test_rewrites_short_follow_up_with_previous_user_topic() -> None:
    history = [
        ConversationTurn(role="user", content="什么是 DBSCAN 的 core point？"),
        ConversationTurn(role="assistant", content="核心点需要满足邻域样本数阈值。"),
    ]

    result = rewrite_retrieval_query("为什么？", history)

    assert result.was_rewritten is True
    assert "DBSCAN" in result.query
    assert "为什么" in result.query


def test_keeps_standalone_question_unchanged_and_bounds_rewrite() -> None:
    standalone = "According to lecture 7, compare ambient and diffuse lighting."
    assert rewrite_retrieval_query(standalone, []).query == standalone

    history = [ConversationTurn(role="user", content="x" * 1_000)]
    rewritten = rewrite_retrieval_query("what about that?", history, max_chars=240)
    assert rewritten.was_rewritten is True
    assert len(rewritten.query) <= 240


def test_progressive_teaching_changes_after_repeated_confusion() -> None:
    assert choose_teaching_approach([]) is TeachingApproach.FORMAL
    assert choose_teaching_approach([
        ConversationTurn(role="user", content="我还是不懂"),
    ]) is TeachingApproach.ANALOGY
    assert choose_teaching_approach([
        ConversationTurn(role="user", content="我还是不懂"),
        ConversationTurn(role="assistant", content="换个比喻。"),
        ConversationTurn(role="user", content="还是没明白"),
    ]) is TeachingApproach.WORKED_EXAMPLE
    assert choose_teaching_approach([
        ConversationTurn(role="user", content="没懂"),
        ConversationTurn(role="user", content="还是没明白"),
        ConversationTurn(role="user", content="能再换一种吗"),
    ]) is TeachingApproach.SOCRATIC
