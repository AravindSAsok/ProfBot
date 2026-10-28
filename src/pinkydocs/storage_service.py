"""Document orchestration shared by the Streamlit entry point."""

from __future__ import annotations

from .config import Settings
from .document_loader import load_document_bytes, load_pasted_text
from .supabase_service import SupabaseService


class StorageService:
    """Validate and index content locally before saving it to private storage."""

    def __init__(self, repository: SupabaseService, settings: Settings):
        self.repository = repository
        self.settings = settings

    def upload(self, user_id: str, filename: str, data: bytes, display_name: str | None = None) -> dict:
        document = load_document_bytes(
            filename,
            data,
            max_upload_bytes=self.settings.max_upload_bytes,
            max_pdf_pages=self.settings.max_pdf_pages,
            max_text_chars=self.settings.max_text_chars,
            display_name=display_name,
        )
        return self.repository.save_document(user_id, document, data)

    def save_pasted_text(self, user_id: str, title: str, text: str) -> dict:
        document = load_pasted_text(title, text, max_text_chars=self.settings.max_text_chars)
        return self.repository.save_document(user_id, document, text.encode("utf-8"))

    def selected_chunks(self, user_id: str, document_ids: list[str]):
        return self.repository.get_owned_chunks(user_id, document_ids)
