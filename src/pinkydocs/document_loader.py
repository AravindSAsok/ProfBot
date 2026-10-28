"""Safe local extraction for PDF, TXT, and pasted text."""

from __future__ import annotations

import hashlib
import io
import re
import uuid
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .models import ExtractedDocument, TextSection


class DocumentError(ValueError):
    """A user-correctable document loading or validation problem."""


def _make_document(
    filename: str,
    display_name: str,
    source_type: str,
    raw: bytes,
    sections: tuple[TextSection, ...],
    page_count: int | None = None,
    document_id: str | None = None,
) -> ExtractedDocument:
    return ExtractedDocument(
        id=document_id or str(uuid.uuid4()),
        filename=filename,
        display_name=display_name,
        source_type=source_type,
        file_size_bytes=len(raw),
        sections=sections,
        page_count=page_count,
        content_hash=hashlib.sha256(raw).hexdigest(),
    )


def _txt_sections(text: str) -> tuple[TextSection, ...]:
    lines = text.splitlines()
    heading: str | None = None
    current: list[tuple[int, str]] = []
    sections: list[TextSection] = []

    def flush() -> None:
        if current:
            sections.append(
                TextSection(
                    text="\n".join(line for _, line in current).strip(),
                    line_start=current[0][0],
                    line_end=current[-1][0],
                    section_title=heading,
                )
            )
            current.clear()

    for number, line in enumerate(lines, 1):
        clean = line.strip()
        next_line = lines[number].strip() if number < len(lines) else ""
        is_heading = bool(clean) and len(clean) < 100 and (
            clean.startswith("#")
            or (clean.isupper() and any(char.isalpha() for char in clean))
            or (clean.endswith(":") and len(clean.split()) <= 8)
            or (
                bool(next_line)
                and len(clean.split()) <= 6
                and clean.istitle()
                and not clean.endswith((".", "?", "!", ",", ";"))
            )
        )
        if is_heading:
            flush()
            heading = clean.lstrip("#").strip().rstrip(":") or None
            continue
        if clean:
            current.append((number, line))
        elif current:
            current.append((number, ""))
    flush()
    if not sections and text.strip():
        sections.append(TextSection(text=text.strip(), line_start=1, line_end=max(1, len(lines))))
    return tuple(sections)


def load_document_bytes(
    filename: str,
    data: bytes,
    *,
    max_upload_bytes: int = 10 * 1024 * 1024,
    max_pdf_pages: int = 200,
    max_text_chars: int = 200_000,
    display_name: str | None = None,
    document_id: str | None = None,
) -> ExtractedDocument:
    """Extract an uploaded PDF or TXT byte buffer without trusting its filename."""
    safe_name = Path(filename.replace("\\", "/")).name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in {".pdf", ".txt"}:
        raise DocumentError("Unsupported file type. Choose a PDF or TXT file.")
    if not data:
        raise DocumentError("The selected file is empty.")
    if len(data) > max_upload_bytes:
        raise DocumentError(f"File exceeds the {max_upload_bytes // (1024 * 1024)} MB upload limit.")
    title = display_name or safe_name

    if suffix == ".txt":
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentError("This TXT file is not valid UTF-8 text.") from exc
        if not text.strip():
            raise DocumentError("The TXT file contains no text.")
        if len(text) > max_text_chars:
            raise DocumentError(f"Extracted text exceeds the {max_text_chars:,}-character limit.")
        return _make_document(safe_name, title, "txt", data, _txt_sections(text), document_id=document_id)

    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            try:
                unlocked = reader.decrypt("")
            except Exception:
                unlocked = 0
            if not unlocked:
                raise DocumentError("This PDF is encrypted. Upload an unlocked copy.")
        count = len(reader.pages)
        if count == 0:
            raise DocumentError("The PDF has no pages.")
        if count > max_pdf_pages:
            raise DocumentError(f"The PDF has {count} pages; the limit is {max_pdf_pages}.")
        pages: list[TextSection] = []
        total_chars = 0
        for index, page in enumerate(reader.pages, 1):
            text = (page.extract_text() or "").strip()
            total_chars += len(text)
            if text:
                pages.append(TextSection(text=text, page_number=index))
        if not pages:
            raise DocumentError("No text could be extracted. This may be a scanned PDF; OCR is not supported.")
        if total_chars > max_text_chars:
            raise DocumentError(f"Extracted text exceeds the {max_text_chars:,}-character limit.")
        return _make_document(safe_name, title, "pdf", data, tuple(pages), count, document_id)
    except DocumentError:
        raise
    except (PdfReadError, OSError, ValueError, TypeError, KeyError) as exc:
        raise DocumentError("The PDF appears to be malformed or could not be read.") from exc
    except Exception as exc:
        raise DocumentError("The PDF could not be read. Please try a repaired copy.") from exc


def load_document_path(
    path: str | Path,
    *,
    max_upload_bytes: int = 10 * 1024 * 1024,
    max_pdf_pages: int = 200,
    max_text_chars: int = 200_000,
) -> ExtractedDocument:
    """Load a local file path for the CLI, enforcing size before reading it."""
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        raise DocumentError("File not found. Check the path and try again.")
    try:
        if file_path.stat().st_size > max_upload_bytes:
            raise DocumentError(f"File exceeds the {max_upload_bytes // (1024 * 1024)} MB upload limit.")
        return load_document_bytes(
            file_path.name,
            file_path.read_bytes(),
            max_upload_bytes=max_upload_bytes,
            max_pdf_pages=max_pdf_pages,
            max_text_chars=max_text_chars,
        )
    except DocumentError:
        raise
    except OSError as exc:
        raise DocumentError("The file could not be opened. Check its path and permissions.") from exc


def load_pasted_text(
    title: str,
    text: str,
    *,
    max_text_chars: int = 200_000,
    document_id: str | None = None,
) -> ExtractedDocument:
    """Validate pasted text and preserve its supplied display title."""
    normalized_title = re.sub(r"\s+", " ", title).strip()
    if not normalized_title:
        raise DocumentError("Enter a title for the pasted document.")
    if not text.strip():
        raise DocumentError("Paste some text before saving the document.")
    if len(text) > max_text_chars:
        raise DocumentError(f"Pasted text exceeds the {max_text_chars:,}-character limit.")
    raw = text.encode("utf-8")
    return _make_document(
        normalized_title + ".txt",
        normalized_title,
        "pasted",
        raw,
        _txt_sections(text),
        document_id=document_id,
    )
