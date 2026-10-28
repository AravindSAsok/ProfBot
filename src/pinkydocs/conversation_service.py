"""Small conversation policy helpers around the owner-scoped repository."""

from __future__ import annotations

import re


def conversation_title(first_question: str) -> str:
    """Build a deterministic, readable title without an extra Gemini request."""
    compact = re.sub(r"\s+", " ", first_question).strip()
    if not compact:
        return "New conversation"
    return compact if len(compact) <= 54 else compact[:51].rstrip() + "…"
