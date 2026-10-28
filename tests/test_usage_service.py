from concurrent.futures import ThreadPoolExecutor
from datetime import date

from pinkydocs.usage_service import InMemoryUsageRepository, UsageError, UsageLimiter


def test_per_user_and_global_daily_limits():
    repository = InMemoryUsageRepository()
    limiter = UsageLimiter(repository)
    today = date(2026, 10, 28)
    limiter.reserve("user-1", 2, 5, day=today)
    limiter.reserve("user-1", 2, 5, day=today)
    try:
        limiter.reserve("user-1", 2, 5, day=today)
    except UsageError as exc:
        assert "daily question limit" in str(exc)
    else:
        raise AssertionError("Per-user quota was exceeded.")

    limiter.reserve("user-2", 2, 3, day=today)
    try:
        limiter.reserve("user-3", 2, 3, day=today)
    except UsageError as exc:
        assert "shared question limit" in str(exc)
    else:
        raise AssertionError("Global quota was exceeded.")


def test_concurrent_reservations_cannot_exceed_per_user_limit():
    repository = InMemoryUsageRepository()
    limiter = UsageLimiter(repository)
    today = date(2026, 10, 28)

    def reserve(_):
        try:
            limiter.reserve("shared-user", 11, 100, day=today)
            return True
        except UsageError:
            return False

    with ThreadPoolExecutor(max_workers=16) as pool:
        outcomes = list(pool.map(reserve, range(60)))
    assert sum(outcomes) == 11
    assert repository.global_counts[today] == 11


def test_usage_service_errors_fail_closed():
    class BrokenRepository:
        def reserve_question(self, *args):
            raise OSError("database down")

    limiter = UsageLimiter(BrokenRepository())
    try:
        limiter.reserve("user", 10, 10)
    except UsageError as exc:
        assert "could not be checked" in str(exc)
    else:
        raise AssertionError("Usage backend failure should fail closed.")


def test_empty_and_no_evidence_requests_never_reserve(settings):
    from pinkydocs.chunker import chunk_document
    from pinkydocs.document_loader import load_pasted_text
    from pinkydocs.qa_service import answer_question

    class Client:
        def generate(self, *args, **kwargs):
            raise AssertionError("Model must not be called.")

    calls = []
    chunks = chunk_document(load_pasted_text("Leave", "Employees receive annual leave."))
    result = answer_question(
        "Where is the moon?",
        chunks,
        client=Client(),
        settings=settings,
        reserve_usage=lambda: calls.append(True),
    )
    assert result.found is False
    assert calls == []
