from __future__ import annotations

import pytest

from pinkydocs.config import ConfigurationError, load_settings


def test_settings_parse_streamlit_secret_strings_and_ignore_placeholders(monkeypatch):
    for key in (
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "MAX_UPLOAD_MB",
        "MAX_PDF_PAGES",
        "CHUNK_SIZE_CHARS",
        "CHUNK_OVERLAP_CHARS",
        "MAX_QUESTION_CHARS",
    ):
        monkeypatch.delenv(key, raising=False)
    settings = load_settings({
        "GEMINI_API_KEY": "replace_with_your_gemini_api_key",
        "GEMINI_MODEL": "account-model",
        "SUPABASE_URL": "https://project.example",
        "SUPABASE_SERVICE_ROLE_KEY": "server-secret-placeholder",
        "MAX_UPLOAD_MB": "7",
        "MAX_PDF_PAGES": "80",
        "CHUNK_SIZE_CHARS": "900",
        "CHUNK_OVERLAP_CHARS": "120",
        "MAX_QUESTION_CHARS": "2500",
    })
    assert settings.gemini_api_key == ""
    assert settings.gemini_model == "account-model"
    assert settings.max_upload_mb == 7
    assert settings.max_pdf_pages == 80
    assert settings.chunk_size_chars == 900
    assert settings.max_question_chars == 2500


def test_missing_streamlit_secrets_object_does_not_crash(monkeypatch):
    for key in ("GEMINI_API_KEY", "GEMINI_MODEL", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
        monkeypatch.delenv(key, raising=False)

    class NoSecrets:
        def __contains__(self, _key):
            raise RuntimeError("No Streamlit secrets file")

        def __getitem__(self, key):
            raise KeyError(key)

    settings = load_settings(NoSecrets())
    with pytest.raises(ConfigurationError, match="GEMINI_API_KEY"):
        settings.validate_cli()


def test_invalid_numeric_or_chunk_configuration_fails(monkeypatch):
    monkeypatch.delenv("CHUNK_SIZE_CHARS", raising=False)
    monkeypatch.delenv("CHUNK_OVERLAP_CHARS", raising=False)
    with pytest.raises(ConfigurationError, match="integer"):
        load_settings({"MAX_UPLOAD_MB": "ten"})
    with pytest.raises(ConfigurationError, match="smaller"):
        load_settings({"CHUNK_SIZE_CHARS": "100", "CHUNK_OVERLAP_CHARS": "100"})
