"""Atomic usage allowance reservation immediately before a Gemini call."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from threading import Lock
from typing import Protocol


class UsageError(RuntimeError):
    """A daily question allowance or usage service failed."""


class UsageRepository(Protocol):
    def reserve_question(self, user_id: str, day: date, per_user_limit: int, global_limit: int) -> None: ...


class UsageLimiter:
    """Thin policy wrapper; the repository must reserve counters atomically."""

    def __init__(self, repository: UsageRepository):
        self.repository = repository

    def reserve(self, user_id: str, per_user_limit: int, global_limit: int, *, day: date | None = None) -> None:
        if not user_id:
            raise UsageError("Sign in before asking a question.")
        try:
            self.repository.reserve_question(
                user_id,
                day or date.today(),
                per_user_limit,
                global_limit,
            )
        except Exception as exc:
            message = str(exc).casefold()
            if "user_daily_limit" in message or "daily question limit" in message:
                raise UsageError("Your daily question limit has been reached. Try again tomorrow.") from exc
            if "global_daily_limit" in message or "shared question limit" in message:
                raise UsageError("Today's shared question limit has been reached. Please try again tomorrow.") from exc
            raise UsageError("Usage limits could not be checked. Please try again later.") from exc


@dataclass
class InMemoryUsageRepository:
    """Thread-safe test/local repository; production quotas use a Supabase RPC."""
    counts: dict[tuple[date, str], int]
    global_counts: dict[date, int]
    lock: Lock

    def __init__(self):
        self.counts = {}
        self.global_counts = {}
        self.lock = Lock()

    def reserve_question(self, user_id: str, day: date, per_user_limit: int, global_limit: int) -> None:
        with self.lock:
            user_key = (day, user_id)
            user_count = self.counts.get(user_key, 0)
            global_count = self.global_counts.get(day, 0)
            if user_count >= per_user_limit:
                raise UsageError("USER_DAILY_LIMIT")
            if global_count >= global_limit:
                raise UsageError("GLOBAL_DAILY_LIMIT")
            self.counts[user_key] = user_count + 1
            self.global_counts[day] = global_count + 1
