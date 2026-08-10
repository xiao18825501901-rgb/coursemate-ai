import pytest

from app.rag.chunking import chunk_sections
from app.rag.types import SourceSection


def section(text: str) -> SourceSection:
    return SourceSection(
        text=text,
        locator_type="page",
        locator_value="7",
        section="Lighting",
    )


def test_chunker_preserves_paragraphs_and_metadata_when_they_fit() -> None:
    first = "Ambient light approximates indirect illumination."
    second = "Diffuse light depends on the normal and light direction."
    chunks = chunk_sections([section(f"{first}\n\n{second}")], chunk_size=70, overlap=0)

    assert [chunk.content for chunk in chunks] == [first, second]
    assert all(chunk.locator_type == "page" for chunk in chunks)
    assert all(chunk.locator_value == "7" for chunk in chunks)
    assert all(chunk.section == "Lighting" for chunk in chunks)
    assert [chunk.ordinal for chunk in chunks] == [0, 1]


def test_chunker_splits_oversized_paragraphs_on_word_boundaries() -> None:
    text = "one two three four five six seven eight nine ten eleven twelve"
    chunks = chunk_sections([section(text)], chunk_size=24, overlap=0)

    assert len(chunks) >= 3
    assert all(len(chunk.content) <= 24 for chunk in chunks)
    assert " ".join(chunk.content for chunk in chunks) == text
    assert all(not chunk.content.startswith(" ") for chunk in chunks)
    assert all(not chunk.content.endswith(" ") for chunk in chunks)


def test_overlap_is_bounded_deterministic_and_keeps_all_source_words() -> None:
    source = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda"

    first_run = chunk_sections([section(source)], chunk_size=28, overlap=10)
    second_run = chunk_sections([section(source)], chunk_size=28, overlap=10)

    assert first_run == second_run
    assert all(len(chunk.content) <= 28 for chunk in first_run)
    assert set(source.split()).issubset(
        {word for chunk in first_run for word in chunk.content.split()}
    )
    assert any(
        set(left.content.split()) & set(right.content.split())
        for left, right in zip(first_run, first_run[1:], strict=False)
    )


@pytest.mark.parametrize(
    ("chunk_size", "overlap"),
    [(0, 0), (10, -1), (10, 10), (10, 11)],
)
def test_invalid_chunk_settings_fail_clearly(chunk_size: int, overlap: int) -> None:
    with pytest.raises(ValueError, match="chunk_size|overlap"):
        chunk_sections([section("content")], chunk_size=chunk_size, overlap=overlap)


def test_empty_sections_do_not_create_empty_chunks() -> None:
    chunks = chunk_sections(
        [section("  \n\n "), section("Useful content")],
        chunk_size=100,
        overlap=10,
    )

    assert [chunk.content for chunk in chunks] == ["Useful content"]
