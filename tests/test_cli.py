from __future__ import annotations

import builtins
from pathlib import Path

import cli
from pinkydocs.config import Settings


class FakeGemini:
    def __init__(self):
        self.prompts = []

    def generate(self, prompt, *, system_instruction, max_output_tokens):
        self.prompts.append(prompt)
        if "Current user question:\nCan they be carried forward?" in prompt:
            return "Up to 5 unused days can be carried forward. [S1]\nSources: [S1]"
        return "Employees receive 18 annual leave days per calendar year. [S1]\nSources: [S1]"


def test_cli_loads_txt_and_answers_multiple_questions(monkeypatch, capsys):
    settings = Settings(gemini_api_key="test-key", gemini_model="test-model")
    client = FakeGemini()
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "GeminiClient", lambda _settings: client)
    responses = iter([
        "2",
        str(Path(__file__).resolve().parents[1] / "sample_documents" / "company_leave_policy.txt"),
        "How many annual leave days do employees receive?",
        "Can they be carried forward?",
        "exit",
    ])
    monkeypatch.setattr(builtins, "input", lambda _prompt="": next(responses))
    assert cli.main() == 0
    output = capsys.readouterr().out
    assert "Document loaded" in output
    assert "Employees receive 18 annual leave days" in output
    assert "Up to 5 unused days can be carried forward" in output
    assert output.count("Sources:") == 2
    assert len(client.prompts) == 2
    assert "How many annual leave days" in client.prompts[1]


def test_cli_pasted_text_input(monkeypatch):
    settings = Settings(gemini_api_key="test-key", gemini_model="test-model")
    responses = iter(["3", "Planning Notes", "The project review is Friday.", "END"])
    monkeypatch.setattr(builtins, "input", lambda _prompt="": next(responses))
    document = cli._load_input(settings)
    assert document.display_name == "Planning Notes"
    assert "Friday" in document.sections[0].text
