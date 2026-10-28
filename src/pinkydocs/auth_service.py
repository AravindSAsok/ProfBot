"""Username/password authentication using Argon2id and a repository boundary."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


class AuthError(ValueError):
    """Safe validation or authentication failure."""


class AuthRepository(Protocol):
    def create_user(self, username: str, password_hash: str) -> dict: ...
    def get_user_by_username(self, username: str) -> dict | None: ...
    def reserve_login_attempt(self, username: str) -> bool: ...
    def clear_login_attempts(self, username: str) -> None: ...


@dataclass(frozen=True)
class UserIdentity:
    id: str
    username: str


class AuthService:
    """Register and authenticate users without ever retaining plaintext passwords."""

    def __init__(self, repository: AuthRepository, hasher: PasswordHasher | None = None):
        self.repository = repository
        self.hasher = hasher or PasswordHasher()

    @staticmethod
    def normalize_username(username: str) -> str:
        normalized = username.strip().casefold()
        if not re.fullmatch(r"[a-z0-9_.-]{3,24}", normalized):
            raise AuthError("Username must be 3–24 characters using letters, numbers, dots, _ or -.")
        return normalized

    @staticmethod
    def _validate_password(password: str) -> None:
        if len(password) < 8:
            raise AuthError("Password must be at least 8 characters long.")
        if len(password) > 128:
            raise AuthError("Password must be 128 characters or fewer.")

    def register(self, username: str, password: str) -> UserIdentity:
        normalized = self.normalize_username(username)
        self._validate_password(password)
        hashed = self.hasher.hash(password)
        try:
            row = self.repository.create_user(normalized, hashed)
        except Exception as exc:
            message = str(exc).casefold()
            if "duplicate" in message or "unique" in message or "23505" in message:
                raise AuthError("That username is already in use.") from exc
            raise AuthError("Registration could not be completed. Please try again.") from exc
        return UserIdentity(id=str(row["id"]), username=normalized)

    def login(self, username: str, password: str) -> UserIdentity:
        normalized = self.normalize_username(username)
        if not password or len(password) > 128:
            raise AuthError("Invalid username or password.")
        if not self.repository.reserve_login_attempt(normalized):
            raise AuthError("Too many login attempts. Please wait a few minutes and try again.")
        row = self.repository.get_user_by_username(normalized)
        valid = False
        if row and isinstance(row.get("password_hash"), str):
            try:
                valid = self.hasher.verify(row["password_hash"], password)
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                valid = False
        if not valid:
            raise AuthError("Invalid username or password.")
        self.repository.clear_login_attempts(normalized)
        return UserIdentity(id=str(row["id"]), username=normalized)


def clear_auth_state(session_state: dict) -> None:
    """Remove authentication and private UI state on logout."""
    for key in (
        "user_id",
        "username",
        "authenticated_at",
        "last_activity",
        "current_conversation_id",
        "selected_document_ids",
        "messages",
        "documents",
        "document_selector",
        "conversation_selector",
        "_selector_conversation",
        "confirm_delete",
        "suggested_question",
    ):
        session_state.pop(key, None)
