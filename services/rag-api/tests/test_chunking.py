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


def test_assignment_question_structure_is_split_with_parent_and_part_metadata() -> None:
    source = SourceSection(
        text=(
            "GE2324 Assignment 2\nQuestion 1 [55 marks].\nShared table and instructions.\n"
            "(a) Calculate the first centroid.\n"
            "(b) Repeat the assignment step.\n"
            "(c) Explain why the result converges."
        ),
        locator_type="page",
        locator_value="1",
        section="Page 1",
    )

    chunks = chunk_sections([source], chunk_size=400, overlap=20)

    assert [chunk.metadata.get("question_number") for chunk in chunks] == ["1", "1", "1"]
    assert [chunk.metadata.get("question_part") for chunk in chunks] == ["a", "b", "c"]
    assert len({chunk.parent_key for chunk in chunks}) == 1
    assert all("Shared table and instructions" in chunk.content for chunk in chunks)


def test_tutorial_numbered_questions_receive_question_metadata() -> None:
    source = SourceSection(
        text="Tutorial 1\n1. Compare binary vectors.\n2. Calculate cosine similarity.",
        locator_type="page",
        locator_value="1",
        section="Page 1",
    )

    chunks = chunk_sections([source], chunk_size=200, overlap=10)

    assert [chunk.metadata.get("question_number") for chunk in chunks] == ["1", "2"]
    assert chunks[0].metadata["document_kind"] == "tutorial"
    assert chunks[0].metadata["document_number"] == "1"


def test_document_kind_can_be_derived_from_markdown_heading() -> None:
    source = SourceSection(
        text="Question 2\n(a) Derive the gradient.\n(b) Check the result.",
        locator_type="section",
        locator_value="1",
        section="Assignment 2",
    )

    chunks = chunk_sections([source], chunk_size=200, overlap=10)

    assert [chunk.metadata["document_kind"] for chunk in chunks] == [
        "assignment",
        "assignment",
    ]
    assert [chunk.metadata["document_number"] for chunk in chunks] == ["2", "2"]


def test_real_course_subpart_styles_are_recognized() -> None:
    source = SourceSection(
        text=(
            "CS3481 Assignment 2\nQuestion 1\nShared instructions.\n"
            "(1) Prepare the dataset.\n(2) Train the model.\n"
            "Question 2\nShared table.\na) Calculate the statistic.\nb. Explain it."
        ),
        locator_type="page",
        locator_value="1",
        section="Page 1",
    )

    chunks = chunk_sections([source], chunk_size=300, overlap=10)

    assert [chunk.metadata["question_part"] for chunk in chunks] == ["1", "2", "a", "b"]


def test_tutorial_question_continuation_keeps_previous_parent_across_pages() -> None:
    sections = [
        SourceSection(
            text="Tutorial 1\n2. The cosine similarity is defined as follows.",
            locator_type="page",
            locator_value="1",
            section="Page 1",
        ),
        SourceSection(
            text=(
                "Calculate cosine similarity between article 1 and article 2.\n"
                "3. Apply the inverse document frequency transformation."
            ),
            locator_type="page",
            locator_value="2",
            section="Page 2",
        ),
    ]

    chunks = chunk_sections(sections, chunk_size=300, overlap=10)
    question_two = [
        chunk for chunk in chunks if chunk.metadata.get("question_number") == "2"
    ]

    assert len(question_two) == 2
    assert question_two[1].locator_value == "2"
    assert "Calculate cosine similarity" in question_two[1].content
    assert chunks[-1].metadata["question_number"] == "3"
    assert "Calculate cosine similarity" not in chunks[-1].content


def test_long_question_stem_marks_the_subpart_fragment_as_target() -> None:
    source = SourceSection(
        text=(
            "Assignment 2\nQuestion 1\n"
            + "Shared table data. " * 30
            + "\n(b) Do you get the same result?"
        ),
        locator_type="page",
        locator_value="1",
        section="Page 1",
    )

    chunks = chunk_sections([source], chunk_size=180, overlap=20)
    target = [chunk for chunk in chunks if chunk.metadata.get("fragment_role") == "target"]

    assert target
    assert any("same result" in chunk.content for chunk in target)
    assert any(chunk.metadata.get("fragment_role") == "parent" for chunk in chunks)
