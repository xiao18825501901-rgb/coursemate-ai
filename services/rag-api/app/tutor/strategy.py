import re
from enum import StrEnum

from app.tutor.rewrite import ConversationTurn


class TeachingApproach(StrEnum):
    FORMAL = "formal"
    ANALOGY = "analogy"
    WORKED_EXAMPLE = "worked_example"
    SOCRATIC = "socratic"


CONFUSION = re.compile(r"(?:不懂|没懂|没明白|换一种|don't understand|still confused)", re.I)


def choose_teaching_approach(history: list[ConversationTurn]) -> TeachingApproach:
    attempts = sum(
        1 for turn in history if turn.role == "user" and CONFUSION.search(turn.content)
    )
    return (
        TeachingApproach.FORMAL,
        TeachingApproach.ANALOGY,
        TeachingApproach.WORKED_EXAMPLE,
        TeachingApproach.SOCRATIC,
    )[min(attempts, 3)]

