"""Small, bounded Gemini API adapter with safe user-facing error messages."""

from __future__ import annotations

import logging
import time
from typing import Callable

from google import genai
from google.genai import types

from .config import Settings

logger = logging.getLogger(__name__)


class GeminiError(RuntimeError):
    """Safe application-level Gemini failure."""


class GeminiAuthenticationError(GeminiError):
    pass


class GeminiQuotaError(GeminiError):
    pass


class GeminiTransientError(GeminiError):
    pass


class GeminiResponseError(GeminiError):
    pass


def _classify_error(exc: Exception) -> GeminiError:
    message = str(exc).casefold()
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status in (401, 403) or any(value in message for value in ("api key", "unauthorized", "permission_denied")):
        return GeminiAuthenticationError("Gemini rejected the configured API key or model access.")
    if status == 429 or any(value in message for value in ("resource_exhausted", "quota", "rate limit", "429")):
        return GeminiQuotaError("The Gemini free-tier quota or rate limit has been reached. Try again later.")
    exception_name = type(exc).__name__.casefold()
    if status in (408, 500, 502, 503, 504) or any(
        value in message
        for value in ("timeout", "timed out", "temporarily unavailable", "connection", "network")
    ) or any(value in exception_name for value in ("timeout", "connecterror", "networkerror")):
        return GeminiTransientError("Gemini is temporarily unavailable. Please try again shortly.")
    return GeminiError("Gemini could not answer this question. Check the model setting and try again.")


class GeminiClient:
    """Calls one configured text-generation model, retrying transient failures once."""

    def __init__(self, settings: Settings, client=None, sleep: Callable[[float], None] = time.sleep):
        if not settings.gemini_api_key or not settings.gemini_model:
            raise GeminiError("Set GEMINI_API_KEY and GEMINI_MODEL before asking a question.")
        self.model = settings.gemini_model
        self._client = client or genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(timeout=settings.request_timeout_seconds * 1000),
        )
        self._sleep = sleep

    def generate(self, prompt: str, *, system_instruction: str, max_output_tokens: int) -> str:
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=max_output_tokens,
            temperature=0.1,
        )
        for attempt in range(2):
            try:
                response = self._client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=config,
                )
                text = getattr(response, "text", None)
                if not isinstance(text, str) or not text.strip():
                    raise GeminiResponseError("Gemini returned an empty response. Please try again.")
                return text.strip()
            except GeminiResponseError:
                raise
            except Exception as exc:
                classified = _classify_error(exc)
                logger.warning("Gemini request failed (%s).", type(exc).__name__)
                if isinstance(classified, GeminiTransientError) and attempt == 0:
                    self._sleep(0.5)
                    continue
                raise classified from exc
        raise GeminiTransientError("Gemini is temporarily unavailable. Please try again shortly.")
