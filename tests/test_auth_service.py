from __future__ import annotations

from argon2 import PasswordHasher

from pinkydocs.auth_service import AuthError, AuthService, clear_auth_state


class MemoryAuthRepository:
    def __init__(self):
        self.users = {}
        self.attempts = {}

    def create_user(self, username, password_hash):
        if username in self.users:
            raise RuntimeError("duplicate key value violates unique constraint")
        row = {"id": f"id-{username}", "username": username, "password_hash": password_hash}
        self.users[username] = row
        return row

    def get_user_by_username(self, username):
        return self.users.get(username)

    def reserve_login_attempt(self, username):
        count = self.attempts.get(username, 0)
        if count >= 5:
            return False
        self.attempts[username] = count + 1
        return True

    def clear_login_attempts(self, username):
        self.attempts.pop(username, None)


def service():
    return AuthService(MemoryAuthRepository(), PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))


def test_register_hashes_password_and_normalizes_username():
    auth = service()
    identity = auth.register(" Example.User ", "a long password")
    row = auth.repository.users["example.user"]
    assert identity.username == "example.user"
    assert row["password_hash"] != "a long password"
    assert row["password_hash"].startswith("$argon2id$")
    assert auth.login("EXAMPLE.USER", "a long password") == identity


def test_duplicate_username_is_case_insensitive_and_wrong_password_is_generic():
    auth = service()
    auth.register("A.User", "password 123")
    try:
        auth.register("a.user", "password 456")
    except AuthError as exc:
        assert "already in use" in str(exc)
    else:
        raise AssertionError("Expected duplicate username rejection.")
    try:
        auth.login("A.USER", "wrong password")
    except AuthError as exc:
        assert str(exc) == "Invalid username or password."
    else:
        raise AssertionError("Expected wrong password rejection.")


def test_username_and_password_validation():
    auth = service()
    for username in ("ab", "not valid", "åbc"):
        try:
            auth.register(username, "long enough password")
        except AuthError:
            pass
        else:
            raise AssertionError(f"Invalid username accepted: {username}")
    for password in ("short", "x" * 129):
        try:
            auth.register("valid_user", password)
        except AuthError:
            pass
        else:
            raise AssertionError("Invalid password accepted.")


def test_login_rate_limiter_and_logout_clear_sensitive_state():
    auth = service()
    auth.register("demo_user", "correct horse battery")
    for _ in range(5):
        try:
            auth.login("demo_user", "incorrect password")
        except AuthError:
            pass
    try:
        auth.login("demo_user", "correct horse battery")
    except AuthError as exc:
        assert "Too many" in str(exc)
    else:
        raise AssertionError("Rate limit was not enforced.")
    state = {
        "user_id": "1",
        "username": "demo_user",
        "messages": ["private"],
        "document_selector": ["doc"],
        "some_unrelated_setting": True,
    }
    clear_auth_state(state)
    assert state == {"some_unrelated_setting": True}
