"""The server's own comparison of two solutions' machine-readable answers.

`question.answer_agreement.v1` asks whether the author's solution and an
independent blind solve reach the same answer.  Until now that judgement was
made by the two model roles alone, and the measured consequence is in the
record: the 2026-09-30 run recorded four injected `DISAGREEING_SOLUTION` rows
that both roles accepted, and every one of them was a pair whose answer could
have been compared arithmetically.

An answer that a machine can read does not need a vote.  Where both solutions
expose the same channel in a comparable form the server compares them itself:

* the channels **disagree** -> `FAIL`, deterministically, whatever the roles
  said.  This is the direction that matters: it is how a wrongly accepted item
  is caught;
* the channels **agree** -> no opinion.  Equality of two rendered numbers is not
  agreement of reasoning, and that judgement stays with the roles;
* either side **unreadable** -> no opinion.  Prose answers are the normal case,
  and guessing at them is how a checker starts inventing disagreements.

The check is therefore refuse-only: it can take a `PASS` away and can never
grant one.  It cannot create a false accept, which is the same asymmetry the
specification pass and the completeness certificate already have.

The comparison is deliberately narrow.  A channel is only read when its value is
unambiguous in both solutions -- an integer option index, or a string that is
nothing but one number.  `"about 42"` is not read as 42, because a checker that
normalises prose will eventually call two different answers equal, and that
failure is silent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Final

VERDICT_AGREE: Final = "AGREE"
VERDICT_DISAGREE: Final = "DISAGREE"
VERDICT_UNREADABLE: Final = "UNREADABLE"

CHANNEL_OPTION_INDEX: Final = "correct_option_index"
CHANNEL_NUMBER: Final = "number"

# A value is a number only when it is nothing but a number.  Thousands
# separators and a leading sign are accepted because both renderings appear in
# authored items; currency symbols, units and prose are not, because reading
# them requires interpreting the text.
_NUMBER = re.compile(r"^[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$")


@dataclass(frozen=True)
class AnswerAgreementCheck:
    """One deterministic comparison of the two solutions' declared answers."""

    verdict: str
    channel: str | None = None
    detail: str = ""

    @property
    def disagrees(self) -> bool:
        return self.verdict == VERDICT_DISAGREE


def read_number(value: Any) -> Decimal | None:
    """The value as a number, or `None` when it is not unambiguously one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not _NUMBER.match(text.replace(",", "")) and not _NUMBER.match(text):
        return None
    try:
        return Decimal(text.replace(",", ""))
    except InvalidOperation:  # pragma: no cover - guarded by the pattern
        return None


def _as_option_index(value: Any) -> int | None:
    """The value as an option index, or `None`.

    `bool` is excluded on purpose: `True == 1` would otherwise compare equal to
    option 1 and invent agreement between an index and a flag.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _option_index(solution: dict[str, Any]) -> int | None:
    return _as_option_index(solution.get(CHANNEL_OPTION_INDEX))


def _declared_number(solution: dict[str, Any]) -> tuple[Decimal | None, str]:
    """The solution's declared final answer as a number, with its field name."""
    for field in ("answer", "candidate_answer"):
        if field not in solution:
            continue
        number = read_number(solution.get(field))
        if number is not None:
            return number, field
    return None, ""


def compare_answers(
    solution_a: dict[str, Any], solution_b: dict[str, Any]
) -> AnswerAgreementCheck:
    """Compare two solutions' declared answers, refusing only on a real conflict.

    The option-index channel is tried first because an MCQ's answer *is* the
    selected option: a numeric reading of the option's own text would compare
    the wrong fact, and the two solutions usually restate the option text
    differently even when they select the same one.
    """
    if not isinstance(solution_a, dict) or not isinstance(solution_b, dict):
        return AnswerAgreementCheck(VERDICT_UNREADABLE, None, "not a solution object")

    index_a = _option_index(solution_a)
    index_b = _option_index(solution_b)
    if index_a is not None and index_b is not None:
        if index_a != index_b:
            return AnswerAgreementCheck(
                VERDICT_DISAGREE,
                CHANNEL_OPTION_INDEX,
                f"solution A selects option {index_a}, solution B selects option {index_b}",
            )
        return AnswerAgreementCheck(
            VERDICT_AGREE,
            CHANNEL_OPTION_INDEX,
            f"both solutions select option {index_a}",
        )

    number_a, field_a = _declared_number(solution_a)
    number_b, field_b = _declared_number(solution_b)
    if number_a is not None and number_b is not None:
        if number_a != number_b:
            return AnswerAgreementCheck(
                VERDICT_DISAGREE,
                CHANNEL_NUMBER,
                f"solution A declares {number_a} in {field_a}, "
                f"solution B declares {number_b} in {field_b}",
            )
        return AnswerAgreementCheck(
            VERDICT_AGREE, CHANNEL_NUMBER, f"both solutions declare {number_a}"
        )

    return AnswerAgreementCheck(
        VERDICT_UNREADABLE,
        None,
        "at least one solution declares no machine-readable answer",
    )
