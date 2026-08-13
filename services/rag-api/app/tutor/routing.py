import re
from dataclasses import dataclass
from enum import StrEnum


class QueryIntent(StrEnum):
    COURSE_GROUNDED = "COURSE_GROUNDED"
    COURSE_TUTORING = "COURSE_TUTORING"
    GENERAL_CONVERSATION = "GENERAL_CONVERSATION"
    COURSE_META = "COURSE_META"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class RouteDecision:
    intent: QueryIntent
    uses_course_retrieval: bool
    reason: str


EXPLICIT_GROUNDING = re.compile(
    r"(?:课件|讲义|课程资料|slides?|lecture|according\s+to|材料中|老师.*(?:说|定义))",
    re.IGNORECASE,
)
COURSE_META = re.compile(
    r"(?:有哪些|列出|多少).*(?:资料|文档|课件|文件)|"
    r"(?:资料|文档|课件|文件).*(?:有哪些|list|available)",
    re.IGNORECASE,
)
GENERAL = re.compile(
    r"^(?:你?好|hello|hi|hey|跟我聊|聊两句)|"
    r"(?:今天|today).*(?:累|疲惫|状态|tired|study)|"
    r"(?:学习状态|心情|焦虑|休息).*(?:怎么办|建议|how)",
    re.IGNORECASE,
)
TUTORING = re.compile(
    r"(?:为什么|为啥|why|怎么理解|如何理解|教我|讲解|解释|"
    r"举.*(?:例|题)|例题|step\s+by\s+step|teach\s+me|"
    r"不懂|没懂|没明白|换一种)",
    re.IGNORECASE,
)


def route_query(question: str) -> RouteDecision:
    """Select a response strategy with deterministic, explainable precedence."""

    normalized = " ".join(question.strip().split())
    if EXPLICIT_GROUNDING.search(normalized):
        return RouteDecision(QueryIntent.COURSE_GROUNDED, True, "explicit_course_evidence")
    if COURSE_META.search(normalized):
        return RouteDecision(QueryIntent.COURSE_META, False, "course_metadata_request")
    if GENERAL.search(normalized):
        return RouteDecision(QueryIntent.GENERAL_CONVERSATION, False, "social_or_study_support")
    if TUTORING.search(normalized):
        return RouteDecision(QueryIntent.COURSE_TUTORING, True, "teaching_request")
    return RouteDecision(QueryIntent.AMBIGUOUS, True, "insufficient_intent_signal")

