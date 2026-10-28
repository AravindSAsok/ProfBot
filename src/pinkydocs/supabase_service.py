"""Server-side Supabase gateway. Every private query is scoped to an owner."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

from supabase import Client, create_client
from supabase.lib.client_options import SyncClientOptions

from .chunker import chunk_document
from .config import Settings
from .conversation_service import conversation_title
from .models import Chunk, ExtractedDocument

logger = logging.getLogger(__name__)
_GLOBAL_USAGE_ID = "00000000-0000-0000-0000-000000000000"


class SupabaseService:
    """Repository for auth, private files, chunks, conversations, and quotas."""

    def __init__(self, client: Client, settings: Settings):
        self.client = client
        self.settings = settings
        self.bucket = settings.supabase_bucket_name

    @classmethod
    def from_settings(cls, settings: Settings) -> "SupabaseService":
        if not settings.supabase_configured:
            raise ValueError("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY to use the web application.")
        options = SyncClientOptions(
            postgrest_client_timeout=settings.request_timeout_seconds,
            storage_client_timeout=settings.request_timeout_seconds,
            function_client_timeout=settings.request_timeout_seconds,
        )
        return cls(
            create_client(settings.supabase_url, settings.supabase_service_role_key, options=options),
            settings,
        )

    # Authentication repository methods.
    def create_user(self, username: str, password_hash: str) -> dict:
        response = self.client.table("app_users").insert(
            {"username": username, "password_hash": password_hash}
        ).execute()
        return response.data[0]

    def get_user_by_username(self, username: str) -> dict | None:
        response = self.client.table("app_users").select("id,username,password_hash").eq(
            "username", username
        ).limit(1).execute()
        return response.data[0] if response.data else None

    def reserve_login_attempt(self, username: str) -> bool:
        response = self.client.rpc(
            "reserve_login_attempt",
            {"p_username": username},
        ).execute()
        return bool(response.data)

    def clear_login_attempts(self, username: str) -> None:
        self.client.rpc("clear_login_attempts", {"p_username": username}).execute()

    # Usage repository method. The function uses transaction-scoped DB locks.
    def reserve_question(
        self, user_id: str, day: date, per_user_limit: int, global_limit: int
    ) -> None:
        self.client.rpc(
            "reserve_question",
            {
                "p_user_id": user_id,
                "p_day": day.isoformat(),
                "p_user_limit": per_user_limit,
                "p_global_limit": global_limit,
            },
        ).execute()

    def list_documents(self, user_id: str) -> list[dict]:
        response = self.client.table("documents").select(
            "id,original_filename,display_name,file_type,file_size_bytes,page_count,created_at"
        ).eq("user_id", user_id).order("created_at", desc=True).execute()
        return response.data or []

    def save_document(self, user_id: str, document: ExtractedDocument, raw: bytes) -> dict:
        """Upload to a private generated path, then persist metadata and chunks."""
        doc_id = str(uuid.uuid4())
        suffix = ".pdf" if document.source_type == "pdf" else ".txt"
        storage_path = f"{user_id}/{doc_id}/original{suffix}"
        content_type = "application/pdf" if suffix == ".pdf" else "text/plain; charset=utf-8"
        try:
            self.client.storage.from_(self.bucket).upload(
                storage_path,
                raw,
                file_options={"content-type": content_type, "upsert": "false"},
            )
            row = {
                "id": doc_id,
                "user_id": user_id,
                "original_filename": Path(document.filename).name,
                "display_name": document.display_name,
                "file_type": document.source_type,
                "file_size_bytes": document.file_size_bytes,
                "storage_path": storage_path,
                "content_hash": document.content_hash,
                "page_count": document.page_count,
            }
            self.client.table("documents").insert(row).execute()
            rows = []
            for chunk in chunk_document(
                document,
                chunk_size_chars=self.settings.chunk_size_chars,
                chunk_overlap_chars=self.settings.chunk_overlap_chars,
            ):
                rows.append(
                    {
                        "document_id": doc_id,
                        "user_id": user_id,
                        "chunk_index": chunk.chunk_index,
                        "content": chunk.content,
                        "page_start": chunk.page_start,
                        "page_end": chunk.page_end,
                        "line_start": chunk.line_start,
                        "line_end": chunk.line_end,
                        "section_title": chunk.section_title,
                    }
                )
            if rows:
                self.client.table("document_chunks").insert(rows).execute()
            return row
        except Exception as exc:
            logger.warning("Document save failed (%s).", type(exc).__name__)
            try:
                # Safe even when the insert response was lost after a successful commit.
                self.client.table("documents").delete().eq("id", doc_id).eq("user_id", user_id).execute()
            except Exception:
                logger.error("Could not roll back failed document metadata.")
            try:
                # Safe even if the storage upload timed out after the object was accepted.
                self.client.storage.from_(self.bucket).remove([storage_path])
            except Exception:
                logger.error("Could not roll back failed document storage upload.")
            raise RuntimeError("Document could not be saved. Please try again.") from exc

    def get_owned_chunks(self, user_id: str, document_ids: Iterable[str]) -> list[Chunk]:
        ids = list(dict.fromkeys(str(item) for item in document_ids))
        if not ids:
            return []
        documents = self.client.table("documents").select(
            "id,display_name,original_filename,file_type"
        ).eq("user_id", user_id).in_("id", ids).execute().data or []
        owned = {str(row["id"]): row for row in documents}
        if len(owned) != len(ids):
            raise PermissionError("One or more selected documents are unavailable.")
        rows = self.client.table("document_chunks").select(
            "document_id,chunk_index,content,page_start,page_end,line_start,line_end,section_title"
        ).eq("user_id", user_id).in_("document_id", ids).order("chunk_index").execute().data or []
        return [
            Chunk(
                document_id=str(row["document_id"]),
                filename=owned[str(row["document_id"])]["display_name"],
                source_type=owned[str(row["document_id"])]["file_type"],
                chunk_index=int(row["chunk_index"]),
                content=row["content"],
                page_start=row.get("page_start"),
                page_end=row.get("page_end"),
                line_start=row.get("line_start"),
                line_end=row.get("line_end"),
                section_title=row.get("section_title"),
            )
            for row in rows
        ]

    def delete_document(self, user_id: str, document_id: str) -> None:
        row = self.client.table("documents").select("id,storage_path").eq(
            "id", document_id
        ).eq("user_id", user_id).limit(1).execute().data
        if not row:
            raise PermissionError("Document is unavailable.")
        storage_path = row[0]["storage_path"]
        try:
            self.client.storage.from_(self.bucket).remove([storage_path])
        except Exception as exc:
            raise RuntimeError("The private file could not be deleted. Please retry.") from exc
        self.client.table("documents").delete().eq("id", document_id).eq("user_id", user_id).execute()

    # Conversation methods always validate ownership before touching associations/messages.
    def list_conversations(self, user_id: str) -> list[dict]:
        return self.client.table("conversations").select(
            "id,title,created_at,updated_at"
        ).eq("user_id", user_id).order("updated_at", desc=True).execute().data or []

    def create_conversation(self, user_id: str, title: str, document_ids: list[str]) -> dict:
        self._validate_document_ownership(user_id, document_ids)
        row = self.client.table("conversations").insert(
            {"user_id": user_id, "title": title[:100]}
        ).execute().data[0]
        self.set_conversation_documents(user_id, row["id"], document_ids)
        return row

    def _owned_conversation(self, user_id: str, conversation_id: str) -> dict:
        rows = self.client.table("conversations").select("id,title").eq(
            "user_id", user_id
        ).eq("id", conversation_id).limit(1).execute().data or []
        if not rows:
            raise PermissionError("Conversation is unavailable.")
        return rows[0]

    def _validate_document_ownership(self, user_id: str, document_ids: list[str]) -> None:
        ids = list(dict.fromkeys(str(item) for item in document_ids))
        if not ids:
            return
        rows = self.client.table("documents").select("id").eq("user_id", user_id).in_(
            "id", ids
        ).execute().data or []
        if {str(row["id"]) for row in rows} != set(ids):
            raise PermissionError("One or more selected documents are unavailable.")

    def set_conversation_documents(
        self, user_id: str, conversation_id: str, document_ids: list[str]
    ) -> None:
        self._owned_conversation(user_id, conversation_id)
        ids = list(dict.fromkeys(str(item) for item in document_ids))
        self._validate_document_ownership(user_id, ids)
        self.client.table("conversation_documents").delete().eq(
            "user_id", user_id
        ).eq("conversation_id", conversation_id).execute()
        if ids:
            self.client.table("conversation_documents").insert(
                [
                    {"user_id": user_id, "conversation_id": conversation_id, "document_id": item}
                    for item in ids
                ]
            ).execute()

    def get_conversation_documents(self, user_id: str, conversation_id: str) -> list[str]:
        self._owned_conversation(user_id, conversation_id)
        rows = self.client.table("conversation_documents").select(
            "document_id"
        ).eq("user_id", user_id).eq("conversation_id", conversation_id).execute().data or []
        ids = [str(row["document_id"]) for row in rows]
        self._validate_document_ownership(user_id, ids)
        return ids

    def get_messages(self, user_id: str, conversation_id: str) -> list[dict]:
        self._owned_conversation(user_id, conversation_id)
        return self.client.table("messages").select(
            "id,role,content,citations,created_at"
        ).eq("user_id", user_id).eq("conversation_id", conversation_id).order(
            "created_at"
        ).execute().data or []

    def add_message(
        self, user_id: str, conversation_id: str, role: str, content: str, citations: list[dict] | None = None
    ) -> dict:
        if role not in {"user", "assistant"}:
            raise ValueError("Invalid message role.")
        self._owned_conversation(user_id, conversation_id)
        row = self.client.table("messages").insert(
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "role": role,
                "content": content,
                "citations": citations or [],
            }
        ).execute().data[0]
        update = {"updated_at": datetime.now(timezone.utc).isoformat()}
        if role == "user":
            conversation = self._owned_conversation(user_id, conversation_id)
            if conversation["title"] == "New conversation":
                update["title"] = conversation_title(content)
        self.client.table("conversations").update(update).eq(
            "id", conversation_id
        ).eq("user_id", user_id).execute()
        return row
