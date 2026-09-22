import re
from dataclasses import dataclass
from enum import StrEnum


class DocumentKind(StrEnum):
    ASSIGNMENT = "assignment"
    TUTORIAL = "tutorial"
    LECTURE = "lecture"
    EXAM = "exam"
    PRACTICE = "practice"


@dataclass(frozen=True, slots=True)
class QueryReference:
    document: str | None = None
    document_kind: DocumentKind | None = None
    document_number: str | None = None
    question_number: str | None = None
    question_part: str | None = None
    page_number: int | None = None
    slide_number: int | None = None
    # Character span of the question label inside :func:`normalize_query` output.
    # It is the locator the extraction verifier checks the label against, so a
    # reference always carries where in the query it was read from.
    question_span: tuple[int, int] | None = None


FILE_REFERENCE = re.compile(
    r"(?P<filename>[A-Za-z0-9_][\w .\-\[\]()]*?\.(?:pdf|docx|pptx|md|txt))"
    r"(?=$|\s|的)",
    re.IGNORECASE,
)
KIND_PATTERNS: tuple[tuple[DocumentKind, re.Pattern[str]], ...] = (
    (DocumentKind.ASSIGNMENT, re.compile(r"assignment[_\s-]*(\d+)", re.I)),
    (DocumentKind.TUTORIAL, re.compile(r"(?:tutorial|tut)[_\s-]*0*(\d+)", re.I)),
    (DocumentKind.LECTURE, re.compile(r"(?:lecture|lec)[_\s-]*0*(\d+)", re.I)),
    (DocumentKind.EXAM, re.compile(r"(?:exam|past\s*paper)[_\s-]*0*(\d+)?", re.I)),
    (DocumentKind.PRACTICE, re.compile(r"practice[_\s-]*(?:problem[s]?)?[_\s-]*0*(\d+)", re.I)),
)
QUESTION = re.compile(
    r"(?:(?:question|quest(?:ion)?|q)\s*(?P<number_en>[0-9]+|[ivxlcdm]+(?![a-z0-9]))"
    r"|第\s*(?P<number_zh>[0-9]+|[ivxlcdm]+(?![a-z0-9]))\s*题)"
    # A sub-part is read only when it is *delimited*: either parenthesised
    # ("Question 1(b)", "Q3(2)") or a standalone token separated from the number
    # by whitespace and not glued to a following word ("q 2 b"). A bare letter
    # that continues a word is prose, not a part: "question 5 have to do with
    # chapter 2" must not yield part "h", and "q mean in this context" must not
    # yield the roman number "M". Getting this wrong is not cosmetic — the
    # reference becomes an exact-locator SQL filter, so an invented part letter
    # can pin retrieval onto the wrong sub-question.
    r"(?:\s*[\(\uFF08]\s*(?P<paren_part>[a-z]|\d+)\s*[\)\uFF09]"
    r"|\s+(?P<bare_part>[a-z]|\d+)(?![a-z0-9]))?",
    re.IGNORECASE,
)
PAGE = re.compile(
    r"(?:(?:page|p\.?)\s*(?P<number_en>\d+)|第\s*(?P<number_zh>\d+)\s*页)",
    re.I,
)
SLIDE = re.compile(
    r"(?:slide\s*(?P<number_en>\d+)|第\s*(?P<number_zh>\d+)\s*张(?:幻灯片)?)",
    re.I,
)


def _matched_number(match: re.Match[str] | None) -> str | None:
    if match is None:
        return None
    return match.group("number_en") or match.group("number_zh")


def _document_kind(text: str) -> tuple[DocumentKind | None, str | None]:
    for kind, pattern in KIND_PATTERNS:
        if match := pattern.search(text):
            number = match.group(1) if match.lastindex else None
            return kind, number.lstrip("0") or "0" if number else None
    return None, None


def normalize_query(query: str) -> str:
    """Collapse whitespace the way the reference parser (and its spans) see it."""
    return " ".join(query.strip().split())


def parse_query_reference(query: str) -> QueryReference:
    normalized = normalize_query(query)
    file_match = FILE_REFERENCE.search(normalized)
    document = file_match.group("filename").strip() if file_match else None
    kind, document_number = _document_kind(document or normalized)
    question = QUESTION.search(normalized)
    page = PAGE.search(normalized)
    slide = SLIDE.search(normalized)
    question_number = _matched_number(question)
    page_number = _matched_number(page)
    slide_number = _matched_number(slide)
    question_part = None
    if question is not None:
        question_part = question.group("paren_part") or question.group("bare_part")
    return QueryReference(
        document=document,
        document_kind=kind,
        document_number=document_number,
        question_number=question_number.upper() if question_number else None,
        question_part=question_part.casefold() if question_part else None,
        page_number=int(page_number) if page_number else None,
        slide_number=int(slide_number) if slide_number else None,
        question_span=(question.start(), question.end()) if question is not None else None,
    )
