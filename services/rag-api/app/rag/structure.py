import re
from dataclasses import dataclass

from app.rag.types import SourceSection


@dataclass(frozen=True, slots=True)
class StructuredBlock:
    content: str
    metadata: dict[str, str | int | None]
    parent_key: str


DOCUMENT_KIND = re.compile(
    r"\b(?P<kind>assignment|tutorial|tut|practice(?:\s+problems?)?)"
    r"[_\s-]*0*(?P<number>\d+)",
    re.IGNORECASE,
)
EXPLICIT_QUESTION = re.compile(
    r"(?im)^\s*(?:question|q(?:uestion)?\.?)\s*"
    r"(?P<number>\d+|[ivxlcdm]+)\b[^\n]*"
)
NUMBERED_QUESTION = re.compile(r"(?m)^\s*(?P<number>\d+)[.)]\s+[^\n]+")
QUESTION_PART = re.compile(
    r"(?im)^\s*(?:"
    r"[\(\uFF08](?P<paren_part>[a-z]|\d+)[\)\uFF09]"
    r"|(?P<plain_part>[a-z])[.)]"
    r")\s*"
)


def _kind_metadata(text: str) -> tuple[str | None, str | None]:
    match = DOCUMENT_KIND.search(text)
    if match is None:
        return None, None
    kind = match.group("kind").casefold()
    if kind == "tut":
        kind = "tutorial"
    elif kind.startswith("practice"):
        kind = "practice"
    number = match.group("number").lstrip("0") or "0"
    return kind, number


def _question_matches(text: str, kind: str | None) -> list[re.Match[str]]:
    explicit = list(EXPLICIT_QUESTION.finditer(text))
    if explicit:
        return explicit
    if kind in {"tutorial", "practice"}:
        return list(NUMBERED_QUESTION.finditer(text))
    return []


def extract_structured_blocks(
    section: SourceSection,
    previous: StructuredBlock | None = None,
) -> list[StructuredBlock]:
    """Extract question/part blocks only when the document exposes clear structure."""

    descriptor = "\n".join(value for value in (section.section, section.text) if value)
    kind, document_number = _kind_metadata(descriptor)
    if previous is not None:
        previous_kind = previous.metadata.get("document_kind")
        previous_number = previous.metadata.get("document_number")
        kind = kind or (str(previous_kind) if previous_kind else None)
        document_number = document_number or (
            str(previous_number) if previous_number else None
        )
    questions = _question_matches(section.text, kind)
    if not questions:
        if previous is None:
            return []
        continuation_metadata = {
            **previous.metadata,
            "source_locator": f"{section.locator_type} {section.locator_value}",
        }
        return [StructuredBlock(section.text.strip(), continuation_metadata, previous.parent_key)]
    blocks: list[StructuredBlock] = []
    document_header = section.text[: questions[0].start()].strip()
    if previous is not None and document_header:
        continuation_metadata = {
            **previous.metadata,
            "source_locator": f"{section.locator_type} {section.locator_value}",
        }
        blocks.append(
            StructuredBlock(document_header, continuation_metadata, previous.parent_key)
        )
        document_header = ""
    for index, question in enumerate(questions):
        end = questions[index + 1].start() if index + 1 < len(questions) else len(section.text)
        question_text = section.text[question.start() : end].strip()
        question_number = question.group("number").upper()
        parent_key = ":".join(
            part for part in (kind or "document", document_number, f"q{question_number}") if part
        )
        metadata: dict[str, str | int | None] = {
            "document_kind": kind,
            "document_number": document_number,
            "question_number": question_number,
            "question_part": None,
            "heading_path": f"Question {question_number}",
            "source_locator": f"{section.locator_type} {section.locator_value}",
        }
        parts = list(QUESTION_PART.finditer(question_text))
        if not parts:
            content = "\n".join(part for part in (document_header, question_text) if part)
            blocks.append(StructuredBlock(content, metadata, parent_key))
            continue
        stem = question_text[: parts[0].start()].strip()
        prefix = "\n".join(part for part in (document_header, stem) if part)
        for part_index, part in enumerate(parts):
            part_end = (
                parts[part_index + 1].start()
                if part_index + 1 < len(parts)
                else len(question_text)
            )
            part_text = question_text[part.start() : part_end].strip()
            part_name = (part.group("paren_part") or part.group("plain_part")).casefold()
            part_metadata = {
                **metadata,
                "question_part": part_name,
                "heading_path": f"Question {question_number}({part_name})",
            }
            content = "\n".join(value for value in (prefix, part_text) if value)
            blocks.append(StructuredBlock(content, part_metadata, parent_key))
    return blocks
