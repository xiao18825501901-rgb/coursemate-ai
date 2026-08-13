from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SourceSection:
    """Text and its human-readable location in a source document."""

    text: str
    locator_type: str
    locator_value: str
    section: str | None = None
    metadata: dict[str, str | int | None] = field(default_factory=dict)
    parent_key: str | None = None


@dataclass(frozen=True, slots=True)
class TextChunk:
    """A bounded text unit that retains its source location."""

    ordinal: int
    content: str
    locator_type: str
    locator_value: str
    section: str | None = None
    metadata: dict[str, str | int | None] = field(default_factory=dict)
    parent_key: str | None = None


@dataclass(frozen=True, slots=True)
class SearchHit:
    """A traceable retrieval result with channel-specific or fused score."""

    chunk_id: str
    document_id: str
    course_id: str
    filename: str
    content: str
    locator_type: str
    locator_value: str
    section: str | None
    score: float
    channels: tuple[str, ...]
    metadata: dict[str, str | int | None] = field(default_factory=dict)
    parent_key: str | None = None
