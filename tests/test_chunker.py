from pinkydocs.chunker import chunk_document
from pinkydocs.document_loader import load_document_bytes, load_pasted_text
from pinkydocs.models import ExtractedDocument, TextSection


def test_short_document_stays_one_chunk_and_keeps_line_metadata():
    document = load_document_bytes("rules.txt", b"Leave\nEmployees get 18 days.")
    chunks = chunk_document(document, chunk_size_chars=100, chunk_overlap_chars=10)
    assert len(chunks) == 1
    assert chunks[0].section_title == "Leave"
    assert chunks[0].line_start == 2
    assert chunks[0].line_end == 2


def test_long_text_is_chunked_with_overlap_and_progress():
    document = load_pasted_text("Notes", "alpha beta gamma. " * 40)
    chunks = chunk_document(document, chunk_size_chars=100, chunk_overlap_chars=20)
    assert len(chunks) > 3
    assert all(0 < len(chunk.content) <= 100 for chunk in chunks)
    assert any(set(chunks[i].content.split()) & set(chunks[i + 1].content.split()) for i in range(len(chunks) - 1))
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))


def test_page_metadata_is_preserved_for_pdf_chunks():
    doc = ExtractedDocument(
        id="doc-1",
        filename="policy.pdf",
        display_name="policy.pdf",
        source_type="pdf",
        file_size_bytes=10,
        sections=(TextSection("Annual leave is eighteen days.", page_number=7),),
        page_count=7,
    )
    chunks = chunk_document(doc, chunk_size_chars=10, chunk_overlap_chars=2)
    assert chunks
    assert all(chunk.page_start == 7 and chunk.page_end == 7 for chunk in chunks)
    assert chunks[0].source_label() == "policy.pdf — Page 7"


def test_invalid_chunk_settings_fail_without_looping():
    document = load_pasted_text("Notes", "some text")
    try:
        chunk_document(document, chunk_size_chars=10, chunk_overlap_chars=10)
    except ValueError as exc:
        assert "smaller" in str(exc)
    else:
        raise AssertionError("Expected overlapping window validation.")
