"""Paragraph-aware chunking with source metadata retained per chunk."""

from __future__ import annotations

import re

from .models import Chunk, ExtractedDocument, TextSection


def _split_at_boundary(text: str, limit: int) -> int:
    """Pick a readable boundary near the hard limit, always making progress."""
    if len(text) <= limit:
        return len(text)
    floor = max(1, int(limit * 0.65))
    candidates = [
        text.rfind("\n", floor, limit + 1),
        text.rfind(". ", floor, limit + 1) + 1,
        text.rfind("? ", floor, limit + 1) + 1,
        text.rfind("! ", floor, limit + 1) + 1,
        text.rfind(" ", floor, limit + 1),
    ]
    boundary = max(candidates)
    return boundary if boundary > 0 else limit


def _section_chunks(section: TextSection, size: int, overlap: int) -> list[tuple[str, int, int]]:
    text = section.text.strip()
    if not text:
        return []
    chunks: list[tuple[str, int, int]] = []
    cursor = 0
    while cursor < len(text):
        end = _split_at_boundary(text[cursor:], size) + cursor
        piece = text[cursor:end].strip()
        if piece:
            chunks.append((piece, cursor, end))
        if end >= len(text):
            break
        next_cursor = max(cursor + 1, end - overlap)
        cursor = next_cursor
    return chunks


def chunk_document(
    document: ExtractedDocument,
    *,
    chunk_size_chars: int = 1200,
    chunk_overlap_chars: int = 180,
) -> list[Chunk]:
    """Split one extracted document while preserving page and line references."""
    if chunk_size_chars <= 0 or chunk_overlap_chars < 0:
        raise ValueError("Chunk size must be positive and overlap must not be negative.")
    if chunk_overlap_chars >= chunk_size_chars:
        raise ValueError("Chunk overlap must be smaller than chunk size.")
    chunks: list[Chunk] = []
    for section in document.sections:
        lines = section.text.splitlines() or [section.text]
        source_line = section.line_start
        for content, start, end in _section_chunks(section, chunk_size_chars, chunk_overlap_chars):
            line_start = line_end = None
            if source_line is not None:
                line_start = source_line + section.text[:start].count("\n")
                line_end = source_line + section.text[: max(start, end - 1)].count("\n")
            indexed_content = f"{section.section_title}\n{content}" if section.section_title else content
            chunks.append(
                Chunk(
                    document_id=document.id,
                    filename=document.display_name or document.filename,
                    source_type=document.source_type,
                    chunk_index=len(chunks),
                    content=indexed_content,
                    page_start=section.page_number,
                    page_end=section.page_number,
                    line_start=line_start,
                    line_end=line_end,
                    section_title=section.section_title,
                )
            )
    return chunks
