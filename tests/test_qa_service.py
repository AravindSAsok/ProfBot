from dataclasses import replace

from pinkydocs.chunker import chunk_document
from pinkydocs.document_loader import load_pasted_text
from pinkydocs.gemini_client import GeminiAuthenticationError, GeminiClient, GeminiQuotaError, GeminiTransientError
from pinkydocs.qa_service import NOT_FOUND_ANSWER, answer_question


class FakeGemini:
    def __init__(self, response="The policy says 18 days. Sources: [S1]"):
        self.response = response
        self.calls = []

    def generate(self, prompt, *, system_instruction, max_output_tokens):
        self.calls.append((prompt, system_instruction, max_output_tokens))
        return self.response


def test_returns_trusted_citations_and_only_sends_retrieved_evidence(settings):
    source = load_pasted_text("Leave Policy", "Employees receive 18 annual leave days.")
    unrelated = load_pasted_text("Travel Guide", "The airport shuttle leaves every hour.")
    chunks = chunk_document(source) + chunk_document(unrelated)
    client = FakeGemini("Employees receive 18 days. [S1]\nSources: [S1], [S99]")
    result = answer_question("How many annual leave days?", chunks, client=client, settings=settings)
    assert result.answer == "Employees receive 18 days."
    assert [item["label"] for item in result.citations] == ["Leave Policy — Lines 1"]
    prompt = client.calls[0][0]
    assert "Employees receive 18 annual leave days" in prompt
    assert "airport shuttle" not in prompt
    assert "untrusted data" in client.calls[0][1]


def test_no_retrieved_evidence_skips_gemini_and_usage_reservation(settings):
    client = FakeGemini()
    reserved = []
    chunks = chunk_document(load_pasted_text("Leave Policy", "Employees receive annual leave."))
    result = answer_question(
        "Explain quantum astronomy", chunks, client=client, settings=settings,
        reserve_usage=lambda: reserved.append(True),
    )
    assert result.answer == NOT_FOUND_ANSWER
    assert result.found is False
    assert client.calls == []
    assert reserved == []


def test_empty_question_is_rejected_before_usage_or_model(settings):
    client = FakeGemini()
    reserved = []
    try:
        answer_question("  ", [], client=client, settings=settings, reserve_usage=lambda: reserved.append(True))
    except ValueError as exc:
        assert "question" in str(exc)
    else:
        raise AssertionError("Expected empty-question rejection.")
    assert client.calls == []
    assert reserved == []


def test_oversized_question_is_rejected_before_usage_or_model(settings):
    settings = replace(settings, max_question_chars=20)
    client = FakeGemini()
    reserved = []
    try:
        answer_question(
            "How many annual leave days are included in the policy?",
            [],
            client=client,
            settings=settings,
            reserve_usage=lambda: reserved.append(True),
        )
    except ValueError as exc:
        assert "characters or fewer" in str(exc)
    else:
        raise AssertionError("Expected long question rejection.")
    assert client.calls == []
    assert reserved == []


def test_model_cannot_inject_untrusted_source_labels(settings):
    chunks = chunk_document(load_pasted_text("Leave Policy", "Employees receive 18 annual leave days."))
    result = answer_question(
        "How many annual leave days?",
        chunks,
        client=FakeGemini("The answer is 18. Sources: [S404]"),
        settings=settings,
    )
    assert result.found is False
    assert result.citations == ()
    assert "verifiable source" in result.answer


class ErrorModel:
    def __init__(self, errors):
        self.errors = list(errors)
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        outcome = self.errors.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class ErrorClient:
    def __init__(self, errors):
        self.models = ErrorModel(errors)


class APIError(Exception):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


def test_gemini_retries_only_transient_failure(settings):
    model = ErrorClient([APIError(503, "service unavailable"), type("Response", (), {"text": "OK"})()])
    client = GeminiClient(settings, client=model, sleep=lambda _: None)
    assert client.generate("question", system_instruction="rules", max_output_tokens=40) == "OK"
    assert model.models.calls == 2


def test_gemini_auth_and_quota_errors_are_not_retried(settings):
    for error, expected in [
        (APIError(401, "invalid API key"), GeminiAuthenticationError),
        (APIError(429, "resource exhausted"), GeminiQuotaError),
    ]:
        model = ErrorClient([error])
        client = GeminiClient(settings, client=model, sleep=lambda _: None)
        try:
            client.generate("question", system_instruction="rules", max_output_tokens=40)
        except expected:
            pass
        else:
            raise AssertionError(f"Expected {expected.__name__}")
        assert model.models.calls == 1


def test_gemini_malformed_and_empty_responses_fail(settings):
    client = GeminiClient(settings, client=ErrorClient([type("Response", (), {"text": ""})()]))
    try:
        client.generate("question", system_instruction="rules", max_output_tokens=40)
    except Exception as exc:
        assert "empty response" in str(exc)
    else:
        raise AssertionError("Expected an empty response failure.")
