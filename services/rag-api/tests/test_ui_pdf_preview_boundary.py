import hashlib
import io

import pytest
from pypdf import PdfWriter
from pypdf._page import PageObject

from app.cm_update.filesystem import parse_document


def pdf_bytes(pages=334, *, encrypted=False):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    if encrypted:
        writer.encrypt('test-only-password')
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_integrated_preview_is_bounded_and_preserves_original(monkeypatch):
    content = pdf_bytes()
    original_hash = hashlib.sha256(content).hexdigest()
    extracted = []

    def extract(page):
        extracted.append(page)
        return 'Preview evidence'

    monkeypatch.setattr(PageObject, 'extract_text', extract)
    mime, parts, error = parse_document('book.pdf', content, pdf_preview_pages=6)
    assert mime == 'application/pdf'
    assert [page for page, _ in parts] == list(range(1, 7))
    assert len(extracted) == 6
    assert error is None
    assert hashlib.sha256(content).hexdigest() == original_hash


def test_standalone_keeps_full_parse_page_limit():
    with pytest.raises(ValueError, match='250'):
        parse_document('book.pdf', pdf_bytes())


def test_integrated_preview_rejects_encrypted_pdf():
    with pytest.raises(ValueError, match='加密'):
        parse_document('book.pdf', pdf_bytes(encrypted=True), pdf_preview_pages=6)


@pytest.mark.parametrize('limit', [0, -1, 251])
def test_preview_limit_cannot_disable_bounds(limit):
    with pytest.raises(ValueError):
        parse_document('book.pdf', pdf_bytes(1), pdf_preview_pages=limit)
