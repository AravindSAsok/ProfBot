from __future__ import annotations

import io

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from pinkydocs.document_loader import (
    DocumentError,
    load_document_bytes,
    load_document_path,
    load_pasted_text,
)


def make_text_pdf(*pages: str) -> bytes:
    writer = PdfWriter()
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    font_ref = writer._add_object(font)
    resources = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})
    })
    for text in pages:
        page = writer.add_blank_page(width=250, height=250)
        page[NameObject("/Resources")] = resources
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 40 150 Td ({text}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_load_valid_utf8_txt_and_preserve_lines_and_heading():
    result = load_document_bytes("policy.txt", b"\xef\xbb\xbfAnnual Leave\n18 days.\r\n")
    assert result.source_type == "txt"
    assert result.sections[0].section_title == "Annual Leave"
    assert result.sections[0].line_start == 2
    assert result.sections[0].line_end == 2
    assert "18 days" in result.sections[0].text


def test_empty_txt_and_invalid_utf8_fail_helpfully():
    with pytest.raises(DocumentError, match="empty"):
        load_document_bytes("blank.txt", b"")
    with pytest.raises(DocumentError, match="no text"):
        load_document_bytes("blank.txt", b" \n")
    with pytest.raises(DocumentError, match="UTF-8"):
        load_document_bytes("bad.txt", b"\xff\xfe\xff")


def test_multi_page_pdf_keeps_page_numbers():
    result = load_document_bytes("policy.pdf", make_text_pdf("Annual leave", "Sick leave"))
    assert result.page_count == 2
    assert [section.page_number for section in result.sections] == [1, 2]
    assert result.sections[1].text == "Sick leave"


def test_empty_and_malformed_pdf_are_rejected():
    empty_writer = PdfWriter()
    output = io.BytesIO()
    empty_writer.write(output)
    with pytest.raises(DocumentError, match="no pages"):
        load_document_bytes("empty.pdf", output.getvalue())
    with pytest.raises(DocumentError, match="malformed"):
        load_document_bytes("broken.pdf", b"%PDF-1.4\nnot a pdf")


def test_pdf_without_extractable_text_reports_ocr_limitation():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    output = io.BytesIO()
    writer.write(output)
    with pytest.raises(DocumentError, match="OCR"):
        load_document_bytes("scan.pdf", output.getvalue())


def test_encrypted_pdf_requires_unlocked_copy():
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    font_ref = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    }))
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})
    })
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 40 150 Td (Secret) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.encrypt("password")
    output = io.BytesIO()
    writer.write(output)
    with pytest.raises(DocumentError, match="encrypted"):
        load_document_bytes("locked.pdf", output.getvalue())


def test_rejects_unsupported_file_type_oversize_and_page_limit(tmp_path):
    with pytest.raises(DocumentError, match="Unsupported"):
        load_document_bytes("image.png", b"abc")
    with pytest.raises(DocumentError, match="exceeds"):
        load_document_bytes("a.txt", b"123", max_upload_bytes=2)
    pdf = make_text_pdf("one", "two")
    with pytest.raises(DocumentError, match="limit"):
        load_document_bytes("many.pdf", pdf, max_pdf_pages=1)
    path = tmp_path / "missing.txt"
    with pytest.raises(DocumentError, match="not found"):
        load_document_path(path)


def test_pasted_text_validates_title_and_content():
    pasted = load_pasted_text("Team Notes", "Planning starts Monday.\nOwner: Sam")
    assert pasted.source_type == "pasted"
    assert pasted.filename == "Team Notes.txt"
    assert pasted.display_name == "Team Notes"
    assert pasted.sections[0].line_start == 1
    with pytest.raises(DocumentError, match="title"):
        load_pasted_text(" ", "some content")
    with pytest.raises(DocumentError, match="Paste some text"):
        load_pasted_text("Notes", " \n")
    with pytest.raises(DocumentError, match="character limit"):
        load_pasted_text("Notes", "long text", max_text_chars=3)


def test_user_supplied_path_is_reduced_to_filename():
    result = load_document_bytes("../private/policy.txt", b"Policy text")
    assert result.filename == "policy.txt"
