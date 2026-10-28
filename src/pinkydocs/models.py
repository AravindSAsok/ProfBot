"""Typed data structures shared by document, retrieval, and answer services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TextSection:
    text: str
    page_number: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    section_title: str | None = None


@dataclass(frozen=True)
class ExtractedDocument:
    id: str
    filename: str
    display_name: str
    source_type: str
    file_size_bytes: int
    sections: tuple[TextSection, ...]
    page_count: int | None = None
    content_hash: str = ""


@dataclass(frozen=True)
class Chunk:
    document_id: str
    filename: str
    source_type: str
    chunk_index: int
    content: str
    page_start: int | None = None
    page_end: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    section_title: str | None = None
    score: float = 0.0

    def source_label(self) -> str:
        if self.page_start is not None:
            if self.page_end and self.page_end != self.page_start:
                return f"{self.filename} — Pages {self.page_start}–{self.page_end}"
            return f"{self.filename} — Page {self.page_start}"
        if self.section_title:
            return f"{self.filename} — {self.section_title}"
        if self.line_start is not None:
            suffix = f"–{self.line_end}" if self.line_end and self.line_end != self.line_start else ""
            return f"{self.filename} — Lines {self.line_start}{suffix}"
        return f"{self.filename} — Chunk {self.chunk_index + 1}"

    def citation(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "source_type": self.source_type,
            "chunk_index": self.chunk_index,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "section_title": self.section_title,
            "label": self.source_label(),
        }


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: Chunk
    score: float


@dataclass(frozen=True)
class QAResult:
    answer: str
    citations: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    evidence: tuple[Chunk, ...] = field(default_factory=tuple)
    found: bool = True

