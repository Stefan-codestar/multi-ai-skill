from __future__ import annotations

from multiai.aggregate import (
    AGGREGATOR_SYSTEM_PROMPT,
    SYNTH_MARKER,
    build_synthesis_messages,
    concat_drafts,
    format_drafts_block,
    synthesize,
)
from multiai.fanout import Draft


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


def _drafts():
    return [
        Draft("a", "Antwort A", True, None, 0.1, role="Analytiker", seat=1),
        Draft("b", "", False, "Fehler", 0.1, role="Ingenieur", seat=2),
        Draft("c", "Antwort C", True, None, 0.1, role="Skeptiker", seat=3),
    ]


def test_synthesize_uses_only_ok_drafts_and_numbers_them():
    provider = FakeProvider()
    result = synthesize(provider, "Frage?", _drafts(), aggregator_model="glm-5.2")
    assert result == "Synthese"
    assert provider.last_model == "glm-5.2"
    system = provider.last_messages[0]["content"]
    assert "### 1. Analytiker (a)" in system
    assert "### 2. Skeptiker (c)" in system
    assert "### 2. Ingenieur (b)" not in system   # ausgefallener Sitz fehlt
    assert provider.last_messages[1]["content"] == "Frage?"
    assert AGGREGATOR_SYSTEM_PROMPT in system


def test_synthesis_messages_carry_marker():
    """Der Marker trennt Synthese-Calls von Sitz-Calls — Provider verlassen sich darauf."""
    messages = build_synthesis_messages("Frage?", _drafts())
    assert messages[0]["role"] == "system"
    assert SYNTH_MARKER in messages[0]["content"]


def test_format_drafts_block_falls_back_to_index_without_role():
    block = format_drafts_block([Draft("m", "Inhalt", True, None, 0.1)])
    assert "### 1. Beitrag 1" in block


def test_concat_drafts_labels_by_role_and_skips_failures():
    out = concat_drafts(_drafts())
    assert "## Analytiker (a)" in out
    assert "## Skeptiker (c)" in out
    assert "Ingenieur (b)" not in out
    assert "Antwort A" in out and "Antwort C" in out
