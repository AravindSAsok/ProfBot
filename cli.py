"""Terminal entry point for PinkyDocs AI; requires no Supabase account."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from pinkydocs.chunker import chunk_document
from pinkydocs.config import ConfigurationError, load_settings
from pinkydocs.document_loader import DocumentError, load_document_path, load_pasted_text
from pinkydocs.gemini_client import GeminiClient, GeminiError
from pinkydocs.qa_service import answer_question


def _load_input(settings):
    print("\nChoose an input:\n1. PDF file\n2. TXT file\n3. Paste text")
    choice = input("Enter your choice: ").strip()
    if choice in {"1", "2"}:
        path = input("Enter file path: ").strip().strip('"')
        return load_document_path(
            path,
            max_upload_bytes=settings.max_upload_bytes,
            max_pdf_pages=settings.max_pdf_pages,
            max_text_chars=settings.max_text_chars,
        )
    if choice == "3":
        title = input("Document title: ").strip()
        print("Paste text. Enter a line containing END when finished.")
        lines = []
        while True:
            line = input()
            if line.strip() == "END":
                break
            lines.append(line)
        return load_pasted_text(title, "\n".join(lines), max_text_chars=settings.max_text_chars)
    raise DocumentError("Choose 1, 2, or 3.")


def main() -> int:
    print("PinkyDocs AI - Document Q&A")
    try:
        settings = load_settings()
        settings.validate_cli()
        document = _load_input(settings)
        chunks = chunk_document(
            document,
            chunk_size_chars=settings.chunk_size_chars,
            chunk_overlap_chars=settings.chunk_overlap_chars,
        )
        client = GeminiClient(settings)
    except (ConfigurationError, DocumentError, GeminiError) as exc:
        print(f"\nUnable to start: {exc}")
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nGoodbye!")
        return 0

    print(f"\nDocument loaded: {document.display_name}")
    print(f"Indexed {len(chunks)} text chunk(s).")
    print("\nAsk a question, or type 'exit' to quit.")
    history: list[dict[str, str]] = []
    while True:
        try:
            question = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            return 0
        if question.casefold() in {"exit", "quit"}:
            print("Goodbye!")
            return 0
        if not question:
            print("Enter a question first.")
            continue
        try:
            result = answer_question(question, chunks, client=client, settings=settings, history=history)
        except GeminiError as exc:
            print(f"\nAssistant: {exc}")
            continue
        except ValueError as exc:
            print(f"\n{exc}")
            continue
        print(f"\nAssistant:\n{result.answer}")
        if result.citations:
            print("\nSources:")
            for citation in result.citations:
                label = citation["label"].replace("—", " - ").replace("–", "-")
                print(f"- {label}")
        history.extend(({"role": "user", "content": question}, {"role": "assistant", "content": result.answer}))
        history = history[-settings.max_chat_history_pairs * 2 :]


if __name__ == "__main__":
    raise SystemExit(main())
