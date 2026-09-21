"""Explicit commands must be routed deterministically, without spending a Jev call.

These tests pin the conservative contract: only an *explicit* command is routed (the
message is the command, modulo politeness and punctuation); anything with semantic
content returns ``None`` so the normal path can judge it. The vocabulary follows the
CONTINUOUS_TEACHING protocol of the V2 templates.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.learning import intent_commands as router

ACTIONS = {
    "CONTINUE",
    "ANSWER_ONLY",
    "ANSWER_AND_RESUME",
    "PAUSE",
    "QUIZ_WAIT",
    "SUBMIT_ASSESSMENT",
    "OTHER",
}


@pytest.mark.parametrize(
    "message",
    ["继续", "接着讲", "往下说", "回到主线", "回到原主线", "继续，谢谢", "请继续",
     "continue", "Continue!", "go on", "carry on", "resume", "back to the mainline",
     "please continue", " 继续 ", "继续。",
     # the lesson itself as the object is still the same command
     "继续上课", "继续讲课", "请继续教学", "continue the lesson", "please continue the class"],
)
def test_resume_commands_route_to_continue(message: str) -> None:
    assert router.route_explicit_command(message) == "CONTINUE"


@pytest.mark.parametrize(
    "message",
    ["继续讲一下 K-means", "continue with the previous topic", "继续课程第三章的内容"],
)
def test_continue_with_a_new_topic_is_not_an_explicit_command(message: str) -> None:
    """A different object is a new request: that is semantic, not a command."""
    assert router.route_explicit_command(message) is None


@pytest.mark.parametrize(
    "message", ["暂停", "先停一下", "停一下", "pause", "stop", "hold on", "稍后继续"]
)
def test_pause_commands_route_to_pause(message: str) -> None:
    assert router.route_explicit_command(message) == "PAUSE"


@pytest.mark.parametrize(
    "message",
    ["只回答", "只解释这个", "只讲这一点", "仅回答", "answer only", "just answer", "only this"],
)
def test_answer_only_commands_do_not_advance_the_lesson(message: str) -> None:
    assert router.route_explicit_command(message) == "ANSWER_ONLY"


@pytest.mark.parametrize(
    "message",
    ["给答案然后继续", "给答案再继续", "答完继续", "answer then continue",
     "answer it then resume"],
)
def test_answer_then_resume_is_distinct_from_resume(message: str) -> None:
    assert router.route_explicit_command(message) == "ANSWER_AND_RESUME"


@pytest.mark.parametrize(
    "message", ["做一题", "来一题", "来一道题", "出一题", "给我一题", "quiz me", "one question"]
)
def test_exercise_requests_route_to_quiz_wait(message: str) -> None:
    assert router.route_explicit_command(message) == "QUIZ_WAIT"


@pytest.mark.parametrize("message", ["交卷", "提交答案", "提交测评", "submit", "hand in"])
def test_submission_requires_an_active_assessment(message: str) -> None:
    # Without an active assessment there is nothing to submit, so the command is not
    # an explicit submission and must fall through to the normal path.
    assert router.route_explicit_command(message) is None
    assert (
        router.route_explicit_command(message, active_assessment="session-1")
        == "SUBMIT_ASSESSMENT"
    )


def test_exercise_request_during_an_assessment_is_ambiguous() -> None:
    assert router.route_explicit_command("做一题", active_assessment="session-1") is None


def test_resume_during_an_assessment_without_a_mode_is_ambiguous() -> None:
    assert router.route_explicit_command("继续", active_assessment="session-1") is None
    assert (
        router.route_explicit_command(
            "继续", active_assessment="session-1", current_mode="teach"
        )
        == "CONTINUE"
    )


@pytest.mark.parametrize(
    "message",
    [
        "",
        "   ",
        "\t\n",
        "继续，不过先讲讲 K-means 和 DBSCAN 的区别",
        "继续讲一下 DBSCAN 的密度可达性",
        "我不太懂前置的 eps 是什么意思",
        "为什么这里要用 minPts",
        "continue but explain the previous step first",
        "回到主线之前先把这道题讲完",
    ],
)
def test_commands_with_semantic_content_are_left_to_the_normal_path(message: str) -> None:
    assert router.route_explicit_command(message) is None


def test_router_never_invents_an_action() -> None:
    samples = [
        "继续", "暂停", "做一题", "交卷", "只回答", "给答案然后继续", "回到主线",
        "continue", "pause", "quiz me", "submit", "answer only", "unknown text",
        "继续继续继续", "!", "。",
    ]
    for message in samples:
        action = router.route_explicit_command(message, active_assessment="a")
        assert action is None or action in ACTIONS, message


def test_router_tolerates_extreme_input() -> None:
    assert router.route_explicit_command("继续" * 5000) is None  # not an explicit command
    assert router.route_explicit_command("\u3000继续\u3000") == "CONTINUE"
    assert router.route_explicit_command("CONTINUE") == "CONTINUE"


def test_router_imports_no_jev_and_needs_no_transport() -> None:
    """The whole point: an explicit command must not spend a Jev call."""
    source = Path(inspect.getsourcefile(router) or "").read_text(encoding="utf-8")
    code_lines = [
        line
        for line in source.splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    assert not any("jev" in line.casefold() for line in code_lines), code_lines
    assert "jev" not in vars(router)


def test_is_explicit_command_matches_route() -> None:
    assert router.is_explicit_command("继续") is True
    assert router.is_explicit_command("解释一下这题") is False
