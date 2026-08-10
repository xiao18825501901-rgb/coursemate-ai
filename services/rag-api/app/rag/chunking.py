import re

from app.rag.types import SourceSection, TextChunk


def _normalize_paragraphs(text: str) -> list[str]:
    paragraphs = re.split(r"\n\s*\n+", text.strip())
    return [re.sub(r"\s+", " ", paragraph).strip() for paragraph in paragraphs if paragraph.strip()]


def _split_word_aware(text: str, limit: int) -> list[str]:
    words = text.split()
    pieces: list[str] = []
    current: list[str] = []
    current_length = 0

    for word in words:
        if len(word) > limit:
            if current:
                pieces.append(" ".join(current))
                current = []
                current_length = 0
            pieces.extend(word[offset : offset + limit] for offset in range(0, len(word), limit))
            continue

        candidate_length = current_length + (1 if current else 0) + len(word)
        if current and candidate_length > limit:
            pieces.append(" ".join(current))
            current = [word]
            current_length = len(word)
        else:
            current.append(word)
            current_length = candidate_length

    if current:
        pieces.append(" ".join(current))
    return pieces


def _overlap_suffix(text: str, overlap: int) -> str:
    if overlap == 0:
        return ""
    suffix: list[str] = []
    length = 0
    for word in reversed(text.split()):
        candidate_length = length + (1 if suffix else 0) + len(word)
        if candidate_length > overlap:
            break
        suffix.append(word)
        length = candidate_length
    return " ".join(reversed(suffix))


def _chunk_section(text: str, *, chunk_size: int, overlap: int) -> list[str]:
    units: list[str] = []
    for paragraph in _normalize_paragraphs(text):
        if len(paragraph) <= chunk_size:
            units.append(paragraph)
        else:
            units.extend(_split_word_aware(paragraph, chunk_size))

    chunks: list[str] = []
    current = ""
    for unit in units:
        separator = "\n\n" if current else ""
        if len(current) + len(separator) + len(unit) <= chunk_size:
            current = f"{current}{separator}{unit}"
            continue

        if current:
            chunks.append(current)
            prefix = _overlap_suffix(current, overlap)
            candidate = f"{prefix} {unit}" if prefix else unit
            current = candidate if len(candidate) <= chunk_size else unit
        else:
            current = unit

    if current:
        chunks.append(current)
    return chunks


def chunk_sections(
    sections: list[SourceSection],
    *,
    chunk_size: int,
    overlap: int,
) -> list[TextChunk]:
    """Split sections into deterministic chunks while retaining source metadata."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    if overlap < 0:
        raise ValueError("overlap must not be negative")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    chunks: list[TextChunk] = []
    for source in sections:
        for content in _chunk_section(source.text, chunk_size=chunk_size, overlap=overlap):
            chunks.append(
                TextChunk(
                    ordinal=len(chunks),
                    content=content,
                    locator_type=source.locator_type,
                    locator_value=source.locator_value,
                    section=source.section,
                )
            )
    return chunks
