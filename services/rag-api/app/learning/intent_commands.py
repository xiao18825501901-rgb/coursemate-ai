"""Deterministic handling of *explicit* teaching commands (requirement: 明确命令优先).

Requirement: "明确按钮和明确命令优先由确定性代码处理，不浪费 Jev 调用." The UI already
has explicit buttons; this module covers the typed equivalents, so an explicit command
is answered by deterministic code and never spends a Jev call.

Design rules, deliberately conservative:

* only an **explicit** command fires — the message must be the command itself (allowing
  politeness/punctuation/whitespace around it). A command embedded in a longer question
  ("继续，不过先讲讲 X 为什么") is a *detour* — that is semantic, so it returns ``None``
  and the normal path (Jev when enabled, deterministic default otherwise) decides;
* the vocabulary is the CONTINUOUS_TEACHING protocol shipped in the V2 templates
  (继续 / 只回答 / 暂停 / 做一题 / 回到主线 / 给答案然后继续), plus the plain English
  equivalents, because the same conversation may be held in either language;
* the return value is always one of the eight ``intent.next_action.v1`` candidate ids, or
  ``None``; it never invents a new action and never raises;
* it imports no Jev module and performs no I/O, so "no Jev call was wasted" is provable by
  test rather than by comment.

The teaching-run caller (outside this repository) should call this first and, when it
returns an action, skip the semantic call entirely; otherwise it passes its own
state-derived baseline into ``SemanticDecisionService.next_action(deterministic=...)``.
"""

from __future__ import annotations

import re
from typing import Final

# action ids, identical to the catalog's `intent.next_action.v1` candidates.
CONTINUE: Final = "CONTINUE"
ANSWER_ONLY: Final = "ANSWER_ONLY"
ANSWER_AND_RESUME: Final = "ANSWER_AND_RESUME"
PAUSE: Final = "PAUSE"
QUIZ_WAIT: Final = "QUIZ_WAIT"
SUBMIT_ASSESSMENT: Final = "SUBMIT_ASSESSMENT"
OTHER: Final = "OTHER"

# Longest phrases first so "给答案然后继续" is not shadowed by "继续".
_COMMAND_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # resume the mainline after dealing with the current question
    (re.compile(
        r"^(给答案(然后|再)?继续|答完(再)?继续|"
        r"answer(\s+it)?\s+then\s+(continue|resume))$"
    ), ANSWER_AND_RESUME),
    # stop for now
    (re.compile(r"^(暂停|先停(一下)?|停一下|稍后继续|pause|stop( for now)?|hold on)$"), PAUSE),
    # answer only this, do not advance the lesson
    (re.compile(
        r"^(只回答|只解释(这个|一下)?|只讲(这个|这一点)?|仅回答|"
        r"answer only|just answer( this)?|only this)$"
    ), ANSWER_ONLY),
    # back to the mainline / carry on teaching. The trailing object is accepted only
    # when it refers to the lesson itself ("继续上课" / "continue the lesson"); any
    # other object carries a new request, which is semantic and must not be routed here.
    (re.compile(
        r"^(继续|接着(讲|说)?|往下(讲|说)?|回到主线|回到(原)?主线|回到刚才|"
        r"continue|go on|carry on|resume|back to the main ?line)"
        r"(\s*(the\s+)?(lesson|teaching|class|course)|讲课|上课|教学|课程)?$"
    ), CONTINUE),
    # explicit exercise request: wait for the learner's own attempt
    (re.compile(
        r"^(做一题|来一题|来一道题|出一题|给我一题|练一题|"
        r"give me (a )?(question|problem)|quiz me|one question)$"
    ), QUIZ_WAIT),
    # explicit submission of the active assessment
    (re.compile(
        r"^(交卷|提交答案|提交测评|"
        r"submit( the)?( assessment| answers?)?|hand in)$"
    ), SUBMIT_ASSESSMENT),
)

_PUNCTUATION = r"[\s，,。.!！?？~～、:：;；]*"
_TRAILING_POLITENESS = re.compile(
    _PUNCTUATION + r"(谢谢|多谢|麻烦了|please|thanks|thank you)?" + _PUNCTUATION + r"$",
    re.IGNORECASE,
)
_LEADING_POLITENESS = re.compile(r"^(请|麻烦|帮我|please|pls)\s*", re.IGNORECASE)


def normalise(message: str) -> str:
    """Strip politeness and punctuation so only the command remains."""
    text = (message or "").strip()
    text = _LEADING_POLITENESS.sub("", text)
    text = _TRAILING_POLITENESS.sub("", text)
    return text.strip().casefold()


def route_explicit_command(
    message: str,
    *,
    current_mode: str | None = None,
    active_assessment: str | None = None,
) -> str | None:
    """Return the deterministic action for an explicit command, else ``None``.

    ``current_mode`` and ``active_assessment`` only *guard* a command, they never
    create one: submitting answers is meaningful only while an assessment is active,
    and asking for the mainline while an assessment occupies the screen is a plain
    continue of the assessment flow rather than a teaching step.
    """
    text = normalise(message)
    if not text:
        return None
    for pattern, action in _COMMAND_PATTERNS:
        if not pattern.match(text):
            continue
        if action == SUBMIT_ASSESSMENT and not active_assessment:
            # Nothing to submit: do not pretend the assessment exists.
            return None
        if action == QUIZ_WAIT and active_assessment:
            # An assessment is already open; asking for an exercise is ambiguous.
            return None
        if action == CONTINUE and active_assessment and not current_mode:
            # "继续" with an assessment open and no teaching mode is ambiguous.
            return None
        return action
    return None


def is_explicit_command(message: str) -> bool:
    """True when the message is exactly an explicit command (no semantic work needed)."""
    return route_explicit_command(message) is not None
