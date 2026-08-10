from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.rag.errors import DocumentLoadError
from app.rag.loaders import load_document

FIXTURES = Path(__file__).parent / "fixtures"


def create_text_pdf(path: Path, text: str) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_reference = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): font_reference}
            )
        }
    )
    stream = DecodedStreamObject()
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as output:
        writer.write(output)


def test_markdown_loader_retains_heading_sections() -> None:
    sections = load_document(FIXTURES / "sample.md")

    assert [item.section for item in sections] == [
        "Lighting Models",
        "Diffuse Term",
        "Specular Term",
    ]
    assert all(item.locator_type == "section" for item in sections)
    assert "surface normal" in sections[1].text


def test_pdf_loader_extracts_real_page_text_and_locator(tmp_path: Path) -> None:
    path = tmp_path / "lighting.pdf"
    create_text_pdf(path, "CourseMate vector lighting")

    sections = load_document(path)

    assert len(sections) == 1
    assert "CourseMate vector lighting" in sections[0].text
    assert sections[0].locator_type == "page"
    assert sections[0].locator_value == "1"


@pytest.mark.parametrize(
    ("filename", "content", "expected_code"),
    [
        ("legacy.ppt", b"not a presentation", "UNSUPPORTED_EXTENSION"),
        ("broken.pdf", b"not a pdf", "CORRUPT_DOCUMENT"),
        ("empty.md", b"  \n\n", "EMPTY_DOCUMENT"),
    ],
)
def test_invalid_documents_return_typed_errors(
    tmp_path: Path,
    filename: str,
    content: bytes,
    expected_code: str,
) -> None:
    path = tmp_path / filename
    path.write_bytes(content)

    with pytest.raises(DocumentLoadError) as error:
        load_document(path)

    assert error.value.code == expected_code


def test_missing_document_returns_typed_error(tmp_path: Path) -> None:
    with pytest.raises(DocumentLoadError) as error:
        load_document(tmp_path / "missing.md")

    assert error.value.code == "FILE_NOT_FOUND"
