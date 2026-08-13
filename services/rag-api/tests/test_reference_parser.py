from app.tutor.references import DocumentKind, parse_query_reference


def test_parses_real_ge2324_assignment_filename_question_and_subpart() -> None:
    reference = parse_query_reference("教我 assignment_2.pdf 的 Question 1(c)")

    assert reference.document == "assignment_2.pdf"
    assert reference.document_kind is DocumentKind.ASSIGNMENT
    assert reference.document_number == "2"
    assert reference.question_number == "1"
    assert reference.question_part == "c"


def test_parses_real_cs3481_assignment_filename_and_chinese_question() -> None:
    reference = parse_query_reference("CS_3481_Assignment_2.pdf 第 2 题怎么做？")

    assert reference.document == "CS_3481_Assignment_2.pdf"
    assert reference.document_number == "2"
    assert reference.question_number == "2"
    assert reference.page_number is None


def test_parses_tutorial_reference_without_explicit_extension() -> None:
    reference = parse_query_reference("Tutorial 1 Question 2")

    assert reference.document is None
    assert reference.document_kind is DocumentKind.TUTORIAL
    assert reference.document_number == "1"
    assert reference.question_number == "2"


def test_parses_real_ge2324_tutorial_name_and_locator() -> None:
    reference = parse_query_reference("GE2324_Tut07.docx Q1")

    assert reference.document == "GE2324_Tut07.docx"
    assert reference.document_kind is DocumentKind.TUTORIAL
    assert reference.document_number == "7"
    assert reference.question_number == "1"


def test_parses_page_slide_and_does_not_invent_missing_question() -> None:
    page = parse_query_reference("On page 2 of assignment_2.pdf")
    slide = parse_query_reference("lecture 3 slide 12")

    assert page.page_number == 2
    assert page.question_number is None
    assert slide.document_kind is DocumentKind.LECTURE
    assert slide.document_number == "3"
    assert slide.slide_number == 12
