from __future__ import annotations

from multiai.fanout import Draft, fan_out


class FakeProvider:
    def __init__(self, responses: dict[str, str], fail: set[str] | None = None):
        self.responses = responses
        self.fail = fail or set()
        self.calls = []

    def complete(self, model: str, messages: list[dict[str, str]], **kwargs):
        self.calls.append((model, messages, kwargs))
        if model in self.fail:
            raise RuntimeError(f"Modell {model} fehlgeschlagen")
        return self.responses.get(model, f"Antwort von {model}")


def test_fanout_collects_all_ok():
    provider = FakeProvider({"a": "A", "b": "B", "c": "C"})
    drafts = fan_out(provider, [{"role": "user", "content": "Q"}], ["a", "b", "c"])
    assert len(drafts) == 3
    assert [d.model for d in drafts] == ["a", "b", "c"]
    assert all(d.ok for d in drafts)
    assert [d.content for d in drafts] == ["A", "B", "C"]


def test_fanout_keeps_order():
    provider = FakeProvider({"a": "A", "b": "B"})
    drafts = fan_out(provider, [{"role": "user", "content": "Q"}], ["b", "a"])
    assert [d.model for d in drafts] == ["b", "a"]
    assert [d.content for d in drafts] == ["B", "A"]


def test_fanout_marks_failures():
    provider = FakeProvider({"a": "A", "b": "B"}, fail={"b"})
    drafts = fan_out(provider, [{"role": "user", "content": "Q"}], ["a", "b"])
    assert drafts[0].ok is True
    assert drafts[1].ok is False
    assert "fehlgeschlagen" in drafts[1].error


def test_fanout_passes_extra_body():
    provider = FakeProvider({"a": "A", "b": "B"})
    extra = {"reasoning_effort": "xhigh"}
    fan_out(provider, [{"role": "user", "content": "Q"}], ["a", "b"], extra_body=extra)
    assert len(provider.calls) == 2
    for model, messages, kwargs in provider.calls:
        assert kwargs.get("extra_body") == {"reasoning_effort": "xhigh"}


def test_fanout_extra_body_copied_per_call():
    seen_bodies = []

    class MutatingProvider:
        def complete(self, model, messages, **kwargs):
            eb = kwargs.get("extra_body")
            if eb is not None:
                eb["mutated_by"] = model
            seen_bodies.append(eb)
            return f"Antwort von {model}"

    provider = MutatingProvider()
    extra = {"reasoning_effort": "xhigh"}
    fan_out(provider, [{"role": "user", "content": "Q"}], ["a", "b", "c"], extra_body=extra)

    # Original dict darf nicht mutiert werden
    assert extra == {"reasoning_effort": "xhigh"}

    # Jeder Call bekommt eine eigene Kopie
    assert len(seen_bodies) == 3
    for eb in seen_bodies:
        assert eb is not extra
        assert eb["reasoning_effort"] == "xhigh"
        assert "mutated_by" in eb
