from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pinkydocs.config import Settings


@pytest.fixture
def settings():
    return Settings(
        gemini_api_key="test-key",
        gemini_model="test-model",
        max_retrieved_chunks=4,
        chunk_size_chars=120,
        chunk_overlap_chars=20,
    )
