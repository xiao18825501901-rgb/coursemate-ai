import re
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ConversationTurn:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class RewriteResult:
    query: str
    was_rewritten: bool


FOLLOW_UP = re.compile(
    r"^(?:为什么|怎么|然后呢|那呢|这个呢|为什么呢|"
    r"我?还是?(?:不懂|没懂|没明白)|能再换一种吗|"
    r"what\s+about\s+(?:it|that)|why|how|and\s+then)[?？.!！。\s]*$",
    re.IGNORECASE,
)


def rewrite_retrieval_query(
    question: str,
    history: list[ConversationTurn],
    *,
    max_chars: int = 320,
) -> RewriteResult:
    """Make a short follow-up retrievable without changing the stored user message."""

    normalized = " ".join(question.strip().split())
    if not FOLLOW_UP.match(normalized):
        return RewriteResult(normalized[:max_chars], False)
    topic = next(
        (
            " ".join(turn.content.strip().split())
            for turn in reversed(history)
            if turn.role == "user"
            and turn.content.strip()
            and not FOLLOW_UP.match(" ".join(turn.content.strip().split()))
        ),
        "",
    )
    if not topic:
        return RewriteResult(normalized[:max_chars], False)
    prefix = f"{topic} — follow-up: "
    available = max(max_chars - len(prefix), 0)
    return RewriteResult(f"{prefix}{normalized[:available]}"[:max_chars], True)
