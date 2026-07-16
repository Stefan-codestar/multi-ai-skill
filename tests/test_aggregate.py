from __future__ import annotations

from multiai.aggregate import AGGREGATOR_SYSTEM_PROMPT, Draft, synthesize


class FakeProvider:
    def __init__(self):
        self.last_messages = None
        self.last_model = None
        self.last_kwargs = None

    def complete(self, model: str, messages: list[dict[str, str]], **kwargs):
        self.last_messages = messages
        self.last_model = model
        self.last_kwargs = kwargs
        return "Synthese"


def test_synthesize_uses_only_ok_drafts_and_numbers_them():
    provider = FakeProvider()
    drafts = [
        Draft("a", "Antwort A", True, None, 0.1),
        Draft("b", "", False, "Fehler", 0.1),
        Draft("c", "Antwort C", True, None, 0.1),
    ]
    result = synthesize(provider, "Frage?", drafts, aggregator_model="glm-5.2")
    assert result == "Synthese"
    assert provider.last_model == "glm-5.2"
    system = provider.last_messages[0]["content"]
    assert "1. Antwort A" in system
    assert "2. Antwort C" in system
    assert "Antwort B" not in system
    assert provider.last_messages[1]["content"] == "Frage?"
    assert AGGREGATOR_SYSTEM_PROMPT in system
