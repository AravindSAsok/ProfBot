"""Centralized configuration for the CLI and Streamlit application."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Any

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = ""
    gemini_model: str = ""
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_bucket_name: str = "documents"
    max_upload_mb: int = 10
    max_pdf_pages: int = 200
    max_questions_per_user_per_day: int = 15
    max_questions_global_per_day: int = 100
    max_retrieved_chunks: int = 6
    chunk_size_chars: int = 1200
    chunk_overlap_chars: int = 180
    max_chat_history_pairs: int = 4
    session_timeout_minutes: int = 60
    max_session_lifetime_hours: int = 12
    max_text_chars: int = 200_000
    max_question_chars: int = 4_000
    request_timeout_seconds: int = 35
    max_answer_tokens: int = 700

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key and self.gemini_model)

    def validate_cli(self) -> None:
        missing = []
        if not self.gemini_api_key:
            missing.append("GEMINI_API_KEY")
        if not self.gemini_model:
            missing.append("GEMINI_MODEL")
        if missing:
            raise ConfigurationError(
                "Set " + " and ".join(missing) + " in your environment or .env file."
            )

    def validate_web(self) -> None:
        missing = []
        if not self.supabase_url:
            missing.append("SUPABASE_URL")
        if not self.supabase_service_role_key:
            missing.append("SUPABASE_SERVICE_ROLE_KEY")
        if not self.gemini_api_key:
            missing.append("GEMINI_API_KEY")
        if not self.gemini_model:
            missing.append("GEMINI_MODEL")
        if missing:
            raise ConfigurationError("Missing configuration: " + ", ".join(missing))


class ConfigurationError(ValueError):
    """Raised when a required configuration value is absent or invalid."""


_INTEGER_DEFAULTS = {
    "MAX_UPLOAD_MB": 10,
    "MAX_PDF_PAGES": 200,
    "MAX_QUESTIONS_PER_USER_PER_DAY": 15,
    "MAX_QUESTIONS_GLOBAL_PER_DAY": 100,
    "MAX_RETRIEVED_CHUNKS": 6,
    "CHUNK_SIZE_CHARS": 1200,
    "CHUNK_OVERLAP_CHARS": 180,
    "MAX_CHAT_HISTORY_PAIRS": 4,
    "SESSION_TIMEOUT_MINUTES": 60,
    "MAX_SESSION_LIFETIME_HOURS": 12,
    "MAX_TEXT_CHARS": 200_000,
    "MAX_QUESTION_CHARS": 4_000,
    "REQUEST_TIMEOUT_SECONDS": 35,
    "MAX_ANSWER_TOKENS": 700,
}


def load_settings(secrets: Mapping[str, Any] | None = None) -> Settings:
    """Load environment and optional Streamlit secrets; environment wins."""
    load_dotenv(Path.cwd() / ".env", override=False)
    source = secrets

    def value(key: str, default: str = "") -> str:
        current = os.getenv(key)
        if current is None and source is not None:
            try:
                if key in source:
                    current = str(source[key])
            except Exception:
                # Streamlit raises StreamlitSecretNotFoundError when no secrets file exists.
                current = None
        current = (current or "").strip()
        if current.startswith("replace_with_"):
            return default
        return current or default

    parsed: dict[str, int] = {}
    for key, default in _INTEGER_DEFAULTS.items():
        raw = value(key, str(default))
        try:
            number = int(raw)
        except ValueError as exc:
            raise ConfigurationError(f"{key} must be an integer.") from exc
        if number <= 0:
            raise ConfigurationError(f"{key} must be greater than zero.")
        parsed[key.lower()] = number
    overlap = parsed["chunk_overlap_chars"]
    if overlap >= parsed["chunk_size_chars"]:
        raise ConfigurationError("CHUNK_OVERLAP_CHARS must be smaller than CHUNK_SIZE_CHARS.")
    return Settings(
        gemini_api_key=value("GEMINI_API_KEY"),
        gemini_model=value("GEMINI_MODEL"),
        supabase_url=value("SUPABASE_URL"),
        supabase_service_role_key=value("SUPABASE_SERVICE_ROLE_KEY"),
        supabase_bucket_name=value("SUPABASE_BUCKET_NAME", "documents"),
        **parsed,
    )
