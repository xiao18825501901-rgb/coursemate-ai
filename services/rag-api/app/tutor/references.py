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
    r"(?:(?:question|quest(?:ion)?|q)\s*(?P<number_en>[0-9]+|[ivxlcdm]+)"
    r"|第\s*(?P<number_zh>[0-9]+|[ivxlcdm]+)\s*题)"
    r"(?:\s*[\(\uFF08]?\s*(?P<part>[a-z])\s*[\)\uFF09]?)?",
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


def parse_query_reference(query: str) -> QueryReference:
    normalized = " ".join(query.strip().split())
    file_match = FILE_REFERENCE.search(normalized)
    document = file_match.group("filename").strip() if file_match else None
    kind, document_number = _document_kind(document or normalized)
    question = QUESTION.search(normalized)
    page = PAGE.search(normalized)
    slide = SLIDE.search(normalized)
    question_number = _matched_number(question)
    page_number = _matched_number(page)
    slide_number = _matched_number(slide)
    return QueryReference(
        document=document,
        document_kind=kind,
        document_number=document_number,
        question_number=question_number.upper() if question_number else None,
        question_part=question.group("part").casefold()
        if question and question.group("part")
        else None,
        page_number=int(page_number) if page_number else None,
        slide_number=int(slide_number) if slide_number else None,
    )
